import { createHash } from 'node:crypto';
import { chmod, lstat, mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import type { LibraryRef } from '../../api/web-client.js';
import { resumeUploadFile } from '../../api/attachments.js';
import type { ToolContext } from '../../registry/registry.js';
import { attachmentReceiptSchema, validateFulltextHandoff, type AttachmentReceipt, type FulltextHandoff } from './handoff-contract.js';

type ReceiptResult = AttachmentReceipt['results'][number];
const FILE_MODE = 0o600;
const DIRECTORY_MODE = 0o700;

function now(): string { return new Date().toISOString(); }
function dataOf(item: any): Record<string, any> { return item?.data ?? item ?? {}; }
function normalizeDoi(value: unknown): string {
  return String(value ?? '').trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, '').replace(/^doi:\s*/i, '').replace(/[\s.]+$/u, '').toLowerCase();
}
function regularBibliographicItem(item: any): boolean {
  return !['attachment', 'note', 'annotation'].includes(String(dataOf(item).itemType ?? ''));
}
function filePdfChildren(children: any[]): any[] {
  return children.filter((child) => {
    const data = dataOf(child);
    return data.itemType === 'attachment'
      && String(data.contentType ?? '').toLowerCase().split(';')[0] === 'application/pdf'
      && ['imported_file', 'linked_file'].includes(String(data.linkMode ?? ''));
  });
}

async function privateDirectory(path: string): Promise<void> {
  await mkdir(path, { recursive: true, mode: DIRECTORY_MODE });
  await chmod(path, DIRECTORY_MODE).catch(() => undefined);
}

async function writeJson(path: string, value: unknown): Promise<void> {
  await privateDirectory(dirname(path));
  const temporary = `${path}.${process.pid}.${Date.now()}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', mode: FILE_MODE });
  await rename(temporary, path);
  await chmod(path, FILE_MODE).catch(() => undefined);
}

function receiptPath(root: string, handoffId: string): string { return join(root, 'receipts', `${handoffId}.json`); }
function artifactPath(root: string, sha: string): string { return join(root, 'artifacts', `${sha.toLowerCase()}.pdf`); }

async function readArtifact(root: string, sha: string): Promise<string> {
  if (!/^[a-f0-9]{64}$/i.test(sha)) throw new Error('Invalid artifact SHA-256.');
  const path = artifactPath(root, sha);
  const info = await lstat(path);
  if (!info.isFile() || info.isSymbolicLink()) throw new Error('Fulltext artifact is not a regular private file.');
  const bytes = await readFile(path);
  const actual = createHash('sha256').update(bytes).digest('hex');
  if (actual !== sha.toLowerCase()) throw new Error('Fulltext artifact hash does not match the handoff.');
  if (bytes.byteLength < 256 || !bytes.subarray(0, 5).equals(Buffer.from('%PDF-'))) throw new Error('Fulltext artifact is not a PDF.');
  return path;
}

function newReceipt(handoff: FulltextHandoff, library: LibraryRef): AttachmentReceipt {
  const timestamp = now();
  return {
    schema_version: 1,
    receipt_type: 'zotero-fulltext-attachment',
    handoff_id: handoff.handoff_id,
    handoff_hash: handoff.handoff_hash,
    created_at: timestamp,
    updated_at: timestamp,
    library: { type: library.type, id: library.id },
    results: handoff.records.map((record) => ({
      evidence_id: record.evidence_id,
      parent_item_key: record.zotero_item_key,
      artifact_sha256: record.artifact.sha256,
      attachment_item_key: null,
      phase: null,
      status: 'pending',
      error_code: null,
    })),
  };
}

async function loadReceipt(root: string, handoff: FulltextHandoff, library: LibraryRef): Promise<AttachmentReceipt> {
  try {
    const parsed = attachmentReceiptSchema.parse(JSON.parse(await readFile(receiptPath(root, handoff.handoff_id), 'utf8')));
    if (parsed.handoff_hash !== handoff.handoff_hash || parsed.library.type !== library.type || parsed.library.id !== library.id) {
      throw new Error('Existing fulltext attachment receipt conflicts with this handoff or library.');
    }
    return parsed;
  } catch (error: unknown) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return newReceipt(handoff, library);
    throw error;
  }
}

async function saveReceipt(root: string, receipt: AttachmentReceipt): Promise<void> {
  receipt.updated_at = now();
  await writeJson(receiptPath(root, receipt.handoff_id), receipt);
}

function resultFor(receipt: AttachmentReceipt, evidenceId: string): ReceiptResult {
  const result = receipt.results.find((entry) => entry.evidence_id === evidenceId);
  if (!result) throw new Error(`Receipt is missing ${evidenceId}.`);
  return result;
}

async function attachmentStillLive(ctx: ToolContext, library: LibraryRef, result: ReceiptResult): Promise<boolean> {
  if (!result.attachment_item_key) return false;
  try {
    const item = await ctx.web.getItem(library, result.attachment_item_key);
    return dataOf(item).parentItem === result.parent_item_key;
  } catch { return false; }
}

export interface FulltextApplySummary {
  attached: number;
  skipped_existing: number;
  conflicts: number;
  failed: number;
  pending: number;
}

export async function executeFulltextHandoff(
  ctx: ToolContext,
  library: LibraryRef,
  input: { handoffId: string; handoffHash: string },
): Promise<{ handoffId: string; summary: FulltextApplySummary }> {
  if (!/^fth-[A-Za-z0-9-]{8,128}$/.test(input.handoffId)) throw new Error('Invalid fulltext handoff ID.');
  const raw = JSON.parse(await readFile(join(ctx.config.fulltextExchangeRoot, 'handoffs', `${input.handoffId}.json`), 'utf8'));
  const handoff = validateFulltextHandoff(raw);
  if (handoff.handoff_hash !== input.handoffHash) throw new Error('Provided handoff_hash does not match the private handoff.');
  const receipt = await loadReceipt(ctx.config.fulltextExchangeRoot, handoff, library);

  for (const record of handoff.records) {
    const receiptResult = resultFor(receipt, record.evidence_id);
    try {
      if (receiptResult.status === 'complete') {
        if (!await attachmentStillLive(ctx, library, receiptResult)) {
          receiptResult.status = 'conflict';
          receiptResult.error_code = 'ZOTERO_PARENT_CONFLICT';
          await saveReceipt(ctx.config.fulltextExchangeRoot, receipt);
        }
        continue;
      }
      if (receiptResult.status === 'skip_existing' || receiptResult.status === 'conflict') continue;

      const parent = await ctx.web.getItem(library, record.zotero_item_key);
      if (!regularBibliographicItem(parent) || normalizeDoi(dataOf(parent).DOI) !== normalizeDoi(record.expected_parent.doi)) {
        receiptResult.status = 'conflict';
        receiptResult.error_code = 'ZOTERO_PARENT_CONFLICT';
        await saveReceipt(ctx.config.fulltextExchangeRoot, receipt);
        continue;
      }
      const children = await ctx.web.getItemChildren(library, record.zotero_item_key, { limit: 100 });
      const existing = filePdfChildren(children.data);
      if (existing.length === 1) {
        receiptResult.status = 'skip_existing';
        receiptResult.attachment_item_key = String(existing[0]?.key ?? dataOf(existing[0]).key ?? '') || null;
        receiptResult.phase = null;
        receiptResult.error_code = 'EXISTING_PDF';
        await saveReceipt(ctx.config.fulltextExchangeRoot, receipt);
        continue;
      }
      if (existing.length > 1) {
        receiptResult.status = 'conflict';
        receiptResult.error_code = 'ZOTERO_PARENT_CONFLICT';
        await saveReceipt(ctx.config.fulltextExchangeRoot, receipt);
        continue;
      }
      const filePath = await readArtifact(ctx.config.fulltextExchangeRoot, record.artifact.sha256);
      if (!receiptResult.attachment_item_key) {
        const created = await ctx.web.writeItems(library, [{
          itemType: 'attachment', parentItem: record.zotero_item_key, linkMode: 'imported_file',
          title: `Fulltext PDF — ${record.expected_parent.title}`,
          filename: `${record.artifact.sha256}.pdf`, contentType: 'application/pdf',
        }]);
        if (!created.successful.length) throw new Error(`Zotero did not create an attachment item: ${JSON.stringify(created.failed)}`);
        receiptResult.attachment_item_key = created.successful[0]!.key;
        receiptResult.phase = 'attachment_created';
        receiptResult.status = 'pending';
        receiptResult.error_code = null;
        await saveReceipt(ctx.config.fulltextExchangeRoot, receipt);
      }
      if (receiptResult.phase !== 'registered' && receiptResult.phase !== 'verified') {
        await resumeUploadFile(ctx.web, library, { filePath, attachmentKey: receiptResult.attachment_item_key! }, async (phase) => {
          receiptResult.phase = phase;
          await saveReceipt(ctx.config.fulltextExchangeRoot, receipt);
        });
      }
      if (!await attachmentStillLive(ctx, library, receiptResult)) throw new Error('Zotero attachment was not readable after upload registration.');
      receiptResult.phase = 'verified';
      receiptResult.status = 'complete';
      receiptResult.error_code = null;
      await saveReceipt(ctx.config.fulltextExchangeRoot, receipt);
    } catch (error) {
      receiptResult.status = 'failed';
      receiptResult.error_code = error instanceof Error && /hash|PDF|artifact/i.test(error.message) ? 'PDF_INVALID' : 'ZOTERO_UPLOAD_FAILED';
      await saveReceipt(ctx.config.fulltextExchangeRoot, receipt);
    }
  }
  const summary: FulltextApplySummary = {
    attached: receipt.results.filter((entry) => entry.status === 'complete').length,
    skipped_existing: receipt.results.filter((entry) => entry.status === 'skip_existing').length,
    conflicts: receipt.results.filter((entry) => entry.status === 'conflict').length,
    failed: receipt.results.filter((entry) => entry.status === 'failed').length,
    pending: receipt.results.filter((entry) => entry.status === 'pending').length,
  };
  return { handoffId: handoff.handoff_id, summary };
}
