import { z } from 'zod';
import type { LibraryRef } from '../api/web-client.js';
import type { ToolDefinition } from '../registry/registry.js';
import { ok } from '../registry/registry.js';

type AttachmentState =
  | 'existing_file_pdf'
  | 'linked_pdf_url_only'
  | 'non_pdf_attachments_only'
  | 'multiple_pdf_files'
  | 'missing_pdf'
  | 'unsupported_parent';

function dataOf(item: any): Record<string, any> { return item?.data ?? item ?? {}; }
function keyOf(item: any): string { const data = dataOf(item); return String(item?.key ?? data.key ?? ''); }
function versionOf(item: any): number | null {
  const version = item?.version ?? item?.data?.version;
  return Number.isInteger(version) ? version : null;
}

function normalizeDoi(value: unknown): string | null {
  const doi = String(value ?? '').trim()
    .replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, '')
    .replace(/^doi:\s*/i, '')
    .replace(/[\s.]+$/u, '')
    .toLowerCase();
  return /^10\.\d{4,9}\/.+/.test(doi) ? doi : null;
}

function isBibliographicParent(data: Record<string, any>): boolean {
  return Boolean(data.itemType) && !['attachment', 'note', 'annotation'].includes(String(data.itemType));
}

function isPdfAttachment(data: Record<string, any>): boolean {
  return String(data.itemType ?? '') === 'attachment'
    && String(data.contentType ?? '').toLowerCase().split(';')[0] === 'application/pdf';
}

function attachmentProjection(item: any): Record<string, unknown> {
  const data = dataOf(item);
  return {
    item_key: keyOf(item),
    link_mode: String(data.linkMode ?? 'unknown'),
    content_type: String(data.contentType ?? ''),
    filename: String(data.filename ?? ''),
    title: String(data.title ?? ''),
  };
}

function attachmentState(children: any[]): { state: AttachmentState; existing: Record<string, unknown>[] } {
  const attachments = children.filter((item) => String(dataOf(item).itemType ?? '') === 'attachment');
  const pdfs = attachments.filter((item) => isPdfAttachment(dataOf(item)));
  const filePdfs = pdfs.filter((item) => ['imported_file', 'linked_file'].includes(String(dataOf(item).linkMode ?? '')));
  if (filePdfs.length > 1) return { state: 'multiple_pdf_files', existing: filePdfs.map(attachmentProjection) };
  if (filePdfs.length === 1) return { state: 'existing_file_pdf', existing: filePdfs.map(attachmentProjection) };
  const linkedPdfUrls = pdfs.filter((item) => String(dataOf(item).linkMode ?? '') === 'linked_url');
  if (linkedPdfUrls.length) return { state: 'linked_pdf_url_only', existing: linkedPdfUrls.map(attachmentProjection) };
  if (attachments.length) return { state: 'non_pdf_attachments_only', existing: attachments.map(attachmentProjection) };
  return { state: 'missing_pdf', existing: [] };
}

const fulltextContext: ToolDefinition = {
  name: 'zotero_fulltext_context',
  title: 'Check exact Zotero parents before fulltext retrieval',
  description:
    'Read exact Zotero parent records and child attachments before an optional Fulltext MCP job. It classifies locally held file PDFs separately from linked PDF URLs, snapshots, and non-PDF attachments; it never downloads, uploads, deletes, or changes a Zotero item. Items without an exact DOI, unsupported parents, or duplicate DOIs in this request are marked review_required rather than becoming automatic download targets.',
  inputSchema: {
    item_keys: z.array(z.string().regex(/^[A-Z0-9]{8}$/)).min(1).max(50),
    library_type: z.enum(['user', 'group']).optional(),
    library_id: z.number().int().nonnegative().optional(),
  },
  annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
  handler: async (args, ctx) => {
    const library: LibraryRef = args.library_id === undefined
      ? ctx.router.defaultLibrary()
      : { type: args.library_type ?? 'group', id: args.library_id };
    const items = await Promise.all(args.item_keys.map(async (requestedKey: string) => {
      const item = await ctx.router.getItem(requestedKey, { library });
      const data = dataOf(item);
      if (!isBibliographicParent(data)) {
        return {
          item_key: keyOf(item) || requestedKey,
          item_version: versionOf(item),
          doi: normalizeDoi(data.DOI),
          title: String(data.title ?? ''),
          attachment_state: 'unsupported_parent' as const,
          existing_pdf_attachments: [],
          ownership_state: 'review_required' as const,
          reason: 'unsupported-parent-item',
        };
      }
      const children = await ctx.router.getItemChildren(keyOf(item) || requestedKey, { library, limit: 100 });
      const attachment = attachmentState(children.data);
      return {
        item_key: keyOf(item) || requestedKey,
        item_version: versionOf(item),
        doi: normalizeDoi(data.DOI),
        title: String(data.title ?? ''),
        attachment_state: attachment.state,
        existing_pdf_attachments: attachment.existing,
        ownership_state: 'ready' as const,
      };
    }));

    const doiOwners = new Map<string, string[]>();
    for (const item of items) {
      if (!item.doi) continue;
      doiOwners.set(item.doi, [...(doiOwners.get(item.doi) ?? []), item.item_key]);
    }
    for (const item of items) {
      if (item.ownership_state !== 'ready') continue;
      if (!item.doi) {
        item.ownership_state = 'review_required';
        (item as Record<string, unknown>).reason = 'missing-doi';
      } else if ((doiOwners.get(item.doi)?.length ?? 0) > 1) {
        item.ownership_state = 'review_required';
        (item as Record<string, unknown>).reason = 'duplicate-doi-in-request';
      }
    }
    const counts = {
      // A linked publisher URL, snapshot, or other non-PDF attachment is not an
      // offline main-article PDF. It remains eligible for retrieval; only a
      // local/imported PDF (or an ambiguous plurality of them) is a skip.
      ready_for_fetch: items.filter((item) => item.ownership_state === 'ready'
        && !['existing_file_pdf', 'multiple_pdf_files'].includes(item.attachment_state)).length,
      existing_file_pdf: items.filter((item) => item.attachment_state === 'existing_file_pdf' || item.attachment_state === 'multiple_pdf_files').length,
      review_required: items.filter((item) => item.ownership_state === 'review_required').length,
    };
    return ok({ library, items, summary: counts }, `Checked ${items.length} Zotero parent(s): ${counts.ready_for_fetch} missing a file PDF, ${counts.existing_file_pdf} already hold a file PDF, ${counts.review_required} need review.`);
  },
};

export default fulltextContext;
