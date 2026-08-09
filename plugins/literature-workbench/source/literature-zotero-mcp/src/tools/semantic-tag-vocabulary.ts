import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { z } from 'zod';
import type { LibraryRef } from '../api/web-client.js';
import type { ToolDefinition } from '../registry/registry.js';
import { ok } from '../registry/registry.js';
import { comparisonKey, stableUnique } from '../features/semantic-tags/contract.js';
import {
  loadVocabulary, saveVocabulary, semanticTagsDirectory, validateVocabulary,
  vocabularyLookup, vocabularyPath, withVocabularyLock,
} from '../features/semantic-tags/vocabulary.js';

function timestampName(): string { return new Date().toISOString().replace(/[:.]/g, '-'); }

const semanticTagVocabulary: ToolDefinition = {
  name: 'zotero_semantic_tag_vocabulary',
  title: 'Manage semantic-tag vocabulary JSON',
  description:
    'Inspect, export, or merge-import the library-scoped English semantic-tag vocabulary. Import requires the current expected revision, validates all canonical/alias collisions, and never silently replaces incompatible entries.',
  inputSchema: {
    action: z.enum(['inspect', 'export', 'import']),
    path: z.string().optional().describe('Export destination or required import source JSON path.'),
    expected_revision: z.number().int().min(0).optional().describe('Required for import.'),
    limit: z.number().int().min(1).max(500).optional().describe('Inspect entry limit (default 100).'),
    library_type: z.enum(['user', 'group']).optional(),
    library_id: z.number().int().optional(),
  },
  annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
  handler: async (args, ctx) => {
    const library: LibraryRef = args.library_id
      ? { type: args.library_type ?? 'group', id: args.library_id }
      : ctx.router.defaultLibrary();
    const current = await loadVocabulary(ctx.config.dataDir, library);
    if (args.action === 'inspect') {
      const limit = args.limit ?? 100;
      return ok({ library, revision: current.revision, total: current.tags.length,
        entries: current.tags.slice(0, limit), truncated: current.tags.length > limit,
        path: vocabularyPath(ctx.config.dataDir, library) },
      `Semantic vocabulary revision ${current.revision}: ${current.tags.length} entries.`);
    }
    if (args.action === 'export') {
      const path = args.path ?? join(semanticTagsDirectory(ctx.config.dataDir, library), 'exports', `vocabulary-${timestampName()}.json`);
      await mkdir(dirname(path), { recursive: true });
      await writeFile(path, `${JSON.stringify(current, null, 2)}\n`, 'utf8');
      return ok({ path, revision: current.revision, entries: current.tags.length }, `Exported semantic vocabulary to ${path}.`);
    }
    if (!args.path) throw new Error('path is required for vocabulary import');
    if (args.expected_revision === undefined) throw new Error('expected_revision is required for vocabulary import');
    const incoming = validateVocabulary(JSON.parse(await readFile(args.path, 'utf8')), library);
    const result = await withVocabularyLock(ctx.config.dataDir, library, async () => {
      const vocabulary = await loadVocabulary(ctx.config.dataDir, library);
      if (vocabulary.revision !== args.expected_revision) {
        throw new Error(`Semantic vocabulary revision changed: expected ${args.expected_revision}, current ${vocabulary.revision}`);
      }
      let added = 0;
      let merged = 0;
      for (const imported of incoming.tags) {
        const lookup = vocabularyLookup(vocabulary);
        const matches = [lookup.get(imported.id), lookup.get(comparisonKey(imported.canonical)),
          ...imported.aliases.map((alias) => lookup.get(comparisonKey(alias)))]
          .filter(Boolean);
        const unique = [...new Map(matches.map((entry) => [entry!.id, entry!])).values()];
        if (unique.length > 1) throw new Error(`Imported entry ${imported.id} collides with multiple current entries`);
        if (!unique.length) {
          vocabulary.tags.push(structuredClone(imported));
          added += 1;
          continue;
        }
        const existing = unique[0]!;
        if (existing.dimension !== imported.dimension) {
          throw new Error(`Imported entry ${imported.id} conflicts with ${existing.id} on dimension`);
        }
        const otherLookup = vocabularyLookup({ ...vocabulary, tags: vocabulary.tags.filter((entry) => entry.id !== existing.id) });
        for (const alias of [imported.canonical, ...imported.aliases]) {
          const collision = otherLookup.get(comparisonKey(alias));
          if (collision) throw new Error(`Imported label ${alias} collides with ${collision.id}`);
        }
        existing.aliases = stableUnique([...existing.aliases, imported.canonical, ...imported.aliases])
          .filter((alias) => comparisonKey(alias) !== comparisonKey(existing.canonical));
        existing.collection_keys = stableUnique([...existing.collection_keys, ...imported.collection_keys]).sort();
        existing.usage_count = Math.max(existing.usage_count, imported.usage_count);
        existing.updated_at = new Date().toISOString();
        merged += 1;
      }
      vocabulary.revision += 1;
      vocabulary.updated_at = new Date().toISOString();
      vocabulary.tags.sort((left, right) => left.canonical.localeCompare(right.canonical, 'en'));
      await saveVocabulary(vocabularyPath(ctx.config.dataDir, library), vocabulary);
      return { revision: vocabulary.revision, entries: vocabulary.tags.length, added, merged };
    });
    return ok({ source_path: args.path, ...result }, `Imported semantic vocabulary: added=${result.added}, merged=${result.merged}, revision=${result.revision}.`);
  },
};

export default semanticTagVocabulary;
