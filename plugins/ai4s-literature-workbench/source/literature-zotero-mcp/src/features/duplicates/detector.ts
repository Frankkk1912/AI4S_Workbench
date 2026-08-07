export type DuplicateConfidence = 'high' | 'medium' | 'review';

export interface DuplicateCluster {
  cluster_id: string;
  batch_item_keys: string[];
  items: Array<Record<string, unknown>>;
  confidence: DuplicateConfidence;
  reasons: string[];
  field_conflicts: string[];
  recommended_master_key: string;
  master_reason: string;
  native_merge_required: true;
}

interface Identity {
  key: string;
  item: any;
  itemType: string;
  title: string;
  titleTokens: string[];
  titleBlock: string;
  doi: string;
  pmid: string;
  isbn: string;
  year?: number;
  creators: string[];
  isCorrection: boolean;
}

interface PairMatch {
  a: string;
  b: string;
  confidence: DuplicateConfidence;
  reasons: string[];
  conflicts: string[];
}

const CONFIDENCE_RANK: Record<DuplicateConfidence, number> = { review: 1, medium: 2, high: 3 };
const NON_BIBLIOGRAPHIC_TYPES = new Set(['attachment', 'note', 'annotation']);
const CORRECTION_PREFIX = /^\s*(correction|corrigendum|erratum|retraction|retracted)\b/i;

function dataOf(item: any): any {
  return item?.data ?? item ?? {};
}

function normalizeText(value: unknown): string {
  return String(value ?? '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

function normalizeDoi(value: unknown): string {
  return String(value ?? '')
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\/(?:dx\.)?doi\.org\//, '')
    .replace(/^doi:\s*/, '')
    .replace(/[\s.,;]+$/, '');
}

function extractPmid(data: any): string {
  const direct = String(data.PMID ?? data.pmid ?? '').match(/\d{5,}/)?.[0];
  if (direct) return direct;
  return String(data.extra ?? '').match(/(?:^|\n)\s*PMID\s*:\s*(\d{5,})/i)?.[1] ?? '';
}

function normalizeIsbn(value: unknown): string {
  return String(value ?? '')
    .toUpperCase()
    .replace(/[^0-9X]/g, '');
}

function yearOf(value: unknown): number | undefined {
  const match = String(value ?? '').match(/(?:18|19|20|21)\d{2}/);
  return match ? Number(match[0]) : undefined;
}

function creatorKeys(creators: any[] = []): string[] {
  return creators
    .map((creator) => {
      const last = normalizeText(creator.lastName ?? creator.name);
      const first = normalizeText(creator.firstName).slice(0, 1);
      return last ? `${last}:${first}` : '';
    })
    .filter(Boolean);
}

function titleTokens(title: string): string[] {
  return [
    ...new Set(
      normalizeText(title)
        .split(' ')
        .filter((token) => token.length > 1),
    ),
  ];
}

function titleBlock(tokens: string[]): string {
  return [...tokens].sort().slice(0, 4).join('|');
}

function identity(item: any): Identity | null {
  const data = dataOf(item);
  const key = String(item?.key ?? data.key ?? '');
  const itemType = String(data.itemType ?? '');
  if (!key || NON_BIBLIOGRAPHIC_TYPES.has(itemType) || data.deleted) return null;
  const title = String(data.title ?? data.caseName ?? data.subject ?? '');
  const tokens = titleTokens(title);
  return {
    key,
    item,
    itemType,
    title,
    titleTokens: tokens,
    titleBlock: titleBlock(tokens),
    doi: normalizeDoi(data.DOI),
    pmid: extractPmid(data),
    isbn: normalizeIsbn(data.ISBN),
    year: yearOf(data.date ?? data.year),
    creators: creatorKeys(data.creators),
    isCorrection: CORRECTION_PREFIX.test(title),
  };
}

function jaccard(a: string[], b: string[]): number {
  if (!a.length || !b.length) return 0;
  const left = new Set(a);
  const right = new Set(b);
  let intersection = 0;
  for (const value of left) if (right.has(value)) intersection += 1;
  return intersection / (left.size + right.size - intersection);
}

function creatorsOverlap(a: string[], b: string[]): boolean {
  if (!a.length || !b.length) return false;
  const left = new Set(a);
  return b.some((creator) => left.has(creator));
}

function compare(a: Identity, b: Identity, titleThreshold: number): PairMatch | null {
  if (a.key === b.key || a.itemType !== b.itemType) return null;

  const strongReasons: string[] = [];
  if (a.doi && b.doi && a.doi === b.doi) strongReasons.push('same-doi');
  if (a.pmid && b.pmid && a.pmid === b.pmid) strongReasons.push('same-pmid');
  if (a.isbn && b.isbn && a.isbn === b.isbn) strongReasons.push('same-isbn');
  if (strongReasons.length) {
    return { a: a.key, b: b.key, confidence: 'high', reasons: strongReasons, conflicts: [] };
  }

  if ((a.doi && b.doi && a.doi !== b.doi) || (a.pmid && b.pmid && a.pmid !== b.pmid)) return null;
  if (a.isCorrection !== b.isCorrection) return null;

  const similarity = jaccard(a.titleTokens, b.titleTokens);
  if (similarity < titleThreshold) return null;

  const conflicts: string[] = [];
  const hasYears = a.year !== undefined && b.year !== undefined;
  const yearMatches = hasYears && Math.abs(a.year! - b.year!) <= 1;
  if (hasYears && !yearMatches) conflicts.push('publication-year');
  const hasCreators = a.creators.length > 0 && b.creators.length > 0;
  const authorMatches = hasCreators && creatorsOverlap(a.creators, b.creators);
  if (hasCreators && !authorMatches) conflicts.push('creators');
  if (conflicts.length) return null;

  if (similarity >= 0.9 && authorMatches && yearMatches) {
    return {
      a: a.key,
      b: b.key,
      confidence: 'medium',
      reasons: ['title-author-year'],
      conflicts: [],
    };
  }
  return {
    a: a.key,
    b: b.key,
    confidence: 'review',
    reasons: ['similar-title-incomplete-metadata'],
    conflicts: [],
  };
}

function candidatePairs(batch: Identity[], library: Identity[]): Array<[Identity, Identity]> {
  const indexes = {
    doi: new Map<string, Identity[]>(),
    pmid: new Map<string, Identity[]>(),
    isbn: new Map<string, Identity[]>(),
    title: new Map<string, Identity[]>(),
  };
  const add = (map: Map<string, Identity[]>, key: string, value: Identity) => {
    if (!key) return;
    const values = map.get(key) ?? [];
    values.push(value);
    map.set(key, values);
  };
  for (const item of library) {
    add(indexes.doi, item.doi, item);
    add(indexes.pmid, item.pmid, item);
    add(indexes.isbn, item.isbn, item);
    add(indexes.title, item.titleBlock, item);
  }

  const pairs = new Map<string, [Identity, Identity]>();
  for (const item of batch) {
    const candidates = [
      ...(indexes.doi.get(item.doi) ?? []),
      ...(indexes.pmid.get(item.pmid) ?? []),
      ...(indexes.isbn.get(item.isbn) ?? []),
      ...(indexes.title.get(item.titleBlock) ?? []),
    ];
    for (const candidate of candidates) {
      if (candidate.key === item.key) continue;
      const pairKey = [item.key, candidate.key].sort().join('|');
      pairs.set(pairKey, [item, candidate]);
    }
  }
  return [...pairs.values()];
}

function itemProjection(item: any): Record<string, unknown> {
  const data = dataOf(item);
  return {
    key: item.key ?? data.key,
    version: item.version ?? data.version,
    itemType: data.itemType,
    title: data.title,
    date: data.date,
    creators: data.creators,
    DOI: data.DOI,
    PMID: data.PMID ?? (extractPmid(data) || undefined),
    ISBN: data.ISBN,
    tags: data.tags,
    collections: data.collections,
    numChildren: item.meta?.numChildren,
  };
}

function masterScore(item: any): number {
  const data = dataOf(item);
  const fields = [
    'title',
    'creators',
    'date',
    'abstractNote',
    'publicationTitle',
    'volume',
    'issue',
    'pages',
    'DOI',
    'ISBN',
    'url',
  ];
  const completeness = fields.reduce(
    (score, field) => score + (data[field]?.length || data[field] ? 1 : 0),
    0,
  );
  return (
    completeness * 10 +
    (data.collections?.length ?? 0) * 3 +
    (data.tags?.length ?? 0) * 2 +
    (item.meta?.numChildren ?? 0) * 4
  );
}

function recommendMaster(items: any[]): { key: string; reason: string } {
  const ranked = [...items].sort((a, b) => {
    const score = masterScore(b) - masterScore(a);
    if (score) return score;
    return String(a.key ?? dataOf(a).key).localeCompare(String(b.key ?? dataOf(b).key));
  });
  return {
    key: String(ranked[0].key ?? dataOf(ranked[0]).key),
    reason: 'Highest deterministic metadata, child-item, collection, and tag completeness score.',
  };
}

export function findDuplicateClusters(
  batchItems: any[],
  libraryItems: any[],
  options: { titleThreshold?: number } = {},
): DuplicateCluster[] {
  const batch = batchItems.map(identity).filter((value): value is Identity => Boolean(value));
  const libraryMap = new Map<string, Identity>();
  for (const value of [...libraryItems, ...batchItems].map(identity))
    if (value) libraryMap.set(value.key, value);
  const library = [...libraryMap.values()];
  const matches = candidatePairs(batch, library)
    .map(([a, b]) => compare(a, b, options.titleThreshold ?? 0.85))
    .filter((value): value is PairMatch => Boolean(value));

  const parent = new Map<string, string>();
  const find = (key: string): string => {
    const current = parent.get(key) ?? key;
    if (current === key) return key;
    const root = find(current);
    parent.set(key, root);
    return root;
  };
  const union = (a: string, b: string) => {
    const left = find(a);
    const right = find(b);
    if (left !== right) parent.set(right, left);
  };
  for (const match of matches) union(match.a, match.b);

  const batchKeys = new Set(batch.map((value) => value.key));
  const groups = new Map<string, Set<string>>();
  for (const match of matches) {
    const root = find(match.a);
    const keys = groups.get(root) ?? new Set<string>();
    keys.add(match.a);
    keys.add(match.b);
    groups.set(root, keys);
  }

  return [...groups.values()]
    .map((keys, index) => {
      const identities = [...keys].map((key) => libraryMap.get(key)!).filter(Boolean);
      const items = identities.map((value) => value.item);
      const relatedMatches = matches.filter((match) => keys.has(match.a) && keys.has(match.b));
      const confidence = relatedMatches.reduce<DuplicateConfidence>(
        (best, match) =>
          CONFIDENCE_RANK[match.confidence] > CONFIDENCE_RANK[best] ? match.confidence : best,
        'review',
      );
      const master = recommendMaster(items);
      return {
        cluster_id: `duplicate-${String(index + 1).padStart(4, '0')}`,
        batch_item_keys: [...keys].filter((key) => batchKeys.has(key)).sort(),
        items: items.map(itemProjection),
        confidence,
        reasons: [...new Set(relatedMatches.flatMap((match) => match.reasons))].sort(),
        field_conflicts: [...new Set(relatedMatches.flatMap((match) => match.conflicts))].sort(),
        recommended_master_key: master.key,
        master_reason: master.reason,
        native_merge_required: true as const,
      };
    })
    .sort((a, b) => a.cluster_id.localeCompare(b.cluster_id));
}
