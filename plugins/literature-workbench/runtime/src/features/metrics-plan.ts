import { createHash } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import type { LibraryRef } from '../api/web-client.js';
import type { ToolContext } from '../registry/registry.js';

const PREFIX = 'AI4S-Metrics:';
const YEAR = /^(?:19|20)\d{2}$/;
const SHA256 = /^[0-9a-f]{64}$/;

export interface MetricsPlanAction {
  item_key: string;
  expected_version: number | null;
  title: string;
  issns: string[];
  decision: 'update' | 'skip';
  reason_codes: string[];
  metric: Record<string, unknown> | null;
}

export interface MetricsPlan {
  schema_version: '1.0';
  plan_type: 'zotero-metrics';
  created_at: string;
  plan_hash: string;
  target: { library_type: 'user' | 'group'; library_id: number };
  metrics: { metrics_year: number; remove_years?: number[]; source_label: string; source_sha256: string };
  actions: MetricsPlanAction[];
  summary: { selected: number; update: number; skip: number };
}

type ResultOutcome = 'updated' | 'unchanged' | 'skipped' | 'failed' | 'pending';
interface MetricsReceipt {
  schema_version: '1.0'; receipt_type: 'zotero-metrics'; plan_hash: string;
  started_at: string; updated_at: string; status: 'complete' | 'partial' | 'blocked';
  results: Array<{ item_key: string; outcome: ResultOutcome; zotero_version: number | null; error: string | null }>;
  summary: Record<ResultOutcome, number>;
}

function isObject(value: unknown): value is Record<string, any> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}
function deepSort(value: any): any {
  if (Array.isArray(value)) return value.map(deepSort);
  if (!isObject(value)) return value;
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, deepSort(value[key])]));
}
export function canonicalMetricsPlanHash(plan: MetricsPlan): string {
  const payload = { schema_version: plan.schema_version, plan_type: plan.plan_type, target: plan.target, metrics: plan.metrics,
    actions: [...plan.actions].sort((a, b) => a.item_key.localeCompare(b.item_key)) };
  return `sha256:${createHash('sha256').update(JSON.stringify(deepSort(payload)), 'utf8').digest('hex')}`;
}
export function validateMetricsPlan(value: unknown): MetricsPlan {
  if (!isObject(value) || value.schema_version !== '1.0' || value.plan_type !== 'zotero-metrics') throw new Error('Unsupported metrics plan schema or type');
  if (!/^sha256:[0-9a-f]{64}$/.test(String(value.plan_hash ?? ''))) throw new Error('Invalid metrics plan hash');
  if (!isObject(value.target) || !['user', 'group'].includes(value.target.library_type) || !Number.isInteger(value.target.library_id)) throw new Error('Invalid metrics plan target');
  if (!isObject(value.metrics) || !YEAR.test(String(value.metrics.metrics_year)) || typeof value.metrics.source_label !== 'string' || !value.metrics.source_label.trim() || !SHA256.test(String(value.metrics.source_sha256))) throw new Error('Invalid metrics provenance');
  if (value.metrics.remove_years !== undefined && (!Array.isArray(value.metrics.remove_years) || value.metrics.remove_years.some((year: unknown) => !Number.isInteger(year) || !YEAR.test(String(year)) || year === value.metrics.metrics_year) || new Set(value.metrics.remove_years).size !== value.metrics.remove_years.length)) throw new Error('Invalid metrics remove_years');
  if (!Array.isArray(value.actions) || !isObject(value.summary)) throw new Error('Metrics plan needs actions and summary');
  const seen = new Set<string>();
  for (const action of value.actions) {
    if (!isObject(action) || typeof action.item_key !== 'string' || !action.item_key || seen.has(action.item_key)) throw new Error('Metrics plan has invalid or duplicate item_key');
    seen.add(action.item_key);
    if (!['update', 'skip'].includes(action.decision) || !Array.isArray(action.reason_codes) || !Array.isArray(action.issns)) throw new Error(`Invalid metrics action ${action.item_key}`);
    if (action.decision === 'update') {
      if (!Number.isInteger(action.expected_version) || !isObject(action.metric)) throw new Error(`Update action ${action.item_key} requires version and metric`);
      const metric = action.metric;
      const hasIf = Object.prototype.hasOwnProperty.call(metric, 'impact_factor');
      const hasIf5 = Object.prototype.hasOwnProperty.call(metric, 'impact_factor_5y');
      const hasJcr = Object.prototype.hasOwnProperty.call(metric, 'jcr_zone');
      const hasCas = Object.prototype.hasOwnProperty.call(metric, 'cas_zone');
      const hasPublicationMetrics = Object.prototype.hasOwnProperty.call(metric, 'publication_metrics');
      if (!hasIf && !hasIf5 && !hasJcr && !hasCas && !hasPublicationMetrics) throw new Error(`Metric for ${action.item_key} needs IF, zone, or publication metrics`);
      for (const [key, label] of [['impact_factor', 'IF'], ['impact_factor_5y', '5-year IF']] as const) {
        if (!Object.prototype.hasOwnProperty.call(metric, key)) continue;
        const number = Number(metric[key]);
        if (!Number.isFinite(number) || number < 0) throw new Error(`Invalid ${label} for ${action.item_key}`);
      }
      for (const key of ['jcr_zone', 'cas_zone']) {
        if (Object.prototype.hasOwnProperty.call(metric, key) && (typeof metric[key] !== 'string' || !metric[key].trim())) {
          throw new Error(`Invalid ${key} for ${action.item_key}`);
        }
      }
      if (hasPublicationMetrics) {
        if (!Array.isArray(metric.publication_metrics) || !metric.publication_metrics.length) throw new Error(`Invalid publication metrics for ${action.item_key}`);
        const allowed = new Set(['cas_major', 'cas_top', 'esi_category', 'indexing']);
        const identities = new Set<string>();
        for (const entry of metric.publication_metrics) {
          if (!isObject(entry) || !allowed.has(entry.code)) throw new Error(`Invalid publication metrics for ${action.item_key}`);
          if (entry.code === 'cas_top' ? entry.value !== true : typeof entry.value !== 'string' || !entry.value.trim()) throw new Error(`Invalid publication metrics for ${action.item_key}`);
          const identity = `${entry.code}:${String(entry.value)}`;
          if (identities.has(identity)) throw new Error(`Duplicate publication metrics for ${action.item_key}`);
          identities.add(identity);
        }
      }
      if (Object.prototype.hasOwnProperty.call(metric, 'retrieved_at') && (typeof metric.retrieved_at !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(metric.retrieved_at))) throw new Error(`Invalid retrieved_at for ${action.item_key}`);
    }
  }
  const expected = { selected: value.actions.length, update: value.actions.filter((a: any) => a.decision === 'update').length, skip: value.actions.filter((a: any) => a.decision === 'skip').length };
  if (Object.entries(expected).some(([key, count]) => value.summary[key] !== count)) throw new Error('Metrics plan summary does not match actions');
  const plan = value as MetricsPlan;
  if (canonicalMetricsPlanHash(plan) !== plan.plan_hash) throw new Error('Metrics plan hash mismatch');
  return plan;
}
export async function readMetricsPlan(path: string): Promise<MetricsPlan> { return validateMetricsPlan(JSON.parse(await readFile(path, 'utf8'))); }

function parseExtra(extra: unknown): Record<string, any> | null {
  const lines = String(extra ?? '').split(/\r?\n/); const matches = lines.filter((line) => line.startsWith(PREFIX));
  if (!matches.length) return { schema_version: 2, by_year: {} };
  if (matches.length !== 1) return null;
  try { const payload = JSON.parse(matches[0]!.slice(PREFIX.length).trim()); return isObject(payload) && payload.schema_version === 2 && isObject(payload.by_year) ? payload : null; } catch { return null; }
}
function mergeMetric(extra: unknown, year: number, metric: Record<string, unknown>): string | null {
  const payload = parseExtra(extra); if (!payload) return null;
  const entry: Record<string, unknown> = {};
  if (Object.prototype.hasOwnProperty.call(metric, 'impact_factor')) entry.impact_factor = Number(metric.impact_factor);
  if (Object.prototype.hasOwnProperty.call(metric, 'impact_factor_5y')) entry.impact_factor_5y = Number(metric.impact_factor_5y);
  for (const key of ['jcr_zone', 'cas_zone', 'retrieved_at', 'source_label', 'source_sha256']) if (typeof metric[key] === 'string' && metric[key]) entry[key] = metric[key];
  if (Array.isArray(metric.publication_metrics)) entry.publication_metrics = metric.publication_metrics.map((value) => deepSort(value));
  payload.by_year[String(year)] = entry;
  const line = `${PREFIX} ${JSON.stringify(deepSort(payload))}`;
  const retained = String(extra ?? '').split(/\r?\n/).filter((part) => !part.startsWith(PREFIX));
  return [...retained, line].filter(Boolean).join('\n');
}
function mergedTags(tags: any[], extra: string): Array<{ tag: string; type?: number }> {
  const payload = parseExtra(extra)!; const years = Object.keys(payload.by_year).filter((year) => YEAR.test(year)).sort();
  const latest = years.length ? payload.by_year[years.at(-1)!] : {};
  const kept = new Map<string, { tag: string; type?: number }>();
  for (const raw of tags ?? []) { const tag = typeof raw === 'string' ? raw : raw?.tag; if (tag && !/^JCR:|^CAS:/.test(tag)) kept.set(tag, typeof raw === 'string' ? { tag } : raw); }
  if (typeof latest.jcr_zone === 'string' && latest.jcr_zone) kept.set(`JCR:${latest.jcr_zone}`, { tag: `JCR:${latest.jcr_zone}` });
  if (typeof latest.cas_zone === 'string' && latest.cas_zone) kept.set(`CAS:${latest.cas_zone}`, { tag: `CAS:${latest.cas_zone}` });
  return [...kept.values()];
}
function versionOf(item: any): number | null { const value = item?.version ?? item?.data?.version; return Number.isInteger(value) ? value : null; }
function dataOf(item: any): Record<string, any> { return isObject(item?.data) ? item.data : item ?? {}; }
function summarize(receipt: MetricsReceipt): void { for (const key of ['updated','unchanged','skipped','failed','pending'] as const) receipt.summary[key] = receipt.results.filter((r) => r.outcome === key).length; receipt.updated_at = new Date().toISOString(); receipt.status = receipt.summary.pending ? 'blocked' : receipt.summary.failed ? 'partial' : 'complete'; }
async function save(path: string, receipt: MetricsReceipt): Promise<void> { summarize(receipt); await mkdir(dirname(path), { recursive: true }); const tmp = `${path}.tmp-${process.pid}`; await writeFile(tmp, `${JSON.stringify(receipt, null, 2)}\n`); await rename(tmp, path); }
function initial(plan: MetricsPlan): MetricsReceipt { const now = new Date().toISOString(); const receipt: MetricsReceipt = { schema_version:'1.0', receipt_type:'zotero-metrics', plan_hash:plan.plan_hash, started_at:now, updated_at:now, status:'partial', results: plan.actions.map((action) => ({ item_key:action.item_key, outcome:action.decision === 'skip' ? 'skipped' : 'pending', zotero_version:action.expected_version, error:action.decision === 'skip' ? action.reason_codes.join(';') : null })), summary:{updated:0,unchanged:0,skipped:0,failed:0,pending:0} }; summarize(receipt); return receipt; }
export async function executeMetricsPlan(ctx: ToolContext, plan: MetricsPlan, lib: LibraryRef, mode: 'dry_run' | 'apply', receiptPath?: string): Promise<{ status: string; summary: Record<string, number>; receiptPath?: string; conflicts: string[] }> {
  let receipt = initial(plan); if (mode === 'apply' && receiptPath) { try { const old = JSON.parse(await readFile(receiptPath, 'utf8')) as MetricsReceipt; if (old.plan_hash !== plan.plan_hash) throw new Error('Receipt plan hash does not match'); receipt = old; if (old.status === 'complete') return { status:'complete', summary:old.summary, receiptPath, conflicts:[] }; } catch (error: any) { if (error?.code !== 'ENOENT') throw error; } }
  const conflicts: string[] = [];
  for (const action of plan.actions.filter((entry) => entry.decision === 'update')) {
    const result = receipt.results.find((entry) => entry.item_key === action.item_key)!; if (result.outcome !== 'pending') continue;
    try {
      const item = await ctx.web.getItem(lib, action.item_key); const data = dataOf(item); const current = versionOf(item);
      if (current === null || action.expected_version === null || current !== action.expected_version) { conflicts.push(action.item_key); result.outcome = 'failed'; result.error = 'version-conflict'; continue; }
      let sourceExtra = data.extra;
      if (plan.metrics.remove_years?.length) {
        const payload = parseExtra(sourceExtra);
        if (payload === null) { result.outcome = 'failed'; result.error = 'invalid-or-duplicate-ai4s-metrics-block'; continue; }
        for (const year of plan.metrics.remove_years) delete payload.by_year[String(year)];
        const retained = String(sourceExtra ?? '').split(/\r?\n/).filter((part) => !part.startsWith(PREFIX));
        sourceExtra = [...retained, `${PREFIX} ${JSON.stringify(deepSort(payload))}`].filter(Boolean).join('\n');
      }
      const extra = mergeMetric(sourceExtra, plan.metrics.metrics_year, action.metric!);
      if (extra === null) { result.outcome = 'failed'; result.error = 'invalid-or-duplicate-ai4s-metrics-block'; continue; }
      const tags = mergedTags(data.tags, extra); const changed = extra !== String(data.extra ?? '') || JSON.stringify(tags) !== JSON.stringify(data.tags ?? []);
      if (mode === 'dry_run') { result.outcome = changed ? 'pending' : 'unchanged'; continue; }
      if (!changed) { result.outcome = 'unchanged'; continue; }
      result.zotero_version = await ctx.web.patchItem(lib, action.item_key, { extra, tags }, current); result.outcome = 'updated'; result.error = null;
    } catch (error) { result.outcome = 'failed'; result.error = (error instanceof Error ? error.message : String(error)).slice(0, 500); }
  }
  if (mode === 'dry_run') {
    summarize(receipt);
    return { status: conflicts.length ? 'blocked' : 'ready', summary: receipt.summary, conflicts };
  }
  if (!receiptPath) throw new Error('receipt path is required for apply'); await save(receiptPath, receipt); return { status: receipt.status, summary:receipt.summary, receiptPath, conflicts };
}
