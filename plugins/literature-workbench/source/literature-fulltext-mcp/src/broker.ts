import { randomUUID } from 'node:crypto';
import { asFulltextError, FulltextError } from './errors.js';
import { canonicalJson, sha256 } from './lib/canonical.js';
import type {
  BrokerIndex, Candidate, FetchRequest, FulltextAdapter, JobRecord, JobState, PdfVerification, RecordState, VerifiedRecord,
} from './domain.js';
import { TERMINAL_JOB_STATES } from './domain.js';
import { FulltextStore } from './store.js';
import { verifyPdf } from './verification.js';

type PdfVerifier = (bytes: Uint8Array, target: { doi: string; title: string }) => Promise<PdfVerification>;

function now(): string { return new Date().toISOString(); }
function jobId(): string { return `ft-${randomUUID()}`; }
function handoffId(): string { return `fth-${randomUUID()}`; }
function normalizeDoi(value: string): string { return value.trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, '').replace(/^doi:\s*/i, '').replace(/[\s.]+$/u, '').toLowerCase(); }
function requestFingerprint(input: FetchRequest): string { return sha256(canonicalJson(input)); }

function summary(job: JobRecord): Record<string, number> {
  const count = (predicate: (state: RecordState) => boolean) => job.records.filter((record) => predicate(record.state)).length;
  return {
    requested: job.records.length,
    verified: count((state) => state === 'verified'),
    auth_required: count((state) => state === 'auth_required'),
    unavailable: count((state) => ['unavailable', 'not_entitled', 'unverified'].includes(state)),
    failed: count((state) => state === 'failed'),
    canceled: count((state) => state === 'canceled'),
  };
}

export class FulltextBroker {
  private index: BrokerIndex | undefined;
  private mutation = Promise.resolve();

  constructor(
    private readonly store: FulltextStore,
    private readonly adapter: FulltextAdapter,
    private readonly verifier: PdfVerifier = verifyPdf,
  ) {}

  async init(): Promise<void> {
    if (this.index) return;
    this.index = await this.store.init();
    for (const job of await this.store.listJobs()) {
      if (TERMINAL_JOB_STATES.has(job.state)) continue;
      job.state = 'stale';
      job.updatedAt = now();
      job.message = 'Fulltext MCP restarted before this job completed. Submit a new request after reviewing its compact result.';
      job.userActionRequired = false;
      for (const record of job.records) if (!['verified', 'unavailable', 'failed', 'canceled'].includes(record.state)) record.state = 'failed';
      await this.store.saveJob(job);
      await this.store.saveJobReceipt(job);
    }
  }

  capabilities(): Record<string, unknown> {
    return {
      schema_version: 1,
      providers: this.adapter.providerNames(),
      access_modes: ['open_access_http'],
      institutional_browser_available: false,
      max_records_per_job: 50,
      pdf_validation: 'pdfjs-parse-plus-doi-and-title-match',
    };
  }

  accessStatus(): Record<string, unknown> {
    return {
      state: 'oa_only_ready',
      institutional_browser_available: false,
      message: 'OA HTTP retrieval is ready. Institutional browser fallback is not installed in this runtime.',
    };
  }

  async submit(input: FetchRequest): Promise<{ jobId: string; reused: boolean }> {
    await this.init();
    const fingerprint = requestFingerprint(input);
    return this.withIndex(async (index) => {
      const existing = index.requestIds[input.requestId];
      if (existing) {
        if (existing.fingerprint !== fingerprint) throw new FulltextError('REQUEST_ID_CONFLICT', 'This request_id is already bound to a different fulltext request.');
        return { jobId: existing.jobId, reused: true };
      }
      const timestamp = now();
      const id = jobId();
      const job: JobRecord = {
        schemaVersion: 1, jobId: id, request: structuredClone(input), state: 'queued', createdAt: timestamp, updatedAt: timestamp,
        userActionRequired: false,
        records: input.records.map((record) => ({ evidenceId: record.evidenceId, zoteroItemKey: record.zoteroItemKey, state: 'queued' })),
      };
      await this.store.createJob(job);
      index.requestIds[input.requestId] = { fingerprint, jobId: id };
      await this.store.saveIndex(index);
      queueMicrotask(() => void this.run(id));
      return { jobId: id, reused: false };
    });
  }

  async status(id: string): Promise<Record<string, unknown>> {
    await this.init();
    const job = await this.requireJob(id);
    const status: Record<string, unknown> = {
      job_id: job.jobId,
      state: job.state,
      counts: summary(job),
      user_action_required: job.userActionRequired,
      next_action: job.userActionRequired ? 'Complete the required action in the visible browser.' : null,
      handoff_id: job.handoffId ?? null,
      handoff_hash: job.handoffHash ?? null,
    };
    if (job.message) status.message = job.message;
    status.records = job.records.map((record) => ({
      evidence_id: record.evidenceId, zotero_item_key: record.zoteroItemKey,
      state: record.state, ...(record.errorCode ? { error_code: record.errorCode } : {}),
    }));
    return status;
  }

  async cancel(id: string): Promise<Record<string, unknown>> {
    await this.init();
    const job = await this.requireJob(id);
    if (!TERMINAL_JOB_STATES.has(job.state)) {
      job.state = 'canceled';
      job.updatedAt = now();
      job.message = 'Job canceled by request; no handoff will be generated.';
      for (const record of job.records) if (!['verified', 'unavailable', 'failed'].includes(record.state)) record.state = 'canceled';
      await this.store.saveJob(job);
      await this.store.saveJobReceipt(job);
    }
    return { job_id: job.jobId, state: 'canceled', canceled: true };
  }

  private async run(id: string): Promise<void> {
    try {
      let job = await this.transition(id, 'resolving_open_access', 'Resolving legal OA candidates.');
      for (const record of job.request.records) {
        if ((await this.requireJob(id)).state === 'canceled') return;
        job = await this.setRecord(id, record.evidenceId, 'resolving');
        if (!record.doi) {
          job = await this.setRecord(id, record.evidenceId, 'unavailable', 'ZOTERO_PARENT_DOI_REQUIRED', 'This initial attachment workflow requires an exact parent DOI.');
          continue;
        }
        const candidates = await this.adapter.resolveCandidates(record);
        if (!candidates.length) {
          job = await this.setRecord(id, record.evidenceId, 'unavailable', 'NO_OPEN_ACCESS_COPY', 'No legal OA candidate was found.');
          continue;
        }
        let accepted = false;
        let lastError: FulltextError | undefined;
        for (const candidate of candidates) {
          if ((await this.requireJob(id)).state === 'canceled') return;
          if (candidate.fileRole !== 'main_article') {
            lastError = new FulltextError('MAIN_ARTICLE_NOT_VERIFIED', 'Candidate appears to be supplementary, correction, or non-article material.');
            continue;
          }
          await this.setRecord(id, record.evidenceId, 'candidate_found');
          try {
            await this.setRecord(id, record.evidenceId, 'downloading');
            const download = await this.adapter.download(candidate);
            await this.transition(id, 'validating_oa_candidates', 'Validating downloaded PDF artifacts.');
            await this.setRecord(id, record.evidenceId, 'validating');
            const verification = await this.verifier(download.bytes, { doi: record.doi, title: record.title });
            if (verification.level !== 'strong_identifier' || !verification.doiMatch || !verification.titleMatch) {
              lastError = new FulltextError(
                verification.doiMatch ? 'MAIN_ARTICLE_NOT_VERIFIED' : 'IDENTITY_MISMATCH',
                'PDF did not provide a strong DOI-and-title match for the selected parent.',
              );
              continue;
            }
            await this.store.writeArtifact(verification.sha256, download.bytes);
            const verified: VerifiedRecord = {
              evidenceId: record.evidenceId, zoteroItemKey: record.zoteroItemKey, doi: normalizeDoi(record.doi), title: record.title,
              candidate, verification,
            };
            job = await this.setRecord(id, record.evidenceId, 'verified', undefined, undefined, verified);
            accepted = true;
            break;
          } catch (error) {
            lastError = asFulltextError(error);
            if (lastError.code === 'RATE_LIMITED') break;
          }
        }
        if (!accepted) {
          const code = lastError?.code ?? 'NO_OPEN_ACCESS_COPY';
          const state: RecordState = ['IDENTITY_MISMATCH', 'MAIN_ARTICLE_NOT_VERIFIED', 'DOWNLOAD_NOT_PDF', 'PDF_INVALID'].includes(code)
            ? 'unverified' : 'unavailable';
          job = await this.setRecord(id, record.evidenceId, state, code, lastError?.message ?? 'No legal OA PDF was verified.');
        }
      }
      if ((await this.requireJob(id)).state === 'canceled') return;
      const verified = (await this.requireJob(id)).records.flatMap((record) => record.verified ? [record.verified] : []);
      if (!verified.length) {
        await this.finish(id, 'failed', 'No selected record produced a verified OA main-article PDF.');
        return;
      }
      await this.transition(id, 'building_handoff', 'Building immutable fulltext handoff.');
      const handoff = this.makeHandoff(await this.requireJob(id), verified);
      await this.store.writeHandoff(handoff);
      const finalState: JobState = verified.length === (await this.requireJob(id)).records.length ? 'complete' : 'partial';
      await this.finish(id, finalState, `Verified ${verified.length} OA main-article PDF(s).`, handoff.handoff_id, handoff.handoff_hash);
    } catch (error) {
      const fulltextError = asFulltextError(error);
      const job = await this.store.loadJob(id);
      if (!job || job.state === 'canceled') return;
      await this.finish(id, 'failed', fulltextError.message);
    }
  }

  private makeHandoff(job: JobRecord, verified: VerifiedRecord[]): Record<string, unknown> & { handoff_id: string; handoff_hash: string } {
    const base: Record<string, unknown> = {
      schema_version: 1,
      handoff_id: handoffId(),
      job_id: job.jobId,
      request_id: job.request.requestId,
      created_at: now(),
      records: verified.map((record) => ({
        evidence_id: record.evidenceId,
        zotero_item_key: record.zoteroItemKey,
        expected_parent: { doi: record.doi, title: record.title },
        retrieval: {
          status: 'verified', provider: record.candidate.provider, access_mode: record.candidate.accessMode,
          document_version: record.candidate.documentVersion, file_role: 'main_article', retrieved_at: now(),
        },
        artifact: {
          artifact_id: `sha256:${record.verification.sha256}`, sha256: record.verification.sha256,
          md5: record.verification.md5, bytes: record.verification.bytes,
          content_type: 'application/pdf', page_count: record.verification.pageCount,
        },
        verification: { level: 'strong_identifier', doi_match: true, title_match: true },
      })),
    };
    const handoffHash = `sha256:${sha256(canonicalJson(base))}`;
    return { ...base, handoff_hash: handoffHash } as Record<string, unknown> & { handoff_id: string; handoff_hash: string };
  }

  private async finish(id: string, state: JobState, message: string, handoffIdValue?: string, handoffHash?: string): Promise<void> {
    const job = await this.requireJob(id);
    if (job.state === 'canceled') return;
    job.state = state;
    job.updatedAt = now();
    job.message = message;
    job.userActionRequired = false;
    if (handoffIdValue && handoffHash) { job.handoffId = handoffIdValue; job.handoffHash = handoffHash; }
    await this.store.saveJob(job);
    await this.store.saveJobReceipt(job);
  }

  private async transition(id: string, state: JobState, message: string): Promise<JobRecord> {
    const job = await this.requireJob(id);
    if (job.state === 'canceled') return job;
    job.state = state;
    job.updatedAt = now();
    job.message = message;
    await this.store.saveJob(job);
    return job;
  }

  private async setRecord(
    id: string, evidenceId: string, state: RecordState, errorCode?: JobRecord['records'][number]['errorCode'], message?: string, verified?: VerifiedRecord,
  ): Promise<JobRecord> {
    const job = await this.requireJob(id);
    if (job.state === 'canceled') return job;
    const record = job.records.find((entry) => entry.evidenceId === evidenceId);
    if (!record) throw new Error(`Missing record ${evidenceId} in job ${id}.`);
    record.state = state;
    record.errorCode = errorCode;
    record.message = message;
    if (verified) record.verified = verified;
    job.updatedAt = now();
    await this.store.saveJob(job);
    return job;
  }

  private async requireJob(id: string): Promise<JobRecord> {
    const job = await this.store.loadJob(id);
    if (!job) throw new FulltextError('JOB_NOT_FOUND', `No fulltext job exists with id ${id}.`);
    return job;
  }

  private async withIndex<T>(operation: (index: BrokerIndex) => Promise<T>): Promise<T> {
    const previous = this.mutation;
    let release: (() => void) | undefined;
    this.mutation = new Promise<void>((resolve) => { release = resolve; });
    await previous;
    try {
      if (!this.index) throw new Error('Broker was not initialized.');
      return await operation(this.index);
    } finally { release?.(); }
  }
}
