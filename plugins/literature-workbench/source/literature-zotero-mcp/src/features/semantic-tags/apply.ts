import { mkdir, rename, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import type { ToolContext } from '../../registry/registry.js';
import type { LibraryRef } from '../../api/web-client.js';
import {
  comparisonKey, semanticLabel, semanticPlanHash, semanticTag, stableUnique, validateRecommendation, vocabularyId,
  type ItemRecommendation, type SemanticTagPlan, type SemanticVocabulary, type VocabularyEntry,
} from './contract.js';
import {
  loadVocabulary, saveVocabulary, semanticTagsDirectory, vocabularyLookup, vocabularyPath, withVocabularyLock,
} from './vocabulary.js';

type Outcome = 'updated' | 'unchanged' | 'skipped' | 'conflicted' | 'failed';
interface ReceiptResult {
  item_key: string;
  outcome: Outcome;
  zotero_version: number | null;
  before_semantic_tags: string[];
  after_semantic_tags: string[];
  removed_automatic_tags: string[];
  error: string | null;
}

function dataOf(item: any): any { return item?.data ?? item ?? {}; }
function versionOf(item: any): number | null {
  const value = item?.version ?? item?.data?.version;
  return Number.isInteger(value) ? value : null;
}
function tagName(entry: any): string { return typeof entry === 'string' ? entry : String(entry?.tag ?? ''); }
function normalizedTag(entry: any): { tag: string; type?: number } {
  return typeof entry === 'string' ? { tag: entry } : entry?.type === undefined ? { tag: entry.tag } : { tag: entry.tag, type: entry.type };
}
function regularItem(data: any): boolean { return !['attachment', 'note', 'annotation'].includes(String(data.itemType ?? '')); }
function timestampName(): string { return new Date().toISOString().replace(/[:.]/g, '-'); }

async function persistJson(path: string, value: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.tmp-${process.pid}`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  await rename(temporary, path);
}

function resolveProposal(
  proposal: ReturnType<typeof validateRecommendation>['tags'][number],
  vocabulary: SemanticVocabulary,
  stagedNew: Map<string, VocabularyEntry>,
  now: string,
): VocabularyEntry {
  const lookup = vocabularyLookup({ ...vocabulary, tags: [...vocabulary.tags, ...stagedNew.values()] });
  const byId = proposal.vocabulary_id ? lookup.get(proposal.vocabulary_id) : undefined;
  const byLabel = lookup.get(comparisonKey(proposal.canonical));
  const byAlias = proposal.matched_alias ? lookup.get(comparisonKey(proposal.matched_alias)) : undefined;
  if (proposal.decision === 'reuse') {
    const matches = [byId, byLabel, byAlias].filter(Boolean) as VocabularyEntry[];
    const unique = [...new Map(matches.map((entry) => [entry.id, entry])).values()];
    if (unique.length !== 1) throw new Error(`Reuse tag ${proposal.canonical} must resolve to exactly one vocabulary entry`);
    const entry = unique[0]!;
    if (entry.dimension !== proposal.dimension) {
      throw new Error(`Reuse tag ${proposal.canonical} dimension conflicts with vocabulary entry ${entry.id}`);
    }
    return entry;
  }
  if (byLabel && stagedNew.has(byLabel.id)) {
    if (byLabel.dimension !== proposal.dimension || comparisonKey(byLabel.description) !== comparisonKey(proposal.description!)) {
      throw new Error(`New tag ${proposal.canonical} has inconsistent definitions within this batch`);
    }
    const currentLookup = vocabularyLookup({ ...vocabulary, tags: [...vocabulary.tags, ...stagedNew.values()] });
    for (const alias of proposal.aliases ?? []) {
      const collision = currentLookup.get(comparisonKey(alias));
      if (collision && collision.id !== byLabel.id) {
        throw new Error(`New tag alias ${alias} collides with ${collision.id}`);
      }
    }
    byLabel.aliases = [...new Map([...byLabel.aliases, ...(proposal.aliases ?? [])]
      .map((alias) => [comparisonKey(alias), alias])).values()];
    return byLabel;
  }
  if (byId || byLabel || byAlias) throw new Error(`New tag ${proposal.canonical} collides with an existing vocabulary entry`);
  for (const alias of proposal.aliases ?? []) {
    if (lookup.has(comparisonKey(alias))) throw new Error(`New tag alias ${alias} collides with an existing vocabulary entry`);
  }
  const id = vocabularyId(proposal.canonical);
  if (lookup.has(id)) throw new Error(`New tag ${proposal.canonical} generated duplicate id ${id}`);
  const entry: VocabularyEntry = {
    id, canonical: proposal.canonical, dimension: proposal.dimension,
    aliases: proposal.aliases ?? [], description: proposal.description!, usage_count: 0,
    collection_keys: [], created_at: now, updated_at: now,
  };
  stagedNew.set(id, entry);
  return entry;
}

export async function executeSemanticTags(
  ctx: ToolContext,
  library: LibraryRef,
  input: {
    scope: { type: 'items' | 'collection'; collection_key?: string };
    vocabulary_revision: number;
    cleanup_auto_tags: boolean;
    items: ItemRecommendation[];
  },
): Promise<Record<string, unknown>> {
  return withVocabularyLock(ctx.config.dataDir, library, async () => {
    const vocabulary = await loadVocabulary(ctx.config.dataDir, library);
    if (vocabulary.revision !== input.vocabulary_revision) {
      throw new Error(`Semantic vocabulary revision changed: expected ${input.vocabulary_revision}, current ${vocabulary.revision}`);
    }
    const recommendations = input.items.map(validateRecommendation);
    const duplicateKeys = recommendations.map((item) => item.item_key)
      .filter((key, index, all) => all.indexOf(key) !== index);
    if (duplicateKeys.length) throw new Error(`Duplicate recommendation item keys: ${[...new Set(duplicateKeys)].join(', ')}`);
    const now = new Date().toISOString();
    const stagedNew = new Map<string, VocabularyEntry>();
    const fetched = new Map<string, any>();
    const desiredByItem = new Map<string, Array<{
      entry: VocabularyEntry;
      proposal: ReturnType<typeof validateRecommendation>['tags'][number];
    }>>();

    for (const recommendation of recommendations) {
      const item = await ctx.web.getItem(library, recommendation.item_key);
      fetched.set(recommendation.item_key, item);
      const desired = recommendation.tags.map((proposal) => ({
        entry: resolveProposal(proposal, vocabulary, stagedNew, now), proposal,
      }));
      desiredByItem.set(recommendation.item_key, desired);
    }

    const aliasOwners = new Map<string, string>();
    for (const entry of [...vocabulary.tags, ...stagedNew.values()]) {
      for (const label of [entry.canonical, ...entry.aliases]) aliasOwners.set(comparisonKey(label), entry.id);
    }
    for (const desired of desiredByItem.values()) {
      for (const { entry, proposal } of desired) {
        for (const alias of proposal.aliases ?? []) {
          const key = comparisonKey(alias);
          const owner = aliasOwners.get(key);
          if (owner && owner !== entry.id) throw new Error(`Proposed alias ${alias} collides with vocabulary entry ${owner}`);
          aliasOwners.set(key, entry.id);
        }
      }
    }

    const actions: SemanticTagPlan['actions'] = recommendations.map((recommendation) => {
      const item = fetched.get(recommendation.item_key);
      const data = dataOf(item);
      const currentVersion = versionOf(item);
      const rawTags = Array.isArray(data.tags) ? data.tags : [];
      const beforeSemantic = rawTags.map(tagName).filter((tag: string) => semanticLabel(tag));
      const beforeAutomatic = rawTags.filter((tag: any) => typeof tag !== 'string' && tag?.type === 1).map(tagName);
      const desired = desiredByItem.get(recommendation.item_key) ?? [];
      const retained = rawTags.filter((entry: any) => {
        const tag = tagName(entry);
        if (semanticLabel(tag)) return false;
        if (input.cleanup_auto_tags && typeof entry !== 'string' && entry?.type === 1) return false;
        return Boolean(tag);
      }).map(normalizedTag);
      const finalTags = [...retained, ...desired.map(({ entry }) => ({ tag: semanticTag(entry.canonical) }))];
      const reasonCodes: string[] = [];
      let decision: 'update' | 'unchanged' | 'skip' = 'update';
      if (!regularItem(data)) { decision = 'skip'; reasonCodes.push('non-bibliographic-item'); }
      else if (currentVersion !== recommendation.expected_version) { decision = 'skip'; reasonCodes.push('version-conflict'); }
      else if (JSON.stringify(finalTags) === JSON.stringify(rawTags.map(normalizedTag))) { decision = 'unchanged'; reasonCodes.push('already-current'); }
      if (!desired.length) reasonCodes.push('no-confident-tag');
      return {
        item_key: recommendation.item_key, expected_version: recommendation.expected_version,
        title: String(data.title ?? '(untitled)'), evidence_depth: recommendation.evidence_depth,
        desired: desired.map(({ entry, proposal }) => ({
          id: entry.id, canonical: entry.canonical, dimension: entry.dimension,
          decision: proposal.decision, aliases: proposal.aliases ?? [],
          ...(proposal.description ? { description: proposal.description } : {}),
        })),
        before_semantic_tags: beforeSemantic, before_automatic_tags: beforeAutomatic,
        final_tags: finalTags, decision, reason_codes: reasonCodes,
      };
    });
    const plan: SemanticTagPlan = {
      schema_version: '1.0', plan_type: 'zotero-semantic-tags', created_at: now, plan_hash: '',
      target: { library_type: library.type, library_id: library.id }, scope: input.scope,
      vocabulary_revision: vocabulary.revision, cleanup_auto_tags: input.cleanup_auto_tags, actions,
    };
    plan.plan_hash = semanticPlanHash(plan);
    const root = semanticTagsDirectory(ctx.config.dataDir, library);
    const stem = `${timestampName()}-${plan.plan_hash.slice(-12)}`;
    const planPath = join(root, 'plans', `${stem}.json`);
    const receiptPath = join(root, 'receipts', `${stem}.json`);
    await persistJson(planPath, plan);

    const results: ReceiptResult[] = [];
    const successfulActions: SemanticTagPlan['actions'] = [];
    for (const action of actions) {
      if (action.decision === 'skip') {
        results.push({ item_key: action.item_key, outcome: action.reason_codes.includes('version-conflict') ? 'conflicted' : 'skipped',
          zotero_version: action.expected_version, before_semantic_tags: action.before_semantic_tags,
          after_semantic_tags: action.before_semantic_tags, removed_automatic_tags: [], error: action.reason_codes.join(';') });
        continue;
      }
      if (action.decision === 'unchanged') {
        successfulActions.push(action);
        results.push({ item_key: action.item_key, outcome: 'unchanged', zotero_version: action.expected_version,
          before_semantic_tags: action.before_semantic_tags, after_semantic_tags: action.before_semantic_tags,
          removed_automatic_tags: [], error: null });
        continue;
      }
      try {
        const newVersion = await ctx.web.patchItem(library, action.item_key, { tags: action.final_tags }, action.expected_version);
        successfulActions.push(action);
        results.push({ item_key: action.item_key, outcome: 'updated', zotero_version: newVersion,
          before_semantic_tags: action.before_semantic_tags,
          after_semantic_tags: action.desired.map((entry) => semanticTag(entry.canonical)),
          removed_automatic_tags: input.cleanup_auto_tags ? action.before_automatic_tags : [], error: null });
      } catch (error) {
        results.push({ item_key: action.item_key, outcome: 'failed', zotero_version: action.expected_version,
          before_semantic_tags: action.before_semantic_tags, after_semantic_tags: action.before_semantic_tags,
          removed_automatic_tags: [], error: (error instanceof Error ? error.message : String(error)).slice(0, 500) });
      }
    }

    const entryById = new Map(vocabulary.tags.map((entry) => [entry.id, entry]));
    let vocabularyChanged = false;
    for (const action of successfulActions) {
      const beforeLabels = new Set(action.before_semantic_tags.map((tag) => comparisonKey(semanticLabel(tag) ?? '')));
      const afterIds = new Set(action.desired.map((desired) => desired.id));
      for (const entry of vocabulary.tags) {
        if (beforeLabels.has(comparisonKey(entry.canonical)) && !afterIds.has(entry.id)) {
          const nextUsage = Math.max(0, entry.usage_count - 1);
          if (nextUsage !== entry.usage_count) {
            entry.usage_count = nextUsage;
            entry.updated_at = now;
            vocabularyChanged = true;
          }
        }
      }
      for (const desired of action.desired) {
        let entry = entryById.get(desired.id);
        let entryChanged = false;
        if (!entry) {
          const staged = stagedNew.get(desired.id);
          if (!staged) continue;
          entry = structuredClone(staged);
          vocabulary.tags.push(entry);
          entryById.set(entry.id, entry);
          entry.usage_count += 1;
          entryChanged = true;
        }
        else if (!beforeLabels.has(comparisonKey(entry.canonical))) {
          entry.usage_count += 1;
          entryChanged = true;
        }
        const nextAliases = stableUnique([...entry.aliases, ...desired.aliases])
          .filter((alias) => comparisonKey(alias) !== comparisonKey(entry.canonical));
        if (JSON.stringify(nextAliases) !== JSON.stringify(entry.aliases)) {
          entry.aliases = nextAliases;
          entryChanged = true;
        }
        if (input.scope.collection_key && !entry.collection_keys.includes(input.scope.collection_key)) {
          entry.collection_keys.push(input.scope.collection_key);
          entry.collection_keys.sort();
          entryChanged = true;
        }
        if (entryChanged) {
          entry.updated_at = now;
          vocabularyChanged = true;
        }
      }
    }
    let vocabularyError: string | null = null;
    if (vocabularyChanged) {
      vocabulary.revision += 1;
      vocabulary.updated_at = now;
      vocabulary.tags.sort((left, right) => left.canonical.localeCompare(right.canonical, 'en'));
      try { await saveVocabulary(vocabularyPath(ctx.config.dataDir, library), vocabulary); }
      catch (error) { vocabularyError = error instanceof Error ? error.message : String(error); }
    }
    const counts = Object.fromEntries(['updated', 'unchanged', 'skipped', 'conflicted', 'failed']
      .map((outcome) => [outcome, results.filter((result) => result.outcome === outcome).length]));
    const receipt = {
      schema_version: '1.0', receipt_type: 'zotero-semantic-tags', plan_hash: plan.plan_hash,
      status: vocabularyError || counts.failed || counts.conflicted ? 'partial' : 'complete',
      started_at: now, updated_at: new Date().toISOString(), vocabulary_revision_before: input.vocabulary_revision,
      vocabulary_revision_after: vocabularyError ? input.vocabulary_revision : vocabulary.revision,
      vocabulary_error: vocabularyError, results, summary: counts,
    };
    await persistJson(receiptPath, receipt);
    return { status: receipt.status, plan_hash: plan.plan_hash, plan_path: planPath, receipt_path: receiptPath,
      vocabulary_revision: receipt.vocabulary_revision_after, vocabulary_error: vocabularyError, summary: counts };
  });
}
