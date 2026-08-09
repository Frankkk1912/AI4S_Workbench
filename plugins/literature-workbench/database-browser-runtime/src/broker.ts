import { randomUUID } from 'node:crypto';
import { readFile, stat } from 'node:fs/promises';
import { isAbsolute, relative, resolve } from 'node:path';
import type {
  BrokerIndex,
  BrowserAdapter,
  ExportInput,
  Filters,
  JobPhase,
  JobRecord,
  JobState,
  SearchInput,
  SessionSnapshot,
  VerifiedExportFile,
} from './domain.js';
import { DATABASE_ID, TERMINAL_JOB_STATES } from './domain.js';
import { BrokerError, asBrokerError } from './errors.js';
import { canonicalJson, sha256 } from './lib/canonical.js';
import { JobStore } from './store.js';

function timestamp(): string {
  return new Date().toISOString();
}

function jobId(): string {
  return `job-${randomUUID()}`;
}

function sameFilters(left: Filters | undefined, right: Filters | undefined): boolean {
  return canonicalJson(left ?? {}) === canonicalJson(right ?? {});
}

function searchFingerprint(input: SearchInput): string {
  return sha256(canonicalJson({ ...input, requestId: undefined }));
}

function exportFingerprint(input: ExportInput): string {
  return sha256(canonicalJson({ ...input, requestId: undefined }));
}

function userActionMessage(session: SessionSnapshot): string {
  return session.message || 'Continue in the visible WoS browser, then call database_session_open again.';
}

export class DatabaseBroker {
  private index: BrokerIndex | undefined;
  private mutation = Promise.resolve();

  constructor(
    private readonly store: JobStore,
    private readonly adapter: BrowserAdapter,
  ) {}

  async init(): Promise<void> {
    if (this.index) return;
    this.index = await this.store.init();
    const [persistedJobs, adapterSession] = await Promise.all([
      this.store.listJobs(),
      this.adapter.sessionStatus().catch(() => this.index!.session),
    ]);

    this.index.session = adapterSession;
    for (const job of persistedJobs) {
      if (TERMINAL_JOB_STATES.has(job.state) || job.state === 'results_ready') continue;
      job.state = 'stale';
      job.message = 'Broker restarted before this browser action could be verified. Submit a new request after checking the session.';
      job.updatedAt = timestamp();
      job.timeline.push({ at: job.updatedAt, phase: job.phase, state: 'stale', message: job.message });
      await this.store.saveJob(job);
    }
    await this.store.saveIndex(this.index);
  }

  capabilities(): Record<string, unknown> {
    return {
      schema_version: 1,
      supported_databases: [{
        id: DATABASE_ID,
        display_name: 'Web of Science Core Collection',
        access_mode: 'campus-ip-visible-browser',
        query_modes: ['advanced-search'],
        filters: ['year-range', 'document-types'],
        sorts: ['relevance', 'date-desc', 'citations-desc'],
        export_formats: ['tab-delimited-full-record'],
        max_export_records: 1000,
      }],
    };
  }

  async openSession(): Promise<SessionSnapshot> {
    await this.init();
    const session = await this.adapter.openSession();
    await this.setSession(session);
    return session;
  }

  async sessionStatus(): Promise<SessionSnapshot> {
    await this.init();
    const session = await this.adapter.sessionStatus();
    await this.setSession(session);
    return session;
  }

  async submitSearch(input: SearchInput): Promise<{ jobId: string; reused: boolean }> {
    await this.init();
    const fingerprint = searchFingerprint(input);
    return this.withIndex(async (index) => {
      const existing = index.requestIds[input.requestId];
      if (existing) {
        if (existing.operation !== 'search' || existing.fingerprint !== fingerprint) {
          throw new BrokerError('REQUEST_ID_CONFLICT', 'This request_id is already bound to a different search request.');
        }
        return { jobId: existing.jobId, reused: true };
      }
      const at = timestamp();
      const id = jobId();
      const queryHash = sha256(input.query.value);
      const job: JobRecord = {
        schemaVersion: 1,
        jobId: id,
        database: DATABASE_ID,
        attemptId: input.attemptId,
        phase: 'queued',
        state: 'queued',
        createdAt: at,
        updatedAt: at,
        search: {
          database: input.database,
          attemptId: input.attemptId,
          query: input.query,
          ...(input.filters ? { filters: input.filters } : {}),
          ...(input.sort ? { sort: input.sort } : {}),
          requestId: input.requestId,
          queryHash,
        },
        userActionRequired: false,
        timeline: [{ at, phase: 'queued', state: 'queued', message: 'Search job accepted.' }],
      };
      await this.store.createJob(job);
      index.requestIds[input.requestId] = { fingerprint, jobId: id, operation: 'search' };
      await this.store.saveIndex(index);
      queueMicrotask(() => void this.runSearch(id));
      return { jobId: id, reused: false };
    });
  }

  async submitExport(input: ExportInput): Promise<{ jobId: string; reused: boolean }> {
    await this.init();
    const fingerprint = exportFingerprint(input);
    return this.withIndex(async (index) => {
      const existing = index.requestIds[input.requestId];
      if (existing) {
        if (existing.operation !== 'export' || existing.fingerprint !== fingerprint) {
          throw new BrokerError('REQUEST_ID_CONFLICT', 'This request_id is already bound to a different export request.');
        }
        return { jobId: existing.jobId, reused: true };
      }
      const job = await this.requireJob(input.jobId);
      if (job.state !== 'results_ready' || job.phase !== 'results_ready') {
        throw new BrokerError('JOB_NOT_EXPORTABLE', 'Only a verified results_ready search job can be exported.');
      }
      job.export = { limit: input.limit, format: input.format, requestId: input.requestId };
      await this.store.saveJob(job);
      await this.transition(job, 'export_queued', 'queued', 'Export job accepted.');
      index.requestIds[input.requestId] = { fingerprint, jobId: job.jobId, operation: 'export' };
      await this.store.saveIndex(index);
      queueMicrotask(() => void this.runExport(job.jobId));
      return { jobId: job.jobId, reused: false };
    });
  }

  async status(jobIdValue: string): Promise<Record<string, unknown>> {
    await this.init();
    const job = await this.requireJob(jobIdValue);
    const base: Record<string, unknown> = {
      job_id: job.jobId,
      attempt_id: job.attemptId,
      phase: job.phase === 'complete' ? 'export' : job.export ? 'export' : 'search',
      state: job.state,
      user_action_required: job.userActionRequired,
    };
    if (job.reportedResultCount !== undefined) {
      base.reported_result_count = job.reportedResultCount;
      base.applied_filters = job.appliedFilters ?? {};
      base.sort = job.appliedSort ?? 'relevance';
      base.can_export = job.state === 'results_ready' && job.phase === 'results_ready';
    }
    if (job.errorCode) base.error_code = job.errorCode;
    if (job.message) base.message = job.message;
    if (job.state === 'complete') {
      base.requested_export_limit = job.export?.limit;
      base.exported_record_count = job.exportedRecordCount;
      base.export_files = job.exportFiles?.map((file) => file.path) ?? [];
      base.receipt_file = this.store.receiptPath(job.jobId);
      base.next_step = { owner: 'literature-research-cli', command: 'import-wos-export' };
    }
    return base;
  }

  async cancel(jobIdValue: string): Promise<Record<string, unknown>> {
    await this.init();
    const job = await this.requireJob(jobIdValue);
    if (!TERMINAL_JOB_STATES.has(job.state)) {
      await this.transition(job, job.phase, 'canceled', 'Job canceled by request.');
      await this.adapter.cancel?.(job.jobId);
    }
    return { job_id: job.jobId, state: 'canceled', canceled: true };
  }

  private async runSearch(jobIdValue: string): Promise<void> {
    try {
      let job = await this.requireJob(jobIdValue);
      job = await this.transition(job, 'starting_session', 'running', 'Opening or reusing the visible WoS session.');
      const session = await this.openSession();
      if (session.sessionState !== 'ready') {
        await this.transition(
          job,
          'starting_session',
          'user_action_required',
          userActionMessage(session),
          session.errorCode,
          true,
        );
        return;
      }
      job = await this.transition(job, 'navigating', 'running', 'Opening the WoS Advanced Search form.');
      job = await this.transition(job, 'search_form_ready', 'running', 'Advanced Search form is ready.');
      job = await this.transition(job, 'query_committed', 'running', 'Query value was committed and read back.');
      job = await this.transition(job, 'search_submitted', 'running', 'Search submission was accepted by the page.');
      job = await this.transition(job, 'waiting_results', 'running', 'Waiting for a verified results state.');
      const result = await this.adapter.executeSearch({
        database: job.search.database,
        attemptId: job.search.attemptId,
        query: job.search.query,
        ...(job.search.filters ? { filters: job.search.filters } : {}),
        ...(job.search.sort ? { sort: job.search.sort } : {}),
        requestId: job.search.requestId,
      });
      if (!sameFilters(job.search.filters, result.appliedFilters)) {
        throw new BrokerError('FILTER_NOT_APPLIED', 'The page did not verify the requested filters.');
      }
      if ((job.search.sort ?? 'relevance') !== result.appliedSort) {
        throw new BrokerError('FILTER_NOT_APPLIED', 'The page did not verify the requested sort order.');
      }
      job = await this.transition(job, 'applying_filters', 'running', 'Requested filters and sort were verified.');
      if ((await this.requireJob(job.jobId)).state === 'canceled') return;
      job.reportedResultCount = result.reportedResultCount;
      job.appliedFilters = result.appliedFilters;
      job.appliedSort = result.appliedSort;
      await this.store.saveJob(job);
      job = await this.transition(job, 'results_ready', 'results_ready', 'Search results and result count were verified.');
      await this.store.saveReceipt(job);
    } catch (error) {
      await this.fail(jobIdValue, error);
    }
  }

  private async runExport(jobIdValue: string): Promise<void> {
    try {
      let job = await this.requireJob(jobIdValue);
      const exportOptions = job.export;
      if (!exportOptions) throw new BrokerError('JOB_NOT_EXPORTABLE', 'Export options are missing.');
      job = await this.transition(job, 'exporting', 'running', 'Starting official WoS export.');
      const input: ExportInput = { jobId: job.jobId, ...exportOptions };
      const execution = await this.adapter.executeExport(input, this.store.exportsDir(job.jobId));
      job = await this.transition(job, 'verifying_download', 'running', 'Verifying downloaded official export files.');
      const files = await this.validateExport(job, execution.artifacts);
      if ((await this.requireJob(job.jobId)).state === 'canceled') return;
      job.exportFiles = files;
      job.exportedRecordCount = files.reduce((sum, file) => sum + file.rangeEnd - file.rangeStart + 1, 0);
      await this.store.saveJob(job);
      job = await this.transition(job, 'complete', 'complete', 'Official export files were validated.');
      await this.store.saveReceipt(job);
    } catch (error) {
      await this.fail(jobIdValue, error);
    }
  }

  private async validateExport(job: JobRecord, artifacts: Array<{ path: string; rangeStart: number; rangeEnd: number }>): Promise<VerifiedExportFile[]> {
    if (!job.export || artifacts.length === 0) {
      throw new BrokerError('DOWNLOAD_INVALID', 'The export did not produce any downloadable files.');
    }
    const files = await Promise.all(artifacts.map((artifact) => this.validateFile(job.jobId, artifact)));
    const ordered = [...files].sort((left, right) => left.rangeStart - right.rangeStart);
    let expectedStart = 1;
    for (const file of ordered) {
      if (file.rangeStart !== expectedStart || file.rangeEnd < file.rangeStart) {
        throw new BrokerError('DOWNLOAD_INVALID', 'Downloaded export batch ranges are not continuous.');
      }
      expectedStart = file.rangeEnd + 1;
    }
    const expectedRecords = Math.min(job.export.limit, job.reportedResultCount ?? 0);
    if (expectedStart - 1 !== expectedRecords) {
      throw new BrokerError('DOWNLOAD_INVALID', 'Downloaded export batch ranges do not match the verified export count.');
    }
    return ordered;
  }

  private async validateFile(
    jobIdValue: string,
    artifact: { path: string; rangeStart: number; rangeEnd: number },
  ): Promise<VerifiedExportFile> {
    const exportDirectory = resolve(this.store.exportsDir(jobIdValue));
    const filePath = resolve(artifact.path);
    const relativePath = relative(exportDirectory, filePath);
    if (!relativePath || relativePath.startsWith('..') || isAbsolute(relativePath)) {
      throw new BrokerError('DOWNLOAD_INVALID', 'An export file was written outside this job\'s private export directory.');
    }
    const info = await stat(filePath);
    if (!info.isFile() || info.size < 8) {
      throw new BrokerError('DOWNLOAD_INVALID', 'An export file is missing or empty.');
    }
    const contents = await readFile(filePath);
    const text = contents.toString('utf8');
    const lines = text.split(/\r?\n/).filter((line) => line.trim().length > 0);
    const header = (lines[0] ?? '').replace(/^\uFEFF/, '').split('\t').map((field) => field.trim().toLowerCase());
    const hasTitle = header.some((field) => ['article title', 'title', 'ti'].includes(field));
    const hasIdentifier = header.some((field) => ['ut', 'ut (unique wos id)', 'doi', 'di'].includes(field));
    if (header.length < 2 || !hasTitle || !hasIdentifier) {
      throw new BrokerError('DOWNLOAD_INVALID', 'An export file does not have a recognized tab-delimited WoS full-record header.');
    }
    return {
      ...artifact,
      path: filePath,
      sha256: sha256(contents),
      bytes: info.size,
      validatedRows: Math.max(0, lines.length - 1),
    };
  }

  private async fail(jobIdValue: string, error: unknown): Promise<void> {
    const brokerError = asBrokerError(error);
    const job = await this.store.loadJob(jobIdValue);
    if (!job || job.state === 'canceled') return;
    const userActionRequired = brokerError.userActionRequired || ['AUTH_REQUIRED', 'CAMPUS_ACCESS_REQUIRED', 'CAPTCHA_OR_CHALLENGE'].includes(brokerError.code);
    const failed = await this.transition(
      job,
      job.phase,
      userActionRequired ? 'user_action_required' : 'failed',
      brokerError.message,
      brokerError.code,
      userActionRequired,
    );
    await this.store.saveReceipt(failed);
  }

  private async transition(
    job: JobRecord,
    phase: JobPhase,
    state: JobState,
    message: string,
    errorCode?: JobRecord['errorCode'],
    userActionRequired = false,
  ): Promise<JobRecord> {
    const current = await this.requireJob(job.jobId);
    if (current.state === 'canceled') return current;
    const at = timestamp();
    current.phase = phase;
    current.state = state;
    current.updatedAt = at;
    current.message = message;
    current.errorCode = errorCode;
    current.userActionRequired = userActionRequired;
    current.timeline.push({ at, phase, state, message });
    await this.store.saveJob(current);
    return current;
  }

  private async requireJob(jobIdValue: string): Promise<JobRecord> {
    const job = await this.store.loadJob(jobIdValue);
    if (!job) throw new BrokerError('JOB_NOT_FOUND', `No job exists with id ${jobIdValue}.`);
    return job;
  }

  private async setSession(session: SessionSnapshot): Promise<void> {
    await this.withIndex(async (index) => {
      index.session = session;
      await this.store.saveIndex(index);
    });
  }

  private async withIndex<T>(operation: (index: BrokerIndex) => Promise<T>): Promise<T> {
    const previous = this.mutation;
    let release: (() => void) | undefined;
    this.mutation = new Promise<void>((resolveRelease) => {
      release = resolveRelease;
    });
    await previous;
    try {
      if (!this.index) throw new Error('Broker was not initialized.');
      return await operation(this.index);
    } finally {
      release?.();
    }
  }
}
