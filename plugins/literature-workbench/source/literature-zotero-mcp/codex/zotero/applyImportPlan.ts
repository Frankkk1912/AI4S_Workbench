import { callMCPTool } from '../runtime.js';

/**
 * Apply an approved Zotero import plan — Validate and dry-run or apply a file-based zotero_import_plan.json. The tool resolves or creates one exact project collection, creates new items, reuses uniquely matched items, preserves unrelated tags/collections, and saves an idempotent zotero_import_receipt.json. Apply mode requires the exact approved plan hash and a Zotero Web API key. It never writes through the Local API and never merges, trashes, or deletes items.
 * Params: plan_path, mode, receipt_path, confirm_plan_hash.
 */
export function applyImportPlan(input: Record<string, unknown> = {}): Promise<any> {
  return callMCPTool('zotero_apply_import_plan', input);
}
