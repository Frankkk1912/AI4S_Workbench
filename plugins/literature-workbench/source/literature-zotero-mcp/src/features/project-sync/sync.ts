import { readFile } from 'node:fs/promises';
import type { LibraryRef } from '../../api/web-client.js';
import type { ToolContext } from '../../registry/registry.js';
import { applyImportPlan, dryRunImportPlan } from '../import-plan/apply.js';
import { canonicalPlanHash, type ImportPlan, type ImportPlanAction } from '../import-plan/contract.js';
import { displayMetricYear, isPreprintEvidence, mergeMetricIntoExtra, metricFromEvidence, synchronizeCurrentMetricTags, type EvidenceMetric } from '../evidence-metrics.js';
import { renderReportMarkdown, sha256 } from './report-renderer.js';
import { projectReceiptPath, projectStatePath, readProjectState, writeProjectState, type ProjectSyncState } from './state.js';

const REPORT_TAG = 'AI4S:Artifact:LiteratureReport';
const LARGE_CREATE_THRESHOLD = 50;

function dataOf(value: any): Record<string, any> { return value?.data && typeof value.data === 'object' ? value.data : value ?? {}; }
function keyOf(value: any): string { return String(value?.key ?? value?.data?.key ?? ''); }
function versionOf(value: any): number | null {
  const version = value?.version ?? value?.data?.version;
  return Number.isInteger(version) ? version : null;
}
function cleanDoi(value: unknown): string {
  return String(value ?? '').trim().toLowerCase().replace(/^https?:\/\/(dx\.)?doi\.org\//, '').replace(/^doi:\s*/, '').replace(/[ .]+$/, '');
}
function cleanPmid(value: unknown): string { return String(value ?? '').match(/\d+/)?.[0] ?? ''; }
function normalizedTitle(value: unknown): string {
  return String(value ?? '').normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').replace(/\s+/g, ' ').trim();
}
function yearOf(value: unknown): string { return String(value ?? '').match(/(?:19|20)\d{2}/)?.[0] ?? ''; }
function identity(record: Record<string, any>) {
  return { doi: cleanDoi(record.doi ?? record.DOI), pmid: cleanPmid(record.pmid ?? record.PMID ?? record.extra), title: normalizedTitle(record.title), year: yearOf(record.date ?? record.year) };
}
function candidateIdentity(candidate: any) { return identity(dataOf(candidate)); }

export function stableEvidenceId(record: Record<string, any>): string {
  const found = identity(record);
  let computed: string;
  if (found.doi) computed = `doi:${found.doi}`;
  else if (found.pmid) computed = `pmid:${found.pmid}`;
  else {
    const source = String(record.source ?? 'source').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    const sourceId = String(record.id ?? record.source_id ?? '').trim();
    if (sourceId) computed = `source:${source || 'source'}:${sourceId}`;
    else if (found.title) computed = `title-sha256:${sha256(found.title)}`;
    else throw new Error('Evidence record has no stable identifier or usable title');
  }
  const supplied = String(record.evidence_id ?? '').trim();
  if (supplied && supplied !== computed) throw new Error(`Evidence ID mismatch: ${supplied} != ${computed}`);
  return computed;
}

function evidenceRecords(value: any): Record<string, any>[] {
  if (Array.isArray(value)) return value;
  for (const key of ['records', 'ranked', 'results', 'items']) if (Array.isArray(value?.[key])) return value[key];
  throw new Error('Evidence JSON must be an array or contain records/ranked/results/items');
}

function creators(record: Record<string, any>): Array<Record<string, string>> {
  const raw = record.creators ?? record.authors ?? [];
  const values = Array.isArray(raw) ? raw : String(raw).split(';');
  const output: Array<Record<string, string>> = [];
  for (const value of values) {
    if (value && typeof value === 'object') {
      const lastName = String(value.lastName ?? value.last_name ?? '').trim();
      const firstName = String(value.firstName ?? value.first_name ?? '').trim();
      const name = String(value.name ?? '').trim();
      if (lastName) output.push({ creatorType: String(value.creatorType ?? 'author'), lastName, ...(firstName ? { firstName } : {}) });
      else if (name) output.push({ creatorType: String(value.creatorType ?? 'author'), name });
    } else {
      const name = String(value ?? '').trim();
      if (name) output.push({ creatorType: 'author', name });
    }
  }
  return output;
}

function articleTypeTags(record: Record<string, any>): string[] {
  const raw = record.article_types ?? record.publication_types ?? [];
  const values = Array.isArray(raw) ? raw : String(raw).split(';');
  const aliases: Record<string, string> = {
    'journal article': 'Article', article: 'Article', review: 'Review', 'systematic review': 'Systematic Review',
    'meta analysis': 'Meta-Analysis', 'clinical trial': 'Clinical Trial',
    'randomized controlled trial': 'Randomized Controlled Trial', preprint: 'Preprint', letter: 'Letter', editorial: 'Editorial', guideline: 'Guideline',
  };
  const tags = values.map((value) => {
    const original = String(value ?? '').replace(/\s+/g, ' ').trim();
    const key = original.toLowerCase().replace(/[_-]+/g, ' ').replace(/[^a-z0-9 ]+/g, '').replace(/\s+/g, ' ').trim();
    return original ? `AI4S:ArticleType:${aliases[key] ?? original.slice(0, 80)}` : '';
  }).filter(Boolean);
  return [...new Set(tags)].sort();
}

function zoteroItem(record: Record<string, any>, tags: string[]): Record<string, any> | null {
  const found = identity(record);
  const source = String(record.source ?? '').toLowerCase();
  const types = String(record.article_types ?? record.publication_types ?? '').toLowerCase();
  const journal = String(record.journal ?? record.publicationTitle ?? '').trim();
  const itemType = record.itemType === 'preprint' || source === 'arxiv' || types.includes('preprint') ? 'preprint'
    : record.itemType === 'journalArticle' || ['pubmed', 'wos', 'web-of-science', 'webofscience'].includes(source) || journal ? 'journalArticle' : null;
  if (!found.title || !itemType) return null;
  const item: Record<string, any> = {
    itemType, title: String(record.title).replace(/\s+/g, ' ').trim(), creators: creators(record),
    tags: [...new Set([...tags, ...articleTypeTags(record)])].sort().map((tag) => ({ tag })),
  };
  const optional: Record<string, unknown> = {
    abstractNote: record.abstract ?? record.abstractNote, date: record.date ?? record.year,
    DOI: found.doi, url: record.url,
    ...(itemType === 'preprint' ? { repository: record.repository ?? journal } : { publicationTitle: journal }),
  };
  for (const [key, value] of Object.entries(optional)) if (value !== undefined && value !== null && String(value).trim()) item[key] = String(value).trim();
  if (found.pmid) item.extra = `PMID: ${found.pmid}`;
  return item;
}

async function allCollections(ctx: ToolContext, lib: LibraryRef): Promise<any[]> {
  const output: any[] = [];
  let start = 0;
  let hasMore = true;
  while (hasMore) {
    const page = await ctx.web.listCollections(lib, { limit: 100, start });
    output.push(...page.data);
    hasMore = page.data.length > 0 && output.length < page.totalResults;
    if (hasMore) start += page.data.length;
  }
  return output;
}

async function actionsFor(ctx: ToolContext, lib: LibraryRef, records: Array<{ id: string; record: Record<string, any> }>, tags: string[]) {
  const actions: ImportPlanAction[] = [];
  const risks: string[] = [];
  for (let index = 0; index < records.length; index += 1) {
    const { id, record } = records[index]!;
    const foundIdentity = identity(record);
    const item = zoteroItem(record, tags);
    const base = { evidence_id: id, display_rank: index + 1, source: { database: String(record.source ?? '') || null, record_id: String(record.id ?? '') || null } };
    if (!item || (!foundIdentity.doi && !foundIdentity.pmid)) {
      actions.push({ ...base, decision: 'check', reason_codes: ['missing-stable-id-or-unsupported-item'], item, match: null });
      risks.push(`${id}:missing-stable-id-or-unsupported-item`); continue;
    }
    const query = foundIdentity.doi || foundIdentity.pmid;
    const found = await ctx.web.listItems(lib, { q: query, qmode: 'everything', top: true, includeTrashed: false, limit: 50 });
    if (found.totalResults > 50) {
      actions.push({ ...base, decision: 'check', reason_codes: ['candidate-limit-exceeded'], item, match: null });
      risks.push(`${id}:candidate-limit-exceeded`); continue;
    }
    const exact = found.data.filter((candidate) => {
      const live = candidateIdentity(candidate);
      return Boolean((foundIdentity.doi && foundIdentity.doi === live.doi) || (foundIdentity.pmid && foundIdentity.pmid === live.pmid));
    });
    if (exact.length === 1) {
      const live = candidateIdentity(exact[0]);
      const conflicts = Boolean((foundIdentity.doi && live.doi && foundIdentity.doi !== live.doi) || (foundIdentity.pmid && live.pmid && foundIdentity.pmid !== live.pmid));
      if (!conflicts && versionOf(exact[0]) !== null && keyOf(exact[0])) {
        actions.push({ ...base, decision: 'reuse', reason_codes: ['unique-doi-or-pmid-match'], item,
          match: { zotero_key: keyOf(exact[0]), zotero_version: versionOf(exact[0]), match_kind: foundIdentity.doi === live.doi ? 'doi' : 'pmid' } });
        continue;
      }
    }
    if (exact.length > 0) {
      actions.push({ ...base, decision: 'check', reason_codes: ['multiple-or-conflicting-identifier-matches'], item, match: null });
      risks.push(`${id}:multiple-or-conflicting-identifier-matches`); continue;
    }
    const titleCandidate = found.data.some((candidate) => {
      const live = candidateIdentity(candidate);
      return foundIdentity.title && foundIdentity.title === live.title && (!foundIdentity.year || !live.year || foundIdentity.year === live.year);
    });
    if (titleCandidate) {
      actions.push({ ...base, decision: 'check', reason_codes: ['title-only-candidate'], item, match: null });
      risks.push(`${id}:title-only-candidate`); continue;
    }
    actions.push({ ...base, decision: 'create', reason_codes: ['no-library-identifier-match'], item, match: null });
  }
  return { actions, risks };
}

function ownedNote(item: any, projectTag: string): boolean {
  const tags = (dataOf(item).tags ?? []).map((entry: any) => typeof entry === 'string' ? entry : entry?.tag);
  return tags.includes(REPORT_TAG) && tags.includes(projectTag);
}
function compactEvidenceRisks(values: string[]): string[] {
  const counts = new Map<string, number>();
  for (const value of values) {
    const separator = value.lastIndexOf(':');
    const reason = separator >= 0 ? value.slice(separator + 1) : value;
    counts.set(reason, (counts.get(reason) ?? 0) + 1);
  }
  return [...counts.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([reason, count]) => `${reason}:${count}`);
}
async function notesInCollection(ctx: ToolContext, lib: LibraryRef, collectionKey: string): Promise<any[]> {
  return (await ctx.web.listItems(lib, { collectionKey, itemType: 'note', top: true, limit: 100 })).data;
}

export interface ProjectSyncInput {
  projectSlug: string;
  collectionName?: string;
  searchDate: string;
  reportPath: string;
  evidencePath: string;
  selectionPath?: string;
  priorityRecommendationsPath?: string;
  confirmReviewId?: string;
}
export interface ProjectSyncResult {
  status: 'complete' | 'needs_review' | 'blocked'; collectionName: string; collectionKey?: string;
  created: number; reused: number; report: 'created' | 'updated' | 'unchanged' | 'pending'; risks: string[]; reviewId?: string;
  metrics: { updated: number; missing: number; preprintsSkipped: number; displayYear: number; status: string };
}

export async function syncLiteratureProject(ctx: ToolContext, lib: LibraryRef, input: ProjectSyncInput): Promise<ProjectSyncResult> {
  const [reportBytes, evidenceBytes] = await Promise.all([readFile(input.reportPath), readFile(input.evidencePath)]);
  if (reportBytes.byteLength > 2_000_000) throw new Error('report.md exceeds the 2 MB project-sync limit');
  const reportHtml = renderReportMarkdown(reportBytes.toString('utf8'));
  const reportHash = sha256(reportHtml);
  const evidenceHash = sha256(evidenceBytes);
  const evidenceDocument = JSON.parse(evidenceBytes.toString('utf8'));
  const evidence = evidenceRecords(evidenceDocument);
  const byId = new Map(evidence.map((record) => [stableEvidenceId(record), record]));
  let selectedIds = [...byId.keys()];
  if (input.selectionPath) {
    const selection = JSON.parse(await readFile(input.selectionPath, 'utf8'));
    if (selection?.schema_version !== '1.0' || !Array.isArray(selection.evidence_ids) || !selection.evidence_ids.length) throw new Error('Selection JSON must contain schema_version 1.0 and evidence_ids');
    selectedIds = selection.evidence_ids.map(String);
  }
  if (new Set(selectedIds).size !== selectedIds.length) throw new Error('Selection contains duplicate evidence IDs');
  const missing = selectedIds.filter((id) => !byId.has(id));
  if (missing.length) throw new Error(`Selection contains unknown evidence IDs: ${missing.join(', ')}`);
  const metricYear = displayMetricYear(input.searchDate);
  const metricsById = new Map<string, EvidenceMetric>();
  let metricsMissing = 0;
  let metricsPreprintsSkipped = 0;
  for (const id of selectedIds) {
    const record = byId.get(id)!;
    if (isPreprintEvidence(record)) { metricsPreprintsSkipped += 1; continue; }
    const metric = metricFromEvidence(record, evidenceHash);
    if (metric) metricsById.set(id, metric);
    else metricsMissing += 1;
  }
  const enrichment = evidenceDocument?.easyscholar_enrichment;
  const metrics = {
    updated: metricsById.size,
    missing: metricsMissing,
    preprintsSkipped: metricsPreprintsSkipped,
    displayYear: metricYear,
    status: typeof enrichment?.status === 'string' ? enrichment.status : metricsById.size ? 'present-without-summary' : 'not-run',
  };

  let priorityMetadata: ImportPlan['priority'] | undefined;
  const priorityLevels = new Map<string, { level: 1 | 2 | 3; reasons: string[] }>();
  if (input.priorityRecommendationsPath) {
    const bytes = await readFile(input.priorityRecommendationsPath);
    const value = JSON.parse(bytes.toString('utf8'));
    if (value?.schema_version !== '1.0' || value?.artifact_type !== 'literature-priority-recommendations') throw new Error('Unsupported priority recommendations artifact');
    if (value.scope !== input.projectSlug || value.default_for_selected !== 1) throw new Error('Priority recommendations do not match the project scope/default');
    if (!['metadata', 'abstract', 'mixed', 'full-text'].includes(value.review_depth)) throw new Error('Invalid priority review_depth');
    for (const id of selectedIds) priorityLevels.set(id, { level: 1, reasons: [] });
    for (const [id, recommendation] of Object.entries<any>(value.recommendations ?? {})) {
      if (!byId.has(id)) throw new Error(`Priority recommendations contain unknown evidence ID: ${id}`);
      if (![2, 3].includes(recommendation?.priority) || !Array.isArray(recommendation?.reason_codes) || !recommendation.reason_codes.length) throw new Error(`Invalid priority recommendation for ${id}`);
      if (selectedIds.includes(id)) priorityLevels.set(id, { level: recommendation.priority, reasons: recommendation.reason_codes.map(String) });
    }
    priorityMetadata = { source_sha256: sha256(bytes), scope: input.projectSlug, review_depth: value.review_depth, default_for_selected: 1 };
  }

  const statePath = projectStatePath(ctx.config.dataDir, lib, input.projectSlug);
  const state = await readProjectState(statePath);
  const requestedCollectionName = input.collectionName?.trim();
  const collectionName = requestedCollectionName || state?.collection_name;
  if (!collectionName) throw new Error('collection_name is required for the first project sync');
  const collections = await allCollections(ctx, lib);
  const nameMatches = collections.filter((item) => String(dataOf(item).name ?? '') === collectionName);
  const risks: string[] = [];
  let collectionKey: string | undefined;
  if (state) {
    if (requestedCollectionName && requestedCollectionName !== state.collection_name) risks.push('collection-name-conflicts-with-binding');
    const bound = collections.find((item) => keyOf(item) === state.collection_key);
    if (!bound) risks.push('bound-collection-missing');
    else if (String(dataOf(bound).name ?? '') !== collectionName) risks.push('bound-collection-renamed');
    else collectionKey = state.collection_key;
  } else if (nameMatches.length > 1) risks.push('multiple-exact-collection-matches');
  else if (nameMatches.length === 1) collectionKey = keyOf(nameMatches[0]);

  const projectTag = `project:${input.projectSlug}`;
  if (collectionKey) {
    const notes = (await notesInCollection(ctx, lib, collectionKey)).filter((item) => ownedNote(item, projectTag));
    if (notes.length > 1) risks.push('multiple-owned-report-notes');
    else if (state) {
      let note: any;
      try { note = await ctx.web.getItem(lib, state.report_note_key); } catch { risks.push('bound-report-note-missing'); }
      if (note && (notes.length !== 1 || keyOf(note) !== keyOf(notes[0]))) risks.push('bound-report-note-mismatch');
      if (note && sha256(String(dataOf(note).note ?? '')) !== state.report_note_sha256) risks.push('report-note-manually-modified');
    } else if (notes.length === 1 && sha256(String(dataOf(notes[0]).note ?? '')) !== reportHash) risks.push('unbound-existing-report-note');
  }
  if (risks.length) return { status: 'needs_review', collectionName, collectionKey, created: 0, reused: 0, report: 'pending', risks, metrics };

  // A recurring project should not accumulate one search-date tag per run on
  // every previously selected paper. The date remains in the report, plan
  // metadata, state, and private receipt; Zotero membership uses a stable tag.
  const tags = [projectTag];
  const selected = selectedIds.map((id) => ({ id, record: byId.get(id)! }));
  const classified = await actionsFor(ctx, lib, selected, tags);
  for (const action of classified.actions) {
    const metric = metricsById.get(action.evidence_id);
    if (metric && action.item) {
      const extra = mergeMetricIntoExtra(action.item.extra, metricYear, metric);
      if (extra === null) throw new Error(`Unable to create managed metrics Extra for ${action.evidence_id}`);
      action.item.extra = extra;
      action.item.tags = synchronizeCurrentMetricTags(action.item.tags ?? [], extra);
    }
    const priority = priorityLevels.get(action.evidence_id);
    if (!priority) continue;
    const itemTags = action.item?.tags ?? [];
    if (!itemTags.some((entry: any) => entry?.tag === `AI4S:Priority:${priority.level}`)) itemTags.push({ tag: `AI4S:Priority:${priority.level}` });
    action.priority_recommendation = { level: priority.level, reason_codes: priority.reasons, tag_decision: 'add' };
  }
  if (classified.risks.length) return { status: 'needs_review', collectionName, collectionKey, created: 0, reused: 0, report: 'pending', risks: compactEvidenceRisks(classified.risks), metrics };
  const createCount = classified.actions.filter((action) => action.decision === 'create').length;
  const reviewId = sha256(JSON.stringify({ project: input.projectSlug, collection: collectionName, reportHash, evidenceHash, priorityHash: priorityMetadata?.source_sha256 ?? null, selectedIds }));
  if (createCount > LARGE_CREATE_THRESHOLD && input.confirmReviewId !== reviewId) return { status: 'needs_review', collectionName, collectionKey, created: 0, reused: 0, report: 'pending', risks: [`large-create-batch:${createCount}`], reviewId, metrics };

  const plan: ImportPlan = {
    schema_version: '1.0', plan_type: 'zotero-import', created_at: new Date().toISOString(), plan_hash: '',
    project: { slug: input.projectSlug, search_date: input.searchDate },
    target: { library_type: lib.type, library_id: lib.id, collection_name: collectionName, tags },
    matching: { mode: 'local-api', source_library_version: null, candidate_limit: 50, unchecked_create: false },
    actions: classified.actions, ...(priorityMetadata ? { priority: priorityMetadata } : {}),
    summary: { selected: classified.actions.length, create: createCount, reuse: classified.actions.filter((action) => action.decision === 'reuse').length, check: 0, skip: 0 },
  };
  plan.plan_hash = canonicalPlanHash(plan);
  const dryRun = await dryRunImportPlan(ctx, plan, lib);
  if (dryRun.status !== 'ready') return { status: 'needs_review', collectionName, collectionKey, created: 0, reused: 0, report: 'pending', risks: compactEvidenceRisks(dryRun.blockingIssues), metrics };
  const applied = await applyImportPlan(ctx, plan, lib, projectReceiptPath(ctx.config.dataDir, lib, input.projectSlug, plan.plan_hash));
  collectionKey = applied.collectionKey ?? collectionKey;
  if (!collectionKey || applied.status === 'blocked') return { status: 'blocked', collectionName, collectionKey, created: applied.summary.created ?? 0, reused: applied.summary.reused ?? 0, report: 'pending', risks: applied.blockingIssues, metrics };

  let note: any = null;
  if (state) note = await ctx.web.getItem(lib, state.report_note_key);
  else {
    const notes = (await notesInCollection(ctx, lib, collectionKey)).filter((item) => ownedNote(item, projectTag));
    if (notes.length === 1) note = notes[0];
  }
  let report: ProjectSyncResult['report'] = 'unchanged';
  let noteKey = keyOf(note);
  let noteVersion = versionOf(note);
  if (!note) {
    const written = await ctx.web.writeItems(lib, [{ itemType: 'note', note: reportHtml, tags: [{ tag: REPORT_TAG }, { tag: projectTag }], collections: [collectionKey] }]);
    if (written.failed.length || !written.successful[0]?.key) throw new Error(`Report Note creation failed: ${JSON.stringify(written.failed)}`);
    noteKey = written.successful[0].key; noteVersion = written.successful[0].version ?? null; report = 'created';
  } else if (!state || state.report_sha256 !== reportHash) {
    if (noteVersion === null) throw new Error('Report Note has no Zotero version');
    noteVersion = await ctx.web.patchItem(lib, noteKey, { note: reportHtml }, noteVersion); report = 'updated';
  }
  const savedNote = await ctx.web.getItem(lib, noteKey);
  noteVersion = versionOf(savedNote);
  const nextState: ProjectSyncState = {
    schema_version: '1.0', project_slug: input.projectSlug, library: lib, collection_name: collectionName, collection_key: collectionKey,
    report_note_key: noteKey, report_note_version: noteVersion, report_sha256: reportHash,
    report_note_sha256: sha256(String(dataOf(savedNote).note ?? '')), evidence_sha256: evidenceHash,
    synced_evidence_ids: [...selectedIds].sort(), updated_at: new Date().toISOString(),
  };
  await writeProjectState(statePath, nextState);
  return { status: 'complete', collectionName, collectionKey, created: applied.summary.created ?? 0, reused: applied.summary.reused ?? 0, report, risks: [], metrics };
}
