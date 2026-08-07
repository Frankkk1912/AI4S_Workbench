import { mkdir, rename, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import type { LibraryRef } from '../../api/web-client.js';
import { ZoteroApiError } from '../../api/errors.js';
import type { ToolContext } from '../../registry/registry.js';
import {
  aiSummaryPlanHash, encodeAiSummaryExtra, evidenceHash, normalizeEvidenceText, normalizeLanguage,
  parseAiSummaryExtra, validateSummaryText, type AiSummaryPayload, type SummaryMode,
} from './contract.js';

export interface AiSummaryRecommendation {
  item_key: string;
  expected_version: number;
  title_sha256: string;
  abstract_sha256: string;
  text: string;
  language: string;
}

type Outcome = 'created' | 'refreshed' | 'unchanged' | 'stale' | 'skipped' | 'conflicted' | 'failed';

function dataOf(item: any): any { return item?.data ?? item ?? {}; }
function versionOf(item: any): number | null {
  const value = item?.version ?? item?.data?.version;
  return Number.isInteger(value) ? value : null;
}
function regularItem(data: any): boolean {
  return !['attachment', 'note', 'annotation'].includes(String(data.itemType ?? ''));
}
function timestampName(): string { return new Date().toISOString().replace(/[:.]/g, '-'); }

async function persistJson(path: string, value: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.tmp-${process.pid}`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  await rename(temporary, path);
}

function summaryDirectory(dataDir: string, library: LibraryRef): string {
  return join(dataDir, 'ai-summaries', `${library.type}-${library.id}`);
}

function prepareAction(item: any, recommendation: AiSummaryRecommendation, mode: SummaryMode, now: string) {
  const data = dataOf(item);
  const currentVersion = versionOf(item);
  const title = normalizeEvidenceText(data.title);
  const abstract = normalizeEvidenceText(data.abstractNote);
  const currentTitleHash = evidenceHash(title);
  const currentAbstractHash = evidenceHash(abstract);
  const parsed = parseAiSummaryExtra(data.extra);
  const base = {
    item_key: recommendation.item_key, expected_version: recommendation.expected_version,
    live_version: currentVersion, title_sha256: recommendation.title_sha256,
    abstract_sha256: recommendation.abstract_sha256, language: normalizeLanguage(recommendation.language),
    text: validateSummaryText(recommendation.text, recommendation.language),
    before_summary: parsed.status === 'valid' ? parsed.payload.text : null,
  };
  if (!regularItem(data)) return { ...base, decision: 'skip' as const, reason_codes: ['unsupported-item-type'], final_extra: null };
  if (!title) return { ...base, decision: 'skip' as const, reason_codes: ['missing-title'], final_extra: null };
  if (!abstract) return { ...base, decision: 'skip' as const, reason_codes: ['missing-abstract'], final_extra: null };
  if (currentVersion === null) return { ...base, decision: 'conflict' as const, reason_codes: ['missing-version'], final_extra: null };
  if (parsed.status === 'invalid') return { ...base, decision: 'conflict' as const, reason_codes: [parsed.error], final_extra: null };
  if (currentTitleHash !== recommendation.title_sha256 || currentAbstractHash !== recommendation.abstract_sha256) {
    return { ...base, decision: 'conflict' as const, reason_codes: ['stale-input'], final_extra: null };
  }
  if (mode === 'missing' && parsed.status === 'valid') {
    const current = parsed.payload.title_sha256 === currentTitleHash && parsed.payload.abstract_sha256 === currentAbstractHash;
    return { ...base, decision: current ? 'unchanged' as const : 'stale' as const,
      reason_codes: [current ? 'summary-current' : 'explicit-refresh-required'], final_extra: null };
  }
  const payload: AiSummaryPayload = {
    schema_version: 1, text: base.text, language: base.language, basis: 'title-abstract',
    title_sha256: currentTitleHash, abstract_sha256: currentAbstractHash, generated_at: now,
  };
  const finalExtra = encodeAiSummaryExtra(parsed.retained, payload);
  if (String(data.extra ?? '') === finalExtra) {
    return { ...base, decision: 'unchanged' as const, reason_codes: ['already-current'], final_extra: finalExtra };
  }
  return { ...base, decision: parsed.status === 'valid' ? 'refresh' as const : 'create' as const,
    reason_codes: currentVersion !== recommendation.expected_version ? ['version-advanced-input-unchanged'] : [], final_extra: finalExtra };
}

export async function executeAiSummaries(
  ctx: ToolContext,
  library: LibraryRef,
  input: { trigger: 'explicit-user-request'; mode: SummaryMode; items: AiSummaryRecommendation[] },
): Promise<Record<string, unknown>> {
  if (input.trigger !== 'explicit-user-request') throw new Error('AI Summary writes require explicit user request');
  const duplicateKeys = input.items.map((item) => item.item_key)
    .filter((key, index, all) => all.indexOf(key) !== index);
  if (duplicateKeys.length) throw new Error(`Duplicate AI Summary item keys: ${[...new Set(duplicateKeys)].join(', ')}`);
  const now = new Date().toISOString();
  const actions = [];
  for (const recommendation of input.items) {
    const item = await ctx.web.getItem(library, recommendation.item_key);
    actions.push(prepareAction(item, recommendation, input.mode, now));
  }
  const plan: Record<string, any> = {
    schema_version: '1.0', plan_type: 'zotero-ai-summaries', created_at: now, plan_hash: '',
    target: { library_type: library.type, library_id: library.id }, trigger: input.trigger,
    mode: input.mode, actions: actions.map(({ final_extra: _extra, ...action }) => action),
  };
  plan.plan_hash = aiSummaryPlanHash(plan);
  const root = summaryDirectory(ctx.config.dataDir, library);
  const stem = `${timestampName()}-${String(plan.plan_hash).slice(-12)}`;
  const planPath = join(root, 'plans', `${stem}.json`);
  const receiptPath = join(root, 'receipts', `${stem}.json`);
  await persistJson(planPath, plan);

  const results: Array<Record<string, unknown>> = [];
  for (const action of actions) {
    if (action.decision === 'skip' || action.decision === 'conflict' || action.decision === 'stale' || action.decision === 'unchanged') {
      const outcome: Outcome = action.decision === 'conflict' ? 'conflicted'
        : action.decision === 'skip' ? 'skipped' : action.decision;
      results.push({ item_key: action.item_key, outcome, zotero_version: action.live_version,
        before_summary: action.before_summary, after_summary: action.before_summary,
        error: action.reason_codes.join(';') || null });
      continue;
    }
    let liveVersion = action.live_version as number;
    try {
      const newVersion = await ctx.web.patchItem(library, action.item_key, { extra: action.final_extra }, liveVersion);
      results.push({ item_key: action.item_key, outcome: action.decision === 'create' ? 'created' : 'refreshed',
        zotero_version: newVersion, before_summary: action.before_summary, after_summary: action.text, error: null });
    } catch (error) {
      let failure: unknown = error;
      if (error instanceof ZoteroApiError && error.status === 412) {
        try {
          const fresh = await ctx.web.getItem(library, action.item_key);
          const retried = prepareAction(fresh, input.items.find((item) => item.item_key === action.item_key)!, input.mode, now);
          if (retried.decision === 'create' || retried.decision === 'refresh') {
            liveVersion = retried.live_version as number;
            const newVersion = await ctx.web.patchItem(library, action.item_key, { extra: retried.final_extra }, liveVersion);
            results.push({ item_key: action.item_key, outcome: retried.decision === 'create' ? 'created' : 'refreshed',
              zotero_version: newVersion, before_summary: retried.before_summary, after_summary: retried.text,
              error: null, retried: true });
            continue;
          }
          results.push({ item_key: action.item_key, outcome: retried.decision === 'stale' ? 'stale' : 'conflicted',
            zotero_version: retried.live_version, before_summary: retried.before_summary,
            after_summary: retried.before_summary, error: retried.reason_codes.join(';') || 'version-conflict' });
          continue;
        } catch (retryError) {
          failure = retryError;
        }
      }
      results.push({ item_key: action.item_key, outcome: 'failed', zotero_version: liveVersion,
        before_summary: action.before_summary, after_summary: action.before_summary,
        error: (failure instanceof Error ? failure.message : String(failure)).slice(0, 500) });
    }
  }
  const outcomes: Outcome[] = ['created', 'refreshed', 'unchanged', 'stale', 'skipped', 'conflicted', 'failed'];
  const summary = Object.fromEntries(outcomes.map((outcome) => [outcome, results.filter((result) => result.outcome === outcome).length]));
  const receipt = {
    schema_version: '1.0', receipt_type: 'zotero-ai-summaries', plan_hash: plan.plan_hash,
    status: summary.failed || summary.conflicted ? 'partial' : 'complete', started_at: now,
    updated_at: new Date().toISOString(), results, summary,
  };
  await persistJson(receiptPath, receipt);
  return { status: receipt.status, plan_hash: plan.plan_hash, plan_path: planPath, receipt_path: receiptPath, summary };
}
