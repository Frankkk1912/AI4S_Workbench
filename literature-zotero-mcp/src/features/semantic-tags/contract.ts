import { createHash } from 'node:crypto';

export const SEMANTIC_TAG_PREFIX = 'AI4S:Semantic:';
export const SEMANTIC_DIMENSIONS = ['topic', 'entity', 'method', 'mechanism'] as const;
export type SemanticDimension = (typeof SEMANTIC_DIMENSIONS)[number];
export type EvidenceDepth = 'title-abstract' | 'metadata-only';

export interface VocabularyEntry {
  id: string;
  canonical: string;
  dimension: SemanticDimension;
  aliases: string[];
  description: string;
  usage_count: number;
  collection_keys: string[];
  created_at: string;
  updated_at: string;
}

export interface SemanticVocabulary {
  schema_version: '1.0';
  artifact_type: 'ai4s-semantic-tag-vocabulary';
  library: { type: 'user' | 'group'; id: number };
  language: 'en';
  revision: number;
  updated_at: string;
  tags: VocabularyEntry[];
}

export interface TagProposal {
  canonical: string;
  dimension: SemanticDimension;
  decision: 'reuse' | 'new';
  vocabulary_id?: string;
  matched_alias?: string;
  aliases?: string[];
  description?: string;
}

export interface ItemRecommendation {
  item_key: string;
  expected_version: number;
  evidence_depth: EvidenceDepth;
  tags: TagProposal[];
}

export interface SemanticTagPlan {
  schema_version: '1.0';
  plan_type: 'zotero-semantic-tags';
  created_at: string;
  plan_hash: string;
  target: { library_type: 'user' | 'group'; library_id: number };
  scope: { type: 'items' | 'collection'; collection_key?: string };
  vocabulary_revision: number;
  cleanup_auto_tags: boolean;
  actions: Array<{
    item_key: string;
    expected_version: number;
    title: string;
    evidence_depth: EvidenceDepth;
    desired: Array<{
      id: string;
      canonical: string;
      dimension: SemanticDimension;
      decision: 'reuse' | 'new';
      aliases: string[];
      description?: string;
    }>;
    before_semantic_tags: string[];
    before_automatic_tags: string[];
    final_tags: Array<{ tag: string; type?: number }>;
    decision: 'update' | 'unchanged' | 'skip';
    reason_codes: string[];
  }>;
}

function normalizedText(value: unknown, label: string, max = 80): string {
  if (typeof value !== 'string') throw new Error(`${label} must be a string`);
  const text = value.replace(/\s+/g, ' ').trim();
  if (!text || text.length > max || /[\r\n\0]/.test(value)) {
    throw new Error(`${label} must contain 1-${max} printable characters`);
  }
  if (/\p{Script=Han}/u.test(text)) throw new Error(`${label} must use English scientific terminology`);
  return text;
}

export function canonicalLabel(value: unknown): string {
  const text = normalizedText(value, 'canonical');
  if (text.startsWith('AI4S:')) throw new Error('canonical must not contain an AI4S namespace prefix');
  return text;
}

export function normalizedAlias(value: unknown): string {
  return normalizedText(value, 'alias');
}

export function comparisonKey(value: string): string {
  return value.normalize('NFKC').replace(/[‐‑‒–—−]/g, '-').replace(/\s+/g, ' ').trim().toLocaleLowerCase('en-US');
}

export function semanticTag(canonical: string): string {
  return `${SEMANTIC_TAG_PREFIX}${canonical}`;
}

export function semanticLabel(tag: string): string | null {
  if (!tag.startsWith(SEMANTIC_TAG_PREFIX)) return null;
  const label = tag.slice(SEMANTIC_TAG_PREFIX.length).trim();
  return label || null;
}

export function vocabularyId(canonical: string): string {
  const slug = canonical
    .normalize('NFKD')
    .toLocaleLowerCase('en-US')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 56);
  const suffix = createHash('sha256').update(comparisonKey(canonical)).digest('hex').slice(0, 8);
  return `semantic:${slug || 'term'}-${suffix}`;
}

export function stableUnique(values: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    const key = comparisonKey(value);
    if (!seen.has(key)) {
      seen.add(key);
      result.push(value);
    }
  }
  return result;
}

export function validateRecommendation(item: ItemRecommendation): ItemRecommendation {
  if (!/^[A-Z0-9]{8}$/.test(item.item_key)) throw new Error(`Invalid Zotero item key: ${item.item_key}`);
  if (!Number.isInteger(item.expected_version) || item.expected_version < 0) {
    throw new Error(`${item.item_key}.expected_version must be a non-negative integer`);
  }
  if (!['title-abstract', 'metadata-only'].includes(item.evidence_depth)) {
    throw new Error(`${item.item_key}.evidence_depth is invalid`);
  }
  if (!Array.isArray(item.tags) || item.tags.length > 4) {
    throw new Error(`${item.item_key} must contain zero to four semantic tags`);
  }
  if (item.evidence_depth === 'metadata-only' && item.tags.length > 2) {
    throw new Error(`${item.item_key} metadata-only recommendations may contain at most two tags`);
  }
  const seen = new Set<string>();
  const tags = item.tags.map((raw, index) => {
    const canonical = canonicalLabel(raw.canonical);
    const key = comparisonKey(canonical);
    if (seen.has(key)) throw new Error(`${item.item_key} contains duplicate canonical tag ${canonical}`);
    seen.add(key);
    if (!SEMANTIC_DIMENSIONS.includes(raw.dimension)) {
      throw new Error(`${item.item_key}.tags[${index}].dimension is invalid`);
    }
    if (item.evidence_depth === 'metadata-only' && raw.dimension === 'mechanism') {
      throw new Error(`${item.item_key} metadata-only recommendations may not contain mechanism tags`);
    }
    if (!['reuse', 'new'].includes(raw.decision)) {
      throw new Error(`${item.item_key}.tags[${index}].decision is invalid`);
    }
    const aliases = stableUnique((raw.aliases ?? []).map(normalizedAlias)).filter(
      (alias) => comparisonKey(alias) !== key,
    );
    const description = raw.description === undefined
      ? undefined
      : normalizedText(raw.description, 'description', 240);
    if (raw.decision === 'new' && !description) {
      throw new Error(`${item.item_key} new tag ${canonical} requires a short description`);
    }
    return {
      canonical,
      dimension: raw.dimension,
      decision: raw.decision,
      ...(raw.vocabulary_id ? { vocabulary_id: normalizedText(raw.vocabulary_id, 'vocabulary_id', 100) } : {}),
      ...(raw.matched_alias ? { matched_alias: normalizedAlias(raw.matched_alias) } : {}),
      ...(aliases.length ? { aliases } : {}),
      ...(description ? { description } : {}),
    };
  });
  return { ...item, tags };
}

function deepSort(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(deepSort);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>)
      .filter(([key]) => key !== 'plan_hash')
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, entry]) => [key, deepSort(entry)]));
  }
  return value;
}

export function semanticPlanHash(plan: SemanticTagPlan): string {
  const canonical = JSON.stringify(deepSort(plan));
  return `sha256:${createHash('sha256').update(canonical).digest('hex')}`;
}
