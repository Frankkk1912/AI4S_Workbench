import { createHash } from 'node:crypto';
import { z } from 'zod';

/**
 * The shared data boundary between the optional Fulltext MCP and this Zotero
 * runtime. Keep this deliberately small: it contains immutable file facts,
 * never PDF bytes, download URLs, browser state, or credentials.
 */

const SHA256_HEX = /^[a-f0-9]{64}$/i;
const SHA256_ID = /^sha256:[a-f0-9]{64}$/i;

export const documentVersionSchema = z.enum([
  'version_of_record',
  'accepted_manuscript',
  'submitted_manuscript',
  'preprint',
  'unknown',
]);

export const fileRoleSchema = z.enum([
  'main_article',
  'supplement',
  'correction',
  'editorial_or_cover',
  'unknown',
]);

export const verificationLevelSchema = z.enum([
  'strong_identifier',
  'strong_context',
  'weak_title',
  'unverified',
  'mismatch',
]);

const hash = z.string().regex(SHA256_HEX, 'must be a SHA-256 hex digest');
const hashId = z.string().regex(SHA256_ID, 'must be a sha256:<hex> identifier');
const itemKey = z.string().regex(/^[A-Z0-9]{8}$/, 'must be a Zotero item key');
const isoTimestamp = z.string().datetime({ offset: true });

export const fulltextRoutePolicySchema = z.enum([
  'oa_only',
  'oa_then_current_entitlement',
  'oa_then_institutional',
]);

export const fulltextRecordStateSchema = z.enum([
  'queued',
  'skipped_existing',
  'resolving',
  'candidate_found',
  'downloading',
  'validating',
  'verified',
  'unverified',
  'auth_required',
  'not_entitled',
  'unavailable',
  'failed',
  'canceled',
]);

export const fulltextJobStateSchema = z.enum([
  'queued',
  'resolving_open_access',
  'validating_oa_candidates',
  'checking_current_entitlement',
  'institution_auth_required',
  'visible_browser_ready',
  'retrieving_institutional_pdf',
  'validating_institutional_candidate',
  'building_handoff',
  'complete',
  'partial',
  'auth_required',
  'retrying',
  'failed',
  'canceled',
  'stale',
]);

const candidateUrl = z.string().url().max(2_048).refine((value) => {
  const protocol = new URL(value).protocol;
  return protocol === 'https:' || protocol === 'http:';
}, 'must use http or https');

/** Input accepted by `fulltext_fetch_submit`; browser/session data is never part of this request. */
export const fulltextFetchRecordSchema = z.object({
  evidence_id: z.string().trim().min(1).max(300),
  zotero_item_key: itemKey,
  doi: z.string().trim().min(1).max(300).optional(),
  arxiv_id: z.string().trim().min(3).max(100).optional(),
  repository_id: z.string().trim().min(3).max(300).optional(),
  title: z.string().trim().min(1).max(2_000),
  year: z.number().int().min(1000).max(3000).optional(),
  item_type: z.string().trim().min(1).max(100),
  candidate_urls: z.array(candidateUrl).max(20).default([]),
}).strict().superRefine((record, ctx) => {
  if (!record.doi && !record.arxiv_id && !record.repository_id) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'requires doi, arxiv_id, or repository_id' });
  }
});

export type FulltextFetchRecord = z.infer<typeof fulltextFetchRecordSchema>;

export const fulltextFetchRequestSchema = z.object({
  request_id: hash,
  records: z.array(fulltextFetchRecordSchema).min(1).max(50),
  route_policy: fulltextRoutePolicySchema,
}).strict().superRefine((request, ctx) => {
  const evidenceIds = new Set<string>();
  const itemKeys = new Set<string>();
  for (const [index, record] of request.records.entries()) {
    if (evidenceIds.has(record.evidence_id)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['records', index, 'evidence_id'], message: 'evidence_id must be unique' });
    }
    evidenceIds.add(record.evidence_id);
    if (itemKeys.has(record.zotero_item_key)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['records', index, 'zotero_item_key'], message: 'zotero_item_key must be unique' });
    }
    itemKeys.add(record.zotero_item_key);
  }
});

export type FulltextFetchRequest = z.infer<typeof fulltextFetchRequestSchema>;

/** Persisted job state contains compact outcomes, never signed URLs, browser state, or PDF bytes. */
export const fulltextJobSchema = z.object({
  schema_version: z.literal(1),
  job_id: z.string().regex(/^ft-[A-Za-z0-9-]{8,128}$/),
  request_id: hash,
  route_policy: fulltextRoutePolicySchema,
  state: fulltextJobStateSchema,
  created_at: isoTimestamp,
  updated_at: isoTimestamp,
  records: z.array(z.object({
    evidence_id: z.string().trim().min(1).max(300),
    zotero_item_key: itemKey,
    state: fulltextRecordStateSchema,
    error_code: z.string().trim().min(1).max(100).nullable(),
  }).strict()).min(1).max(50),
  user_action_required: z.boolean(),
  handoff_id: z.string().regex(/^fth-[A-Za-z0-9-]{8,128}$/).nullable(),
  handoff_hash: hashId.nullable(),
}).strict().superRefine((job, ctx) => {
  const ids = new Set<string>();
  for (const [index, record] of job.records.entries()) {
    if (ids.has(record.evidence_id)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['records', index, 'evidence_id'], message: 'evidence_id must be unique' });
    }
    ids.add(record.evidence_id);
  }
  const hasHandoff = Boolean(job.handoff_id || job.handoff_hash);
  if (hasHandoff && (!job.handoff_id || !job.handoff_hash)) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, message: 'handoff_id and handoff_hash must be supplied together' });
  }
  if (job.state === 'complete' && !job.handoff_id) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['handoff_id'], message: 'complete job requires a handoff' });
  }
});

export type FulltextJob = z.infer<typeof fulltextJobSchema>;

export const fulltextHandoffRecordSchema = z.object({
  evidence_id: z.string().trim().min(1).max(300),
  zotero_item_key: itemKey,
  expected_parent: z.object({
    doi: z.string().trim().min(1).max(300),
    title: z.string().trim().min(1).max(2_000),
  }).strict(),
  retrieval: z.object({
    status: z.literal('verified'),
    provider: z.string().trim().min(1).max(100),
    access_mode: z.enum([
      'open_access_http',
      'publisher_open_access',
      'direct_entitled_network',
      'publisher_api_entitled',
      'federated_visible_browser',
      'institution_gateway_visible_browser',
    ]),
    document_version: documentVersionSchema,
    file_role: z.literal('main_article'),
    retrieved_at: isoTimestamp,
  }).strict(),
  artifact: z.object({
    artifact_id: hashId,
    sha256: hash,
    md5: z.string().regex(/^[a-f0-9]{32}$/i, 'must be an MD5 hex digest'),
    bytes: z.number().int().positive(),
    content_type: z.literal('application/pdf'),
    page_count: z.number().int().positive(),
  }).strict(),
  verification: z.object({
    level: z.enum(['strong_identifier', 'strong_context']),
    doi_match: z.literal(true),
    title_match: z.literal(true),
  }).strict(),
}).strict().superRefine((record, ctx) => {
  const expectedId = `sha256:${record.artifact.sha256}`.toLowerCase();
  if (record.artifact.artifact_id.toLowerCase() !== expectedId) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['artifact', 'artifact_id'], message: 'must match artifact.sha256' });
  }
});

export const fulltextHandoffSchema = z.object({
  schema_version: z.literal(1),
  handoff_id: z.string().regex(/^fth-[A-Za-z0-9-]{8,128}$/),
  job_id: z.string().regex(/^ft-[A-Za-z0-9-]{8,128}$/),
  request_id: hash,
  created_at: isoTimestamp,
  records: z.array(fulltextHandoffRecordSchema).min(1).max(50),
  handoff_hash: hashId,
}).strict().superRefine((handoff, ctx) => {
  const evidenceIds = new Set<string>();
  const itemKeys = new Set<string>();
  for (const [index, record] of handoff.records.entries()) {
    if (evidenceIds.has(record.evidence_id)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['records', index, 'evidence_id'], message: 'evidence_id must be unique' });
    }
    evidenceIds.add(record.evidence_id);
    if (itemKeys.has(record.zotero_item_key)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, path: ['records', index, 'zotero_item_key'], message: 'zotero_item_key must be unique' });
    }
    itemKeys.add(record.zotero_item_key);
  }
});

export type FulltextHandoff = z.infer<typeof fulltextHandoffSchema>;

export const attachmentReceiptSchema = z.object({
  schema_version: z.literal(1),
  receipt_type: z.literal('zotero-fulltext-attachment'),
  handoff_id: z.string().regex(/^fth-[A-Za-z0-9-]{8,128}$/),
  handoff_hash: hashId,
  created_at: isoTimestamp,
  updated_at: isoTimestamp,
  library: z.object({ type: z.enum(['user', 'group']), id: z.number().int().nonnegative() }).strict(),
  results: z.array(z.object({
    evidence_id: z.string().trim().min(1).max(300),
    parent_item_key: itemKey,
    artifact_sha256: hash,
    attachment_item_key: itemKey.nullable(),
    phase: z.enum(['attachment_created', 'bytes_uploaded', 'registered', 'verified']).nullable(),
    status: z.enum(['pending', 'complete', 'conflict', 'failed', 'skip_existing']),
    error_code: z.string().trim().min(1).max(100).nullable(),
  }).strict()).max(50),
}).strict();

export type AttachmentReceipt = z.infer<typeof attachmentReceiptSchema>;

function deepSort(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(deepSort);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, child]) => [key, deepSort(child)]));
  }
  return value;
}

/** Stable JSON for hashing a schema-controlled handoff. Arrays retain their declared order. */
export function canonicalFulltextHandoffJson(handoff: Omit<FulltextHandoff, 'handoff_hash'> | FulltextHandoff): string {
  const withoutHash = structuredClone(handoff) as Record<string, unknown>;
  delete withoutHash.handoff_hash;
  return JSON.stringify(deepSort(withoutHash));
}

export function canonicalFulltextHandoffHash(handoff: Omit<FulltextHandoff, 'handoff_hash'> | FulltextHandoff): string {
  return `sha256:${createHash('sha256').update(canonicalFulltextHandoffJson(handoff), 'utf8').digest('hex')}`;
}

/** Validates strict shape, cross-record invariants, and canonical hash before any file operation. */
export function validateFulltextHandoff(value: unknown): FulltextHandoff {
  const handoff = fulltextHandoffSchema.parse(value);
  const expectedHash = canonicalFulltextHandoffHash(handoff);
  if (handoff.handoff_hash.toLowerCase() !== expectedHash) {
    throw new Error(`Fulltext handoff hash mismatch: expected ${expectedHash}, found ${handoff.handoff_hash}`);
  }
  return handoff;
}
