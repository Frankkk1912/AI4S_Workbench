export type StageId = "em" | "nvt" | "npt" | "md_prod";

export type RunStatus =
  | "queued"
  | "running"
  | "stopping"
  | "stopped"
  | "completed"
  | "failed"
  | "attention"
  | "unknown"
  | "interrupted";

export type ApprovalKind = "strategy" | "extension" | "resume" | "retry";

export interface Run {
  run_id: string;
  request_id: string;
  project: string;
  stage: StageId;
  status: RunStatus;
  work_dir: string;
}

export interface ProgressData {
  checked_at: string;
  step: number;
  total_steps: number;
  percent: number;
  ns_per_day: number | null;
  eta: string | null;
  stale: boolean;
  source?: string;
  warnings?: string[];
  log_age_seconds?: number;
}

export interface Strategy {
  stages?: string[];
  mdp_templates?: Record<string, unknown>;
  duration_ns?: number;
  constraints?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface Approval {
  approval_id: string;
  kind: ApprovalKind;
  payload_hash: string;
  sidecar_path: string;
  approved_by: string;
  approved_at: string;
  lineage: Record<string, unknown>;
  confirmed: boolean;
}

export interface MdpDiffEntry {
  key: string;
  default: string;
  current: string | null | undefined;
  changed: boolean;
  explanation: string;
  protected: boolean;
}

export interface ProtectedField {
  default?: unknown;
  current?: unknown;
  source?: string;
  protected?: boolean;
  explanation?: string;
}

export interface ParamsDiff {
  mdp: MdpDiffEntry[];
  force_field: ProtectedField;
  water_model: ProtectedField;
  topology: ProtectedField;
  protected_fields: string[];
}

export interface ReceiptStatus {
  receipt_path: string;
  status: "fresh" | "expiring" | "expired";
  age_days: number;
  remaining_days: number;
  message: string;
}

export interface ReceiptError {
  returncode?: number | null;
  stderr?: string;
  stage?: StageId;
  run_id?: string;
}
