const PREFIX = 'AI4S-Metrics:';
const YEAR = /^(?:19|20)\d{2}$/;

export interface EvidenceMetric {
  impact_factor?: number;
  impact_factor_5y?: number;
  jcr_zone?: string;
  cas_zone?: string;
  publication_metrics?: Array<{ code: string; value: string | true }>;
  retrieved_at?: string;
  source_label: string;
  source_sha256: string;
}

function isObject(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function deepSort(value: any): any {
  if (Array.isArray(value)) return value.map(deepSort);
  if (!isObject(value)) return value;
  const output: Record<string, any> = {};
  for (const key of Object.keys(value).sort()) output[key] = deepSort(value[key]);
  return output;
}

function normalizedKey(value: unknown): string {
  return String(value ?? '').normalize('NFKC').toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');
}

function numberValue(value: unknown): number | undefined {
  if (typeof value === 'boolean' || value === null || value === undefined) return undefined;
  const match = String(value).trim().match(/[-+]?\d+(?:\.\d+)?/);
  if (!match) return undefined;
  const parsed = Number(match[0]);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
}

function jcrZone(value: unknown): string | undefined {
  const match = String(value ?? '').toUpperCase().replace(/[\s_-]+/g, '').match(/^(?:JCR)?Q([1-4])(?:区)?$/);
  return match ? `Q${match[1]}` : undefined;
}

function casZone(value: unknown): string | undefined {
  const text = String(value ?? '').replace(/[\s_-]+/g, '');
  const direct = text.match(/^(?:CAS|中科院)?([1-4])区$/i);
  if (direct) return `${direct[1]}区`;
  const chinese: Record<string, string> = { 一区: '1区', 二区: '2区', 三区: '3区', 四区: '4区' };
  if (chinese[text]) return chinese[text];
  const major = text.match(/^.+?([1-4])区[。.]?$/);
  return major ? `${major[1]}区` : undefined;
}

function officialBuckets(easyscholar: Record<string, any>): Record<string, any>[] {
  const rank = easyscholar.official_rank;
  if (!isObject(rank)) return [];
  return ['all', 'select'].map((key) => rank[key]).filter(isObject);
}

function officialValue(buckets: Record<string, any>[], names: string[]): unknown {
  for (const bucket of buckets) {
    const values = new Map(Object.entries(bucket).map(([key, value]) => [normalizedKey(key), value]));
    for (const name of names) if (values.has(normalizedKey(name))) return values.get(normalizedKey(name));
  }
  return undefined;
}

function customZone(easyscholar: Record<string, any>, datasets: string[], normalizer: (value: unknown) => string | undefined): string | undefined {
  if (!Array.isArray(easyscholar.custom_rank)) return undefined;
  for (const dataset of datasets) {
    const expected = normalizedKey(dataset);
    for (const entry of easyscholar.custom_rank) {
      if (isObject(entry) && normalizedKey(entry.dataset) === expected) {
        const value = normalizer(entry.rank);
        if (value) return value;
      }
    }
  }
  return undefined;
}

function publicationMetrics(buckets: Record<string, any>[]): Array<{ code: string; value: string | true }> {
  const output: Array<{ code: string; value: string | true }> = [];
  const major = String(officialValue(buckets, ['sciUp']) ?? '').trim().replace(/[。.]$/, '');
  if (/^.+[1-4]区$/.test(major)) output.push({ code: 'cas_major', value: major });
  if (String(officialValue(buckets, ['sciUpTop']) ?? '').trim()) output.push({ code: 'cas_top', value: true });
  const esi = String(officialValue(buckets, ['esi']) ?? '').trim();
  if (esi) output.push({ code: 'esi_category', value: esi });
  if (String(officialValue(buckets, ['eii']) ?? '').trim().toUpperCase() === 'EI') output.push({ code: 'indexing', value: 'EI' });
  return output;
}

export function isPreprintEvidence(record: Record<string, any>): boolean {
  const source = String(record.source ?? '').toLocaleLowerCase();
  const itemType = String(record.itemType ?? record.item_type ?? '').toLocaleLowerCase();
  const rawTypes = record.article_types ?? record.publication_types ?? [];
  const types = Array.isArray(rawTypes) ? rawTypes : [rawTypes];
  const journal = String(record.journal ?? record.publicationTitle ?? '').toLocaleLowerCase();
  return source === 'arxiv' || itemType === 'preprint' || types.some((value) => String(value).toLocaleLowerCase().includes('preprint'))
    || ['biorxiv', 'medrxiv', 'research square', 'ssrn preprint'].some((server) => journal.includes(server));
}

export function displayMetricYear(searchDate: string): number {
  const match = searchDate.match(/^((?:19|20)\d{2})-(\d{2})-(\d{2})$/);
  if (!match) throw new Error('search_date must use YYYY-MM-DD');
  const year = Number(match[1]);
  const date = new Date(`${searchDate}T00:00:00Z`);
  if (Number.isNaN(date.valueOf()) || date.getUTCFullYear() !== year || date.getUTCMonth() + 1 !== Number(match[2]) || date.getUTCDate() !== Number(match[3])) {
    throw new Error('search_date is not a valid calendar date');
  }
  return year - 1;
}

export function metricFromEvidence(record: Record<string, any>, sourceSha256: string): EvidenceMetric | null {
  if (isPreprintEvidence(record)) return null;
  const easyscholar = isObject(record.easyscholar) ? record.easyscholar : {};
  if (!Object.keys(easyscholar).length) return null;
  const buckets = officialBuckets(easyscholar);
  const impact = numberValue(officialValue(buckets, ['sciif', 'if', 'impact_factor', 'impactFactor']));
  const impact5 = numberValue(officialValue(buckets, ['sciif5', 'if5', 'impact_factor_5y', 'impactFactor5']));
  let jcr = customZone(easyscholar, ['jcr', 'jcr分区', 'jcr期刊分区', 'jcrquartile'], jcrZone);
  jcr ??= jcrZone(officialValue(buckets, ['sci', 'ssci', 'scie', 'esci']));
  let cas = customZone(easyscholar, ['中科院分区', '中科院大类分区', '中科院sci期刊分区', '中科院', 'cas分区', 'cas'], casZone);
  cas ??= casZone(officialValue(buckets, ['sciUp', 'sciBase']));
  const descriptors = publicationMetrics(buckets);
  if (impact === undefined && impact5 === undefined && !jcr && !cas && !descriptors.length) return null;
  const metric: EvidenceMetric = { source_label: 'easyscholar-latest', source_sha256: sourceSha256 };
  if (impact !== undefined) metric.impact_factor = impact;
  if (impact5 !== undefined) metric.impact_factor_5y = impact5;
  if (jcr) metric.jcr_zone = jcr;
  if (cas) metric.cas_zone = cas;
  if (descriptors.length) metric.publication_metrics = descriptors;
  const retrieved = String(easyscholar.fetched_at ?? '').match(/^(\d{4}-\d{2}-\d{2})/);
  if (retrieved) metric.retrieved_at = retrieved[1];
  return metric;
}

function parseExtra(extra: unknown): { payload: Record<string, any>; retained: string[] } | null {
  const lines = String(extra ?? '').split(/\r?\n/);
  const managed = lines.filter((line) => line.startsWith(PREFIX));
  if (managed.length > 1) return null;
  let payload: Record<string, any> = { schema_version: 2, by_year: {} };
  if (managed.length === 1) {
    try {
      const parsed = JSON.parse(managed[0]!.slice(PREFIX.length).trim());
      if (!isObject(parsed) || parsed.schema_version !== 2 || !isObject(parsed.by_year)) return null;
      payload = parsed;
    } catch { return null; }
  }
  return { payload, retained: lines.filter((line) => !line.startsWith(PREFIX)) };
}

function encodeExtra(retained: string[], payload: Record<string, any>): string {
  return [...retained, `${PREFIX} ${JSON.stringify(deepSort(payload))}`].filter(Boolean).join('\n');
}

export function hasManagedMetrics(extra: unknown): boolean {
  return String(extra ?? '').split(/\r?\n/).some((line) => line.startsWith(PREFIX));
}

export function mergeMetricIntoExtra(extra: unknown, year: number, metric: EvidenceMetric): string | null {
  if (!YEAR.test(String(year))) return null;
  const parsed = parseExtra(extra);
  if (!parsed) return null;
  parsed.payload.by_year[String(year)] = metric;
  return encodeExtra(parsed.retained, parsed.payload);
}

export function mergePlannedMetricsExtra(currentExtra: unknown, plannedExtra: unknown): string | null {
  if (!hasManagedMetrics(plannedExtra)) return String(currentExtra ?? '');
  const current = parseExtra(currentExtra);
  const planned = parseExtra(plannedExtra);
  if (!current || !planned) return null;
  current.payload.by_year = { ...current.payload.by_year, ...planned.payload.by_year };
  return encodeExtra(current.retained, current.payload);
}

export function synchronizeCurrentMetricTags(tags: any[], extra: string): Array<{ tag: string; type?: number }> {
  const parsed = parseExtra(extra);
  if (!parsed) return tags ?? [];
  const years = Object.keys(parsed.payload.by_year).filter((year) => YEAR.test(year)).sort();
  const latest = years.length ? parsed.payload.by_year[years.at(-1)!] : {};
  const kept = new Map<string, { tag: string; type?: number }>();
  for (const raw of tags ?? []) {
    const tag = typeof raw === 'string' ? raw : raw?.tag;
    if (tag && !/^JCR:|^CAS:/.test(tag)) kept.set(tag, typeof raw === 'string' ? { tag } : raw);
  }
  if (typeof latest.jcr_zone === 'string' && latest.jcr_zone) kept.set(`JCR:${latest.jcr_zone}`, { tag: `JCR:${latest.jcr_zone}` });
  if (typeof latest.cas_zone === 'string' && latest.cas_zone) kept.set(`CAS:${latest.cas_zone}`, { tag: `CAS:${latest.cas_zone}` });
  return [...kept.values()];
}
