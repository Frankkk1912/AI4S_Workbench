export const DATABASE_ID = 'wos-core-collection' as const;
export const EXPORT_FORMAT = 'tab-delimited-full-record' as const;

export type SessionState =
  | 'closed'
  | 'starting'
  | 'ready'
  | 'auth_required'
  | 'manual_intervention_required'
  | 'unavailable'
  | 'stale';

export type JobPhase =
  | 'queued'
  | 'starting_session'
  | 'navigating'
  | 'search_form_ready'
  | 'query_committed'
  | 'search_submitted'
  | 'waiting_results'
  | 'applying_filters'
  | 'results_ready'
  | 'export_queued'
  | 'exporting'
  | 'verifying_download'
  | 'complete';

export type JobState =
  | 'queued'
  | 'running'
  | 'results_ready'
  | 'complete'
  | 'user_action_required'
  | 'retrying'
  | 'failed'
  | 'canceled'
  | 'stale';

export type ErrorCode =
  | 'CAMPUS_ACCESS_REQUIRED'
  | 'AUTH_REQUIRED'
  | 'CAPTCHA_OR_CHALLENGE'
  | 'PAGE_CONTRACT_CHANGED'
  | 'QUERY_NOT_COMMITTED'
  | 'RESULTS_NOT_VERIFIED'
  | 'FILTER_NOT_APPLIED'
  | 'EXPORT_LIMIT_REJECTED'
  | 'DOWNLOAD_INVALID'
  | 'BROWSER_CLOSED'
  | 'REQUEST_ID_CONFLICT'
  | 'JOB_NOT_EXPORTABLE'
  | 'JOB_NOT_FOUND';

export interface Filters {
  fromYear?: number;
  untilYear?: number;
  documentTypes?: string[];
}

export interface SearchInput {
  database: typeof DATABASE_ID;
  attemptId: string;
  query: {
    mode: 'advanced-search';
    value: string;
  };
  filters?: Filters;
  sort?: 'relevance' | 'date-desc' | 'citations-desc';
  requestId: string;
}

export interface ExportInput {
  jobId: string;
  limit: number;
  format: typeof EXPORT_FORMAT;
  requestId: string;
}

export interface TimelineEntry {
  at: string;
  phase: JobPhase;
  state: JobState;
  message?: string;
}

export interface ExportArtifact {
  path: string;
  rangeStart: number;
  rangeEnd: number;
}

export interface VerifiedExportFile extends ExportArtifact {
  sha256: string;
  bytes: number;
  validatedRows: number;
}

export interface JobRecord {
  schemaVersion: 1;
  jobId: string;
  database: typeof DATABASE_ID;
  attemptId: string;
  phase: JobPhase;
  state: JobState;
  createdAt: string;
  updatedAt: string;
  search: Omit<SearchInput, 'requestId'> & { queryHash: string; requestId: string };
  reportedResultCount?: number;
  appliedFilters?: Filters;
  appliedSort?: 'relevance' | 'date-desc' | 'citations-desc';
  export?: Omit<ExportInput, 'jobId'>;
  exportedRecordCount?: number;
  exportFiles?: VerifiedExportFile[];
  errorCode?: ErrorCode;
  userActionRequired: boolean;
  message?: string;
  timeline: TimelineEntry[];
}

export interface SessionSnapshot {
  database: typeof DATABASE_ID;
  sessionState: SessionState;
  userActionRequired: boolean;
  message: string;
  errorCode?: ErrorCode;
  updatedAt: string;
}

export interface SearchExecutionResult {
  reportedResultCount: number;
  appliedFilters: Filters;
  appliedSort: 'relevance' | 'date-desc' | 'citations-desc';
}

export interface ExportExecutionResult {
  artifacts: ExportArtifact[];
}

export interface BrowserAdapter {
  openSession(): Promise<SessionSnapshot>;
  sessionStatus(): Promise<SessionSnapshot>;
  executeSearch(input: SearchInput): Promise<SearchExecutionResult>;
  executeExport(input: ExportInput, exportDirectory: string): Promise<ExportExecutionResult>;
  cancel?(jobId: string): Promise<void>;
  close?(): Promise<void>;
}

export interface BrokerIndex {
  schemaVersion: 1;
  session: SessionSnapshot;
  requestIds: Record<string, { fingerprint: string; jobId: string; operation: 'search' | 'export' }>;
}

export const TERMINAL_JOB_STATES = new Set<JobState>(['complete', 'failed', 'canceled']);
