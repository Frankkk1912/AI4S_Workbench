import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import type { ZoteroApiError } from '../../api/errors.js';
import type { LibraryRef } from '../../api/web-client.js';
import type { ToolContext } from '../../registry/registry.js';
import { hasManagedMetrics, mergePlannedMetricsExtra, synchronizeCurrentMetricTags } from '../evidence-metrics.js';
import {
  type ImportPlan,
  type ImportPlanAction,
  type ImportReceipt,
  type ReceiptError,
  type ReceiptResult,
  summarizeReceipt,
  validateImportReceipt,
} from './contract.js';

interface Preflight {
  collectionMatches: any[];
  itemChecks: Map<string, string>;
  reuseItems: Map<string, any>;
  blockingIssues: string[];
}

export interface ExecutionSummary {
  mode: 'dry_run' | 'apply';
  planHash: string;
  noOp: boolean;
  collectionKey: string | null;
  receiptPath?: string;
  status: 'ready' | 'partial' | 'complete' | 'blocked';
  summary: Record<string, number>;
  blockingIssues: string[];
}

function dataOf(item: any): Record<string, any> {
  return item?.data && typeof item.data === 'object' ? item.data : item ?? {};
}

function keyOf(item: any): string {
  return String(item?.key ?? item?.data?.key ?? '');
}

function versionOf(item: any): number | null {
  const value = item?.version ?? item?.data?.version;
  return Number.isInteger(value) ? value : null;
}

function cleanDoi(value: unknown): string {
  return String(value ?? '')
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\/(dx\.)?doi\.org\//, '')
    .replace(/^doi:\s*/, '')
    .replace(/[ .]+$/, '');
}

function cleanPmid(value: unknown): string {
  const match = String(value ?? '').match(/\d+/);
  return match?.[0] ?? '';
}

function normalizedTitle(value: unknown): string {
  return String(value ?? '')
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function itemIdentity(item: any): { doi: string; pmid: string; title: string; year: string } {
  const data = dataOf(item);
  return {
    doi: cleanDoi(data.DOI ?? data.doi),
    pmid: cleanPmid(data.PMID ?? data.pmid ?? data.extra),
    title: normalizedTitle(data.title),
    year: String(data.date ?? data.year ?? '').match(/(?:19|20)\d{2}/)?.[0] ?? '',
  };
}

async function allCollections(ctx: ToolContext, lib: LibraryRef): Promise<any[]> {
  const collections: any[] = [];
  let start = 0;
  let hasMore = true;
  while (hasMore) {
    const page = await ctx.web.listCollections(lib, { limit: 100, start });
    collections.push(...page.data);
    hasMore = page.data.length > 0 && collections.length < page.totalResults;
    if (hasMore) start += page.data.length;
  }
  return collections;
}

function queryForCreate(action: ImportPlanAction): string {
  const item = action.item ?? {};
  return cleanDoi(item.DOI) || cleanPmid(item.extra) || String(item.title ?? '');
}

function exactLiveMatch(action: ImportPlanAction, candidate: any): boolean {
  const planned = itemIdentity(action.item);
  const live = itemIdentity(candidate);
  if (planned.doi && planned.doi === live.doi) return true;
  if (planned.pmid && planned.pmid === live.pmid) return true;
  return Boolean(planned.title && planned.year && planned.title === live.title && planned.year === live.year);
}

async function preflight(
  ctx: ToolContext,
  plan: ImportPlan,
  lib: LibraryRef,
  actions: ImportPlanAction[],
): Promise<Preflight> {
  const collections = await allCollections(ctx, lib);
  const collectionMatches = collections.filter(
    (collection) => String(dataOf(collection).name ?? '') === plan.target.collection_name,
  );
  const itemChecks = new Map<string, string>();
  const reuseItems = new Map<string, any>();
  const blockingIssues: string[] = [];
  if (collectionMatches.length > 1) blockingIssues.push('multiple-exact-collection-matches');

  for (const action of actions) {
    if (action.decision === 'create') {
      const validation = await ctx.schema.validateItem(action.item ?? {});
      if (!validation.valid) {
        itemChecks.set(action.evidence_id, `invalid-item:${validation.errors.join('; ')}`);
        continue;
      }
      const query = queryForCreate(action);
      const result = await ctx.web.listItems(lib, {
        q: query,
        qmode: 'everything',
        top: true,
        includeTrashed: false,
        limit: plan.matching.candidate_limit,
      });
      if (result.totalResults > plan.matching.candidate_limit) {
        itemChecks.set(action.evidence_id, 'live-candidate-limit-exceeded');
      } else if (result.data.some((candidate) => exactLiveMatch(action, candidate))) {
        itemChecks.set(action.evidence_id, 'live-match-for-planned-create');
      }
    } else if (action.decision === 'reuse') {
      const key = String(action.match?.zotero_key ?? '');
      const expectedVersion = action.match?.zotero_version;
      const current = await ctx.web.getItem(lib, key);
      const currentVersion = versionOf(current);
      if (currentVersion !== expectedVersion) {
        blockingIssues.push(`stale-reuse-item:${action.evidence_id}`);
      } else {
        reuseItems.set(action.evidence_id, current);
      }
    }
  }
  return { collectionMatches, itemChecks, reuseItems, blockingIssues };
}

function now(): string {
  return new Date().toISOString();
}

function importRunTag(plan: ImportPlan): string {
  return plan.target.tags.find((tag) => tag.startsWith('import-run:')) ?? '';
}

function initialReceipt(plan: ImportPlan): ImportReceipt {
  const started = now();
  const results: ReceiptResult[] = plan.actions.map((action) => ({
    evidence_id: action.evidence_id,
    planned_decision: action.decision,
    outcome: action.decision === 'check' ? 'check' : action.decision === 'skip' ? 'skipped' : 'pending',
    zotero_key: action.decision === 'reuse' ? String(action.match?.zotero_key ?? '') || null : null,
    zotero_version: action.decision === 'reuse' ? (action.match?.zotero_version ?? null) : null,
    error: null,
  }));
  const receipt: ImportReceipt = {
    schema_version: '1.0',
    receipt_type: 'zotero-import',
    plan_hash: plan.plan_hash,
    started_at: started,
    updated_at: started,
    status: 'partial',
    target: {
      library_type: plan.target.library_type,
      library_id: plan.target.library_id,
      collection_name: plan.target.collection_name,
      collection_key: null,
      import_run_tag: importRunTag(plan),
    },
    source_library_version: plan.matching.source_library_version,
    resulting_library_version: plan.matching.source_library_version,
    results,
    summary: { created: 0, reused: 0, check: 0, skipped: 0, failed: 0, pending: 0 },
  };
  summarizeReceipt(receipt);
  return receipt;
}

async function readReceiptIfPresent(path: string): Promise<ImportReceipt | null> {
  try {
    return validateImportReceipt(JSON.parse(await readFile(path, 'utf8')));
  } catch (error: any) {
    if (error?.code === 'ENOENT') return null;
    throw error;
  }
}

async function persistReceipt(path: string, receipt: ImportReceipt): Promise<void> {
  summarizeReceipt(receipt);
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.tmp-${process.pid}-${Date.now()}`;
  await writeFile(temporary, `${JSON.stringify(receipt, null, 2)}\n`, 'utf8');
  await rename(temporary, path);
}

function resultFor(receipt: ImportReceipt, evidenceId: string): ReceiptResult {
  const result = receipt.results.find((entry) => entry.evidence_id === evidenceId);
  if (!result) throw new Error(`Receipt is missing evidence result ${evidenceId}`);
  return result;
}

function errorInfo(error: unknown, code = 'zotero-write-failed'): ReceiptError {
  const candidate = error as Partial<ZoteroApiError>;
  const status = typeof candidate.status === 'number' ? candidate.status : null;
  const retryable = status === 429 || status === 500 || status === 502 || status === 503 || status === 504 || status === null;
  return {
    code,
    message: (error instanceof Error ? error.message : String(error)).slice(0, 500),
    retryable,
    http_status: status,
  };
}

function setBlockingError(receipt: ImportReceipt, actions: ImportPlanAction[], error: ReceiptError): void {
  for (const action of actions) {
    const result = resultFor(receipt, action.evidence_id);
    if (result.outcome === 'pending') result.error = error;
  }
}

function compactSummary(receipt: ImportReceipt): Record<string, number> {
  summarizeReceipt(receipt);
  return { ...receipt.summary };
}

function mergeTags(existing: any[], additions: string[]): Array<{ tag: string; type?: number }> {
  const merged = new Map<string, { tag: string; type?: number }>();
  for (const entry of existing ?? []) {
    if (typeof entry === 'string' && entry) merged.set(entry, { tag: entry });
    else if (entry?.tag) merged.set(String(entry.tag), entry);
  }
  for (const tag of additions) if (!merged.has(tag)) merged.set(tag, { tag });
  return [...merged.values()];
}

function plannedItemTags(action: ImportPlanAction): string[] {
  const tags = action.item?.tags;
  if (!Array.isArray(tags)) return [];
  return tags
    .map((entry: any) => typeof entry === 'string' ? entry : entry?.tag)
    .filter((tag: unknown): tag is string => typeof tag === 'string' && Boolean(tag));
}

function isPriorityTag(tag: string): boolean {
  return /^AI4S:Priority:[1-3]$/.test(tag);
}

function chunks<T>(values: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let index = 0; index < values.length; index += size) out.push(values.slice(index, index + size));
  return out;
}

export async function dryRunImportPlan(
  ctx: ToolContext,
  plan: ImportPlan,
  lib: LibraryRef,
): Promise<ExecutionSummary> {
  const actionable = plan.actions.filter((action) => action.decision === 'create' || action.decision === 'reuse');
  const checked = await preflight(ctx, plan, lib, actionable);
  const adjusted = { ...plan.summary } as Record<string, number>;
  adjusted.create = (adjusted.create ?? 0) - [...checked.itemChecks.keys()].filter(
    (id) => plan.actions.find((action) => action.evidence_id === id)?.decision === 'create',
  ).length;
  adjusted.check = (adjusted.check ?? 0) + checked.itemChecks.size;
  return {
    mode: 'dry_run',
    planHash: plan.plan_hash,
    noOp: false,
    collectionKey: checked.collectionMatches.length === 1 ? keyOf(checked.collectionMatches[0]) : null,
    status: checked.blockingIssues.length ? 'blocked' : 'ready',
    summary: adjusted,
    blockingIssues: [...checked.blockingIssues, ...[...checked.itemChecks.entries()].map(([id, reason]) => `${id}:${reason}`)],
  };
}

export async function applyImportPlan(
  ctx: ToolContext,
  plan: ImportPlan,
  lib: LibraryRef,
  receiptPath: string,
): Promise<ExecutionSummary> {
  let receipt = await readReceiptIfPresent(receiptPath);
  if (receipt && receipt.plan_hash !== plan.plan_hash) throw new Error('Receipt plan hash does not match the approved plan; refusing to overwrite it');
  if (receipt && receipt.status === 'complete') {
    return {
      mode: 'apply',
      planHash: plan.plan_hash,
      noOp: true,
      collectionKey: receipt.target.collection_key,
      receiptPath,
      status: 'complete',
      summary: compactSummary(receipt),
      blockingIssues: [],
    };
  }
  receipt ??= initialReceipt(plan);
  const pendingIds = new Set(receipt.results.filter((result) => result.outcome === 'pending').map((result) => result.evidence_id));
  const pendingActions = plan.actions.filter(
    (action) => pendingIds.has(action.evidence_id) && (action.decision === 'create' || action.decision === 'reuse'),
  );
  if (!pendingActions.length) {
    await persistReceipt(receiptPath, receipt);
    return {
      mode: 'apply',
      planHash: plan.plan_hash,
      noOp: true,
      collectionKey: receipt.target.collection_key,
      receiptPath,
      status: receipt.status,
      summary: compactSummary(receipt),
      blockingIssues: [],
    };
  }

  const checked = await preflight(ctx, plan, lib, pendingActions);
  if (receipt.target.collection_key) {
    const stillExists = checked.collectionMatches.some((collection) => keyOf(collection) === receipt!.target.collection_key);
    if (!stillExists) checked.blockingIssues.push('receipt-collection-key-missing');
  }
  if (checked.blockingIssues.length) {
    const error: ReceiptError = {
      code: 'preflight-blocked',
      message: checked.blockingIssues.join('; '),
      retryable: false,
      http_status: null,
    };
    setBlockingError(receipt, pendingActions, error);
    await persistReceipt(receiptPath, receipt);
    return {
      mode: 'apply',
      planHash: plan.plan_hash,
      noOp: false,
      collectionKey: receipt.target.collection_key,
      receiptPath,
      status: 'blocked',
      summary: compactSummary(receipt),
      blockingIssues: checked.blockingIssues,
    };
  }

  for (const [evidenceId, reason] of checked.itemChecks) {
    const result = resultFor(receipt, evidenceId);
    result.outcome = 'check';
    result.error = null;
    result.zotero_key = null;
    result.zotero_version = null;
    const action = plan.actions.find((candidate) => candidate.evidence_id === evidenceId);
    if (action && !action.reason_codes.includes(reason)) action.reason_codes.push(reason);
  }
  const writable = pendingActions.filter((action) => resultFor(receipt!, action.evidence_id).outcome === 'pending');
  if (!writable.length) {
    await persistReceipt(receiptPath, receipt);
    return {
      mode: 'apply',
      planHash: plan.plan_hash,
      noOp: false,
      collectionKey: receipt.target.collection_key,
      receiptPath,
      status: receipt.status,
      summary: compactSummary(receipt),
      blockingIssues: [...checked.itemChecks.entries()].map(([id, reason]) => `${id}:${reason}`),
    };
  }

  let collectionKey = receipt.target.collection_key;
  if (!collectionKey && checked.collectionMatches.length === 1) collectionKey = keyOf(checked.collectionMatches[0]);
  if (!collectionKey) {
    try {
      const created = await ctx.web.writeCollections(lib, [
        { name: plan.target.collection_name, parentCollection: false },
      ]);
      if (created.failed.length || !created.successful[0]?.key) throw new Error(`Collection creation failed: ${JSON.stringify(created.failed)}`);
      collectionKey = created.successful[0].key;
      receipt.resulting_library_version = created.newLibraryVersion;
    } catch (error) {
      const info = errorInfo(error, 'collection-create-failed');
      setBlockingError(receipt, writable, info);
      await persistReceipt(receiptPath, receipt);
      return {
        mode: 'apply', planHash: plan.plan_hash, noOp: false, collectionKey: null, receiptPath,
        status: 'blocked', summary: compactSummary(receipt), blockingIssues: [info.code],
      };
    }
  }
  receipt.target.collection_key = collectionKey;
  await persistReceipt(receiptPath, receipt);

  const createActions = writable.filter((action) => action.decision === 'create');
  for (const batch of chunks(createActions, 50)) {
    const objects = batch.map((action) => ({
      ...action.item,
      collections: [...new Set([...(action.item?.collections ?? []), collectionKey])],
    }));
    try {
      const written = await ctx.web.writeItems(lib, objects);
      for (const success of written.successful) {
        const action = batch[success.index];
        if (!action) continue;
        const result = resultFor(receipt, action.evidence_id);
        result.outcome = 'created';
        result.zotero_key = success.key;
        result.zotero_version = success.version ?? null;
        result.error = null;
      }
      for (const failure of written.failed) {
        const action = batch[failure.index];
        if (!action) continue;
        const result = resultFor(receipt, action.evidence_id);
        const retryable = failure.code === 429 || failure.code >= 500;
        result.outcome = retryable ? 'pending' : 'failed';
        result.error = {
          code: 'item-create-failed',
          message: String(failure.message).slice(0, 500),
          retryable,
          http_status: failure.code,
        };
      }
      receipt.resulting_library_version = written.newLibraryVersion;
      await persistReceipt(receiptPath, receipt);
      if (written.failed.some((failure) => failure.code === 429 || failure.code >= 500)) {
        return {
          mode: 'apply', planHash: plan.plan_hash, noOp: false, collectionKey, receiptPath,
          status: 'blocked', summary: compactSummary(receipt), blockingIssues: ['retryable-item-create-failure'],
        };
      }
    } catch (error) {
      const info = errorInfo(error, 'item-create-request-failed');
      setBlockingError(receipt, batch, info);
      await persistReceipt(receiptPath, receipt);
      return {
        mode: 'apply', planHash: plan.plan_hash, noOp: false, collectionKey, receiptPath,
        status: 'blocked', summary: compactSummary(receipt), blockingIssues: [info.code],
      };
    }
  }

  const reuseActions = writable.filter((action) => action.decision === 'reuse');
  for (const action of reuseActions) {
    const current = checked.reuseItems.get(action.evidence_id);
    const currentData = dataOf(current);
    const currentVersion = versionOf(current);
    if (currentVersion === null) {
      const info: ReceiptError = { code: 'missing-item-version', message: 'Live Zotero item has no version', retryable: false, http_status: null };
      setBlockingError(receipt, [action], info);
      await persistReceipt(receiptPath, receipt);
      return {
        mode: 'apply', planHash: plan.plan_hash, noOp: false, collectionKey, receiptPath,
        status: 'blocked', summary: compactSummary(receipt), blockingIssues: [info.code],
      };
    }
    const collections = [...new Set([...(currentData.collections ?? []), collectionKey])];
    // Per-item tags (such as AI4S:ArticleType:Review) are part of the hashed
    // action intent. Reused records must receive them just like newly created
    // records, while all existing Zotero tags remain untouched.
    const currentPriority = (currentData.tags ?? [])
      .map((entry: any) => typeof entry === 'string' ? entry : entry?.tag)
      .filter((tag: unknown): tag is string => typeof tag === 'string' && isPriorityTag(tag));
    const actionTags = plannedItemTags(action).filter((tag) => !currentPriority.length || !isPriorityTag(tag));
    const plannedMetrics = hasManagedMetrics(action.item?.extra);
    const extra = plannedMetrics ? mergePlannedMetricsExtra(currentData.extra, action.item?.extra) : String(currentData.extra ?? '');
    if (extra === null) {
      const info: ReceiptError = { code: 'invalid-or-duplicate-ai4s-metrics-block', message: 'Existing or planned Extra contains an invalid managed metrics block', retryable: false, http_status: null };
      setBlockingError(receipt, [action], info);
      await persistReceipt(receiptPath, receipt);
      return {
        mode: 'apply', planHash: plan.plan_hash, noOp: false, collectionKey, receiptPath,
        status: 'blocked', summary: compactSummary(receipt), blockingIssues: [info.code],
      };
    }
    let tags = mergeTags(currentData.tags ?? [], [...plan.target.tags, ...actionTags]);
    if (plannedMetrics) tags = synchronizeCurrentMetricTags(tags, extra);
    try {
      const newVersion = await ctx.web.patchItem(
        lib,
        String(action.match?.zotero_key),
        { collections, tags, ...(plannedMetrics ? { extra } : {}) },
        currentVersion,
      );
      const result = resultFor(receipt, action.evidence_id);
      result.outcome = 'reused';
      result.zotero_key = String(action.match?.zotero_key);
      result.zotero_version = newVersion;
      result.error = null;
      receipt.resulting_library_version = newVersion;
      await persistReceipt(receiptPath, receipt);
    } catch (error) {
      const info = errorInfo(error, 'item-reuse-update-failed');
      const result = resultFor(receipt, action.evidence_id);
      if (info.retryable) {
        result.outcome = 'pending';
      } else if (info.http_status === 409 || info.http_status === 412) {
        result.outcome = 'pending';
      } else {
        result.outcome = 'failed';
      }
      result.error = info;
      await persistReceipt(receiptPath, receipt);
      if (result.outcome === 'pending') {
        return {
          mode: 'apply', planHash: plan.plan_hash, noOp: false, collectionKey, receiptPath,
          status: 'blocked', summary: compactSummary(receipt), blockingIssues: [info.code],
        };
      }
    }
  }

  await persistReceipt(receiptPath, receipt);
  return {
    mode: 'apply',
    planHash: plan.plan_hash,
    noOp: false,
    collectionKey,
    receiptPath,
    status: receipt.status,
    summary: compactSummary(receipt),
    blockingIssues: [],
  };
}
