export type RoutePolicy = 'oa_only' | 'oa_then_current_entitlement' | 'oa_then_institutional';
export type DocumentVersion = 'version_of_record' | 'accepted_manuscript' | 'submitted_manuscript' | 'preprint' | 'unknown';
export type FileRole = 'main_article' | 'supplement' | 'correction' | 'editorial_or_cover' | 'unknown';

export type RecordState =
  | 'queued' | 'resolving' | 'candidate_found' | 'downloading' | 'validating'
  | 'verified' | 'unverified' | 'auth_required' | 'not_entitled' | 'unavailable'
  | 'failed' | 'canceled';

export type JobState =
  | 'queued' | 'resolving_open_access' | 'validating_oa_candidates' | 'building_handoff'
  | 'complete' | 'partial' | 'auth_required' | 'retrying' | 'failed' | 'canceled' | 'stale';

export type ErrorCode =
  | 'NO_STABLE_IDENTIFIER' | 'NO_OPEN_ACCESS_COPY' | 'INSTITUTION_ACCESS_UNAVAILABLE'
  | 'AUTH_REQUIRED' | 'CAPTCHA_OR_CHALLENGE' | 'RATE_LIMITED' | 'PUBLISHER_ROUTE_CHANGED'
  | 'DOWNLOAD_NOT_PDF' | 'PDF_INVALID' | 'IDENTITY_MISMATCH' | 'MAIN_ARTICLE_NOT_VERIFIED'
  | 'REQUEST_ID_CONFLICT' | 'JOB_NOT_FOUND' | 'UNSAFE_DOWNLOAD_URL' | 'DOWNLOAD_TOO_LARGE'
  | 'ZOTERO_PARENT_DOI_REQUIRED';

export interface FetchRecord {
  evidenceId: string;
  zoteroItemKey: string;
  doi?: string;
  arxivId?: string;
  repositoryId?: string;
  title: string;
  year?: number;
  itemType: string;
  candidateUrls: string[];
}

export interface FetchRequest {
  requestId: string;
  routePolicy: RoutePolicy;
  records: FetchRecord[];
}

export interface Candidate {
  provider: 'pmc' | 'candidate-oa-url';
  url: string;
  accessMode: 'open_access_http' | 'publisher_open_access';
  documentVersion: DocumentVersion;
  fileRole: FileRole;
}

export interface DownloadedPdf {
  bytes: Uint8Array;
  contentType: string | null;
}

export interface PdfVerification {
  sha256: string;
  md5: string;
  bytes: number;
  pageCount: number;
  level: 'strong_identifier' | 'strong_context' | 'weak_title' | 'unverified' | 'mismatch';
  doiMatch: boolean;
  titleMatch: boolean;
}

export interface VerifiedRecord {
  evidenceId: string;
  zoteroItemKey: string;
  doi: string;
  title: string;
  candidate: Candidate;
  verification: PdfVerification;
}

export interface JobRecord {
  schemaVersion: 1;
  jobId: string;
  request: FetchRequest;
  state: JobState;
  createdAt: string;
  updatedAt: string;
  records: Array<{
    evidenceId: string;
    zoteroItemKey: string;
    state: RecordState;
    errorCode?: ErrorCode;
    message?: string;
    verified?: VerifiedRecord;
  }>;
  handoffId?: string;
  handoffHash?: string;
  userActionRequired: boolean;
  message?: string;
}

export interface BrokerIndex {
  schemaVersion: 1;
  requestIds: Record<string, { fingerprint: string; jobId: string }>;
}

export interface FulltextAdapter {
  providerNames(): string[];
  resolveCandidates(record: FetchRecord): Promise<Candidate[]>;
  download(candidate: Candidate): Promise<DownloadedPdf>;
}

export const TERMINAL_JOB_STATES = new Set<JobState>(['complete', 'partial', 'failed', 'canceled', 'stale']);
