import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';

export type PlanDecision = 'create' | 'reuse' | 'check' | 'skip';
export type ReceiptOutcome = 'created' | 'reused' | 'check' | 'skipped' | 'failed' | 'pending';

export interface ImportPlanAction {
  evidence_id: string;
  display_rank: number | null;
  decision: PlanDecision;
  reason_codes: string[];
  source: { database: string | null; record_id: string | null };
  item: Record<string, any> | null;
  match: Record<string, any> | null;
  priority_recommendation?: {
    level: 1 | 2 | 3;
    reason_codes: string[];
    tag_decision: 'add' | 'preserve-existing' | 'not-actionable';
    existing_tags?: string[];
  };
}

export interface ImportPlan {
  schema_version: '1.0';
  plan_type: 'zotero-import';
  created_at: string;
  plan_hash: string;
  project: { slug: string; search_date: string };
  target: {
    library_type: 'user' | 'group';
    library_id: number;
    collection_name: string;
    tags: string[];
  };
  matching: {
    mode: 'local-api' | 'snapshot' | 'unchecked';
    source_library_version: number | null;
    candidate_limit: number;
    unchecked_create: boolean;
  };
  priority?: {
    source_sha256: string;
    scope: string;
    review_depth: 'metadata' | 'abstract' | 'mixed' | 'full-text';
    default_for_selected: 1;
  };
  actions: ImportPlanAction[];
  summary: Record<PlanDecision | 'selected', number>;
}

export interface ReceiptError {
  code: string;
  message: string;
  retryable: boolean;
  http_status: number | null;
}

export interface ReceiptResult {
  evidence_id: string;
  planned_decision: PlanDecision;
  outcome: ReceiptOutcome;
  zotero_key: string | null;
  zotero_version: number | null;
  error: ReceiptError | null;
}

export interface ImportReceipt {
  schema_version: '1.0';
  receipt_type: 'zotero-import';
  plan_hash: string;
  started_at: string;
  updated_at: string;
  status: 'partial' | 'complete' | 'blocked';
  target: {
    library_type: 'user' | 'group';
    library_id: number;
    collection_name: string;
    collection_key: string | null;
    import_run_tag: string;
  };
  source_library_version: number | null;
  resulting_library_version: number | null;
  results: ReceiptResult[];
  summary: Record<'created' | 'reused' | 'check' | 'skipped' | 'failed' | 'pending', number>;
}

function isObject(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function exactKeys(value: Record<string, any>, allowed: string[], label: string): void {
  const extras = Object.keys(value).filter((key) => !allowed.includes(key));
  if (extras.length) throw new Error(`${label} contains unsupported field(s): ${extras.join(', ')}`);
}

function requireString(value: unknown, label: string): asserts value is string {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${label} must be a non-empty string`);
}

function sortedUnique(values: unknown, label: string): string[] {
  if (!Array.isArray(values) || values.some((value) => typeof value !== 'string' || !value)) {
    throw new Error(`${label} must be an array of non-empty strings`);
  }
  return [...new Set(values)].sort();
}

function normalizeActionForHash(action: ImportPlanAction): Record<string, any> {
  const item = action.item ? structuredClone(action.item) : null;
  if (item && Array.isArray(item.tags)) {
    item.tags = [...item.tags].sort((a: any, b: any) => String(a?.tag ?? '').localeCompare(String(b?.tag ?? '')));
  }
  return {
    ...action,
    reason_codes: [...new Set(action.reason_codes)].sort(),
    item,
  };
}

function deepSort(value: any): any {
  if (Array.isArray(value)) return value.map(deepSort);
  if (!isObject(value)) return value;
  const out: Record<string, any> = {};
  for (const key of Object.keys(value).sort()) out[key] = deepSort(value[key]);
  return out;
}

export function canonicalPlanHash(plan: ImportPlan): string {
  const payload = {
    schema_version: plan.schema_version,
    plan_type: plan.plan_type,
    project: plan.project,
    target: { ...plan.target, tags: [...new Set(plan.target.tags)].sort() },
    matching: {
      mode: plan.matching.mode,
      unchecked_create: plan.matching.unchecked_create,
    },
    actions: [...plan.actions]
      .sort((a, b) => a.evidence_id.localeCompare(b.evidence_id))
      .map(normalizeActionForHash),
    ...(plan.priority ? { priority: plan.priority } : {}),
  };
  const canonical = JSON.stringify(deepSort(payload));
  return `sha256:${createHash('sha256').update(canonical, 'utf8').digest('hex')}`;
}

export function validateImportPlan(value: unknown): ImportPlan {
  if (!isObject(value)) throw new Error('Import plan must be a JSON object');
  exactKeys(
    value,
    ['schema_version', 'plan_type', 'created_at', 'plan_hash', 'project', 'target', 'matching', 'priority', 'actions', 'summary'],
    'Import plan',
  );
  if (value.schema_version !== '1.0' || value.plan_type !== 'zotero-import') {
    throw new Error('Unsupported import-plan schema or plan type');
  }
  requireString(value.created_at, 'created_at');
  if (!/^sha256:[0-9a-f]{64}$/.test(String(value.plan_hash ?? ''))) throw new Error('Invalid plan_hash');
  if (!isObject(value.project)) throw new Error('project must be an object');
  exactKeys(value.project, ['slug', 'search_date'], 'project');
  requireString(value.project.slug, 'project.slug');
  requireString(value.project.search_date, 'project.search_date');
  if (!isObject(value.target)) throw new Error('target must be an object');
  exactKeys(value.target, ['library_type', 'library_id', 'collection_name', 'tags'], 'target');
  if (!['user', 'group'].includes(value.target.library_type)) throw new Error('Invalid target.library_type');
  if (!Number.isInteger(value.target.library_id) || value.target.library_id < 0) throw new Error('Invalid target.library_id');
  requireString(value.target.collection_name, 'target.collection_name');
  value.target.tags = sortedUnique(value.target.tags, 'target.tags');
  if (!isObject(value.matching)) throw new Error('matching must be an object');
  exactKeys(value.matching, ['mode', 'source_library_version', 'candidate_limit', 'unchecked_create'], 'matching');
  if (!['local-api', 'snapshot', 'unchecked'].includes(value.matching.mode)) throw new Error('Invalid matching.mode');
  if (!Number.isInteger(value.matching.candidate_limit) || value.matching.candidate_limit < 1) {
    throw new Error('matching.candidate_limit must be a positive integer');
  }
  if (typeof value.matching.unchecked_create !== 'boolean') throw new Error('matching.unchecked_create must be boolean');
  if (value.priority !== undefined) {
    if (!isObject(value.priority)) throw new Error('priority must be an object');
    exactKeys(value.priority, ['source_sha256', 'scope', 'review_depth', 'default_for_selected'], 'priority');
    if (!/^[0-9a-f]{64}$/.test(String(value.priority.source_sha256 ?? ''))) throw new Error('priority.source_sha256 must be sha256 hex');
    requireString(value.priority.scope, 'priority.scope');
    if (!['metadata', 'abstract', 'mixed', 'full-text'].includes(value.priority.review_depth)) throw new Error('Invalid priority.review_depth');
    if (value.priority.default_for_selected !== 1) throw new Error('priority.default_for_selected must be 1');
  }
  if (!Array.isArray(value.actions)) throw new Error('actions must be an array');
  const seen = new Set<string>();
  for (const [index, action] of value.actions.entries()) {
    if (!isObject(action)) throw new Error(`actions[${index}] must be an object`);
    exactKeys(action, ['evidence_id', 'display_rank', 'decision', 'reason_codes', 'source', 'item', 'match', 'priority_recommendation'], `actions[${index}]`);
    requireString(action.evidence_id, `actions[${index}].evidence_id`);
    if (seen.has(action.evidence_id)) throw new Error(`Duplicate evidence_id: ${action.evidence_id}`);
    seen.add(action.evidence_id);
    if (!['create', 'reuse', 'check', 'skip'].includes(action.decision)) throw new Error(`Invalid decision for ${action.evidence_id}`);
    action.reason_codes = sortedUnique(action.reason_codes, `${action.evidence_id}.reason_codes`);
    if (!isObject(action.source)) throw new Error(`${action.evidence_id}.source must be an object`);
    exactKeys(action.source, ['database', 'record_id'], `${action.evidence_id}.source`);
    if (action.display_rank !== null && (!Number.isInteger(action.display_rank) || action.display_rank < 1)) {
      throw new Error(`${action.evidence_id}.display_rank must be null or a positive integer`);
    }
    if (action.priority_recommendation !== undefined) {
      const priority = action.priority_recommendation;
      if (!isObject(priority)) throw new Error(`${action.evidence_id}.priority_recommendation must be an object`);
      exactKeys(priority, ['level', 'reason_codes', 'tag_decision', 'existing_tags'], `${action.evidence_id}.priority_recommendation`);
      if (![1, 2, 3].includes(priority.level)) throw new Error(`${action.evidence_id}.priority level must be 1-3`);
      priority.reason_codes = sortedUnique(priority.reason_codes, `${action.evidence_id}.priority reason_codes`);
      if (!['add', 'preserve-existing', 'not-actionable'].includes(priority.tag_decision)) throw new Error(`${action.evidence_id}.priority tag_decision is invalid`);
      if (priority.existing_tags !== undefined) priority.existing_tags = sortedUnique(priority.existing_tags, `${action.evidence_id}.priority existing_tags`);
    }
    if (action.decision === 'create') {
      if (!isObject(action.item)) throw new Error(`${action.evidence_id} create action needs item`);
      if (!['journalArticle', 'preprint'].includes(action.item.itemType)) {
        throw new Error(`${action.evidence_id} create action has unsupported itemType`);
      }
      for (const forbidden of ['key', 'version', 'deleted', 'parentItem', 'collections']) {
        if (forbidden in action.item) {
          throw new Error(`${action.evidence_id} create action must not contain ${forbidden}`);
        }
      }
    }
    if (action.decision === 'reuse') {
      if (!isObject(action.match)) throw new Error(`${action.evidence_id} reuse action needs match`);
      requireString(action.match.zotero_key, `${action.evidence_id}.match.zotero_key`);
      if (!Number.isInteger(action.match.zotero_version)) throw new Error(`${action.evidence_id} reuse action needs zotero_version`);
    }
  }
  if (!isObject(value.summary)) throw new Error('summary must be an object');
  exactKeys(value.summary, ['selected', 'create', 'reuse', 'check', 'skip'], 'summary');
  const expectedSummary = {
    selected: value.actions.length,
    create: value.actions.filter((action: ImportPlanAction) => action.decision === 'create').length,
    reuse: value.actions.filter((action: ImportPlanAction) => action.decision === 'reuse').length,
    check: value.actions.filter((action: ImportPlanAction) => action.decision === 'check').length,
    skip: value.actions.filter((action: ImportPlanAction) => action.decision === 'skip').length,
  };
  for (const [key, expected] of Object.entries(expectedSummary)) {
    if (value.summary[key] !== expected) throw new Error(`summary.${key} does not match actions`);
  }
  const plan = value as ImportPlan;
  const computed = canonicalPlanHash(plan);
  if (computed !== plan.plan_hash) throw new Error(`Plan hash mismatch: expected ${computed}, found ${plan.plan_hash}`);
  return plan;
}

export async function readImportPlan(path: string): Promise<ImportPlan> {
  const raw = JSON.parse(await readFile(path, 'utf8'));
  return validateImportPlan(raw);
}

export function summarizeReceipt(receipt: ImportReceipt): void {
  const keys = ['created', 'reused', 'check', 'skipped', 'failed', 'pending'] as const;
  for (const key of keys) receipt.summary[key] = receipt.results.filter((result) => result.outcome === key).length;
  receipt.updated_at = new Date().toISOString();
  if (receipt.summary.pending > 0) receipt.status = 'blocked';
  else if (receipt.summary.failed > 0) receipt.status = 'partial';
  else receipt.status = 'complete';
}

export function validateImportReceipt(value: unknown): ImportReceipt {
  if (!isObject(value) || value.schema_version !== '1.0' || value.receipt_type !== 'zotero-import') {
    throw new Error('Unsupported receipt schema or type');
  }
  if (!/^sha256:[0-9a-f]{64}$/.test(String(value.plan_hash ?? ''))) throw new Error('Invalid receipt plan_hash');
  if (!['partial', 'complete', 'blocked'].includes(value.status)) throw new Error('Invalid receipt status');
  if (!isObject(value.target) || !isObject(value.summary)) throw new Error('Receipt target/summary must be objects');
  if (!Array.isArray(value.results)) throw new Error('Receipt results must be an array');
  const seen = new Set<string>();
  for (const result of value.results) {
    if (!isObject(result)) throw new Error('Receipt result must be an object');
    requireString(result.evidence_id, 'receipt result evidence_id');
    if (seen.has(result.evidence_id)) throw new Error(`Duplicate receipt evidence_id: ${result.evidence_id}`);
    seen.add(result.evidence_id);
    if (!['create', 'reuse', 'check', 'skip'].includes(result.planned_decision)) throw new Error('Invalid receipt planned_decision');
    if (!['created', 'reused', 'check', 'skipped', 'failed', 'pending'].includes(result.outcome)) throw new Error('Invalid receipt outcome');
  }
  return value as ImportReceipt;
}
