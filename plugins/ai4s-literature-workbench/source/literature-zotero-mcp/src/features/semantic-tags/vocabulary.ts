import { mkdir, open, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import type { LibraryRef } from '../../api/web-client.js';
import {
  SEMANTIC_DIMENSIONS,
  canonicalLabel,
  comparisonKey,
  normalizedAlias,
  stableUnique,
  type SemanticVocabulary,
  type VocabularyEntry,
} from './contract.js';

export function semanticTagsDirectory(dataDir: string, library: LibraryRef): string {
  return join(dataDir, 'semantic-tags', `${library.type}-${library.id}`);
}

export function vocabularyPath(dataDir: string, library: LibraryRef): string {
  return join(semanticTagsDirectory(dataDir, library), 'vocabulary.json');
}

export function emptyVocabulary(library: LibraryRef): SemanticVocabulary {
  return {
    schema_version: '1.0',
    artifact_type: 'ai4s-semantic-tag-vocabulary',
    library: { type: library.type, id: library.id },
    language: 'en',
    revision: 0,
    updated_at: new Date(0).toISOString(),
    tags: [],
  };
}

export function validateVocabulary(value: unknown, expected?: LibraryRef): SemanticVocabulary {
  if (!value || typeof value !== 'object') throw new Error('Semantic vocabulary must be a JSON object');
  const raw = value as any;
  if (raw.schema_version !== '1.0' || raw.artifact_type !== 'ai4s-semantic-tag-vocabulary') {
    throw new Error('Unsupported semantic vocabulary schema or artifact type');
  }
  if (!raw.library || !['user', 'group'].includes(raw.library.type) || !Number.isInteger(raw.library.id)) {
    throw new Error('Semantic vocabulary library is invalid');
  }
  if (expected && (raw.library.type !== expected.type || raw.library.id !== expected.id)) {
    throw new Error('Semantic vocabulary belongs to a different Zotero library');
  }
  if (raw.language !== 'en' || !Number.isInteger(raw.revision) || raw.revision < 0 || !Array.isArray(raw.tags)) {
    throw new Error('Semantic vocabulary language, revision, or tags are invalid');
  }
  const ids = new Set<string>();
  const names = new Map<string, string>();
  const tags: VocabularyEntry[] = raw.tags.map((entry: any, index: number) => {
    const id = typeof entry.id === 'string' ? entry.id.trim() : '';
    const canonical = canonicalLabel(entry.canonical);
    if (!id.startsWith('semantic:') || ids.has(id)) throw new Error(`Vocabulary tag ${index} has an invalid or duplicate id`);
    ids.add(id);
    if (!SEMANTIC_DIMENSIONS.includes(entry.dimension)) throw new Error(`Vocabulary tag ${id} has an invalid dimension`);
    const aliases = stableUnique((Array.isArray(entry.aliases) ? entry.aliases : []).map(normalizedAlias))
      .filter((alias) => comparisonKey(alias) !== comparisonKey(canonical));
    for (const label of [canonical, ...aliases]) {
      const key = comparisonKey(label);
      const owner = names.get(key);
      if (owner && owner !== id) throw new Error(`Vocabulary label collision between ${owner} and ${id}: ${label}`);
      names.set(key, id);
    }
    if (typeof entry.description !== 'string' || !entry.description.trim()) {
      throw new Error(`Vocabulary tag ${id} requires a description`);
    }
    if (!Number.isInteger(entry.usage_count) || entry.usage_count < 0) {
      throw new Error(`Vocabulary tag ${id} has an invalid usage_count`);
    }
    return {
      id,
      canonical,
      dimension: entry.dimension,
      aliases,
      description: entry.description.replace(/\s+/g, ' ').trim().slice(0, 240),
      usage_count: entry.usage_count,
      collection_keys: stableUnique((Array.isArray(entry.collection_keys) ? entry.collection_keys : [])
        .filter((key: unknown) => typeof key === 'string' && /^[A-Z0-9]{8}$/.test(key))),
      created_at: typeof entry.created_at === 'string' ? entry.created_at : new Date(0).toISOString(),
      updated_at: typeof entry.updated_at === 'string' ? entry.updated_at : new Date(0).toISOString(),
    };
  });
  return {
    schema_version: '1.0', artifact_type: 'ai4s-semantic-tag-vocabulary',
    library: { type: raw.library.type, id: raw.library.id }, language: 'en',
    revision: raw.revision, updated_at: typeof raw.updated_at === 'string' ? raw.updated_at : new Date(0).toISOString(),
    tags: tags.sort((left, right) => left.canonical.localeCompare(right.canonical, 'en')),
  };
}

export async function loadVocabulary(dataDir: string, library: LibraryRef): Promise<SemanticVocabulary> {
  const path = vocabularyPath(dataDir, library);
  try {
    return validateVocabulary(JSON.parse(await readFile(path, 'utf8')), library);
  } catch (error: any) {
    if (error?.code === 'ENOENT') return emptyVocabulary(library);
    throw new Error(`Could not load semantic vocabulary ${path}: ${error instanceof Error ? error.message : String(error)}`);
  }
}

export async function saveVocabulary(path: string, vocabulary: SemanticVocabulary): Promise<void> {
  const checked = validateVocabulary(vocabulary, vocabulary.library);
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.tmp-${process.pid}-${Date.now()}`;
  await writeFile(temporary, `${JSON.stringify(checked, null, 2)}\n`, 'utf8');
  await rename(temporary, path);
}

export async function withVocabularyLock<T>(dataDir: string, library: LibraryRef, task: () => Promise<T>): Promise<T> {
  const directory = semanticTagsDirectory(dataDir, library);
  const lockPath = join(directory, 'vocabulary.lock');
  await mkdir(directory, { recursive: true });
  let handle;
  try {
    handle = await open(lockPath, 'wx');
  } catch (error: any) {
    if (error?.code === 'EEXIST') throw new Error(`Semantic vocabulary is busy: ${lockPath}`);
    throw error;
  }
  try {
    return await task();
  } finally {
    await handle.close().catch(() => undefined);
    await unlink(lockPath).catch(() => undefined);
  }
}

export function vocabularyLookup(vocabulary: SemanticVocabulary): Map<string, VocabularyEntry> {
  const lookup = new Map<string, VocabularyEntry>();
  for (const entry of vocabulary.tags) {
    lookup.set(entry.id, entry);
    for (const label of [entry.canonical, ...entry.aliases]) lookup.set(comparisonKey(label), entry);
  }
  return lookup;
}

function tokens(text: string): Set<string> {
  return new Set(text.toLocaleLowerCase('en-US').split(/[^a-z0-9]+/).filter((token) => token.length >= 3));
}

export function selectVocabularyEntries(
  vocabulary: SemanticVocabulary,
  text: string,
  collectionKey: string | undefined,
  limit: number,
): { entries: VocabularyEntry[]; total: number; truncated: boolean } {
  const queryTokens = tokens(text);
  const scored = vocabulary.tags.map((entry) => {
    const labels = tokens([entry.canonical, ...entry.aliases, entry.description].join(' '));
    let lexical = 0;
    for (const token of queryTokens) if (labels.has(token)) lexical += 1;
    const inCollection = collectionKey && entry.collection_keys.includes(collectionKey) ? 1 : 0;
    return { entry, inCollection, lexical };
  }).sort((left, right) =>
    right.inCollection - left.inCollection || right.lexical - left.lexical ||
    right.entry.usage_count - left.entry.usage_count || left.entry.canonical.localeCompare(right.entry.canonical, 'en'));
  return { entries: scored.slice(0, limit).map(({ entry }) => entry), total: scored.length, truncated: scored.length > limit };
}
