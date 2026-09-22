import type {
  AnalysisExportFormat,
  AnalysisSession,
  AnalysisStyle,
  Approval,
  ApprovalKind,
  ParamsDiff,
  ReceiptStatus,
  Run,
  Strategy,
} from "./types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface SubmitBody {
  request_id: string;
  project: string;
  stage: string;
  manifest_path: string;
  stage_plan: {
    deffnm: string;
    profile: string;
    threads: number;
    resume: boolean;
  };
}

export interface StopBody {
  container_id?: string | null;
  receipt_path: string;
  docker_path?: string;
}

export interface ResumeBody {
  stage: string;
  attempt_id: number;
  cpt_path: string;
  tpr_path: string;
  expected_checksum?: string | null;
  cpt_step?: number | null;
  log_step?: number | null;
}

export interface RetryBody {
  reason: string;
  strategy: Strategy;
  receipt_path: string;
}

export interface CreateAnalysisBody {
  request_id: string;
  run_id: string;
  source_kind: "completed" | "snapshot";
  source_stage: string;
  snapshot_id?: string;
  group: string;
  fit_group: string;
  begin_ps?: number | null;
  end_ps?: number | null;
  eq_start_ns: number;
  style: AnalysisStyle;
}

export type FetchLike = (
  input: string,
  init?: RequestInit,
) => Promise<Response>;

const CSRF_HEADER = "X-AI4S-Request";

/**
 * Thin typed client for the local workbench backend (127.0.0.1). Every request
 * carries the bearer token; write operations also carry the non-simple CSRF
 * header required by the security boundary (T2.2). No Docker or shell access
 * is ever performed from the frontend.
 */
export class ApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly token: string,
    // bind to globalThis: unbound native fetch throws "Illegal invocation" in browsers
    private readonly fetchFn: FetchLike = globalThis.fetch.bind(globalThis),
  ) {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {};
    const raw = init.headers as Record<string, string> | undefined;
    if (raw) {
      for (const [key, value] of Object.entries(raw)) headers[key] = value;
    }
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    const method = init.method ?? "GET";
    if (method !== "GET" && method !== "HEAD") {
      headers[CSRF_HEADER] = "1";
    }
    const response = await this.fetchFn(`${this.baseUrl}${path}`, {
      ...init,
      credentials: "include",
      headers,
    });
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const body = (await response.json()) as { detail?: unknown };
        if (body && typeof body.detail === "string") detail = body.detail;
      } catch {
        // Non-JSON error body: keep the HTTP status message.
      }
      throw new ApiError(response.status, detail);
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  async establishHandoff(): Promise<void> {
    const response = await this.fetchFn(`${this.baseUrl}/auth/handoff`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        [CSRF_HEADER]: "1",
      },
      body: JSON.stringify({ access_token: this.token }),
    });
    if (!response.ok) {
      throw new ApiError(response.status, "Local token handoff failed");
    }
  }

  getRun(runId: string): Promise<Run> {
    return this.request<Run>(`/runs/${runId}`);
  }

  getApproval(
    runId: string,
  ): Promise<{ run_id: string; approval: Approval | null }> {
    return this.request(`/runs/${runId}/approval`);
  }

  approveRun(
    runId: string,
    strategy: Strategy,
    kind: ApprovalKind = "strategy",
  ): Promise<{
    approval_id: string;
    run_id: string;
    kind: string;
    strategy_hash: string;
    sidecar_path: string;
  }> {
    return this.request(`/runs/${runId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ strategy, kind }),
    });
  }

  retryRun(
    runId: string,
    body: RetryBody,
  ): Promise<{ run_id: string; status: string; reason: string }> {
    return this.request(`/runs/${runId}/retry`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  stopRun(
    runId: string,
    body: StopBody,
  ): Promise<{ container_id: string; signal: string; status: string }> {
    return this.request(`/runs/${runId}/stop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  resumeRun(
    runId: string,
    body: ResumeBody,
  ): Promise<{
    run_id: string;
    stage: string;
    attempt_id: number;
    status: string;
    cpt_checksum: string;
  }> {
    return this.request(`/runs/${runId}/resume`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  submitRun(body: SubmitBody): Promise<{ run_id: string; status: string }> {
    return this.request("/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  getParamsDiff(params: Record<string, string>): Promise<ParamsDiff> {
    const query = new URLSearchParams(params).toString();
    return this.request(`/params/diff?${query}`);
  }

  getReceiptStatus(receiptPath: string): Promise<ReceiptStatus> {
    const query = new URLSearchParams({ receipt_path: receiptPath }).toString();
    return this.request(`/params/receipt-status?${query}`);
  }

  getAnalysisSessions(
    runId: string,
  ): Promise<{ run_id: string; sessions: AnalysisSession[] }> {
    return this.request(`/analysis/runs/${runId}/sessions`);
  }

  approveAnalysis(body: CreateAnalysisBody): Promise<AnalysisSession> {
    return this.request("/analysis/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  restyleAnalysis(
    sessionId: string,
    requestId: string,
    style: AnalysisStyle,
  ): Promise<AnalysisSession> {
    return this.request(`/analysis/sessions/${sessionId}/style`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: requestId, style }),
    });
  }

  async downloadAnalysisExport(
    sessionId: string,
    format: AnalysisExportFormat,
  ): Promise<Blob> {
    const headers: Record<string, string> = {};
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    const response = await this.fetchFn(
      `${this.baseUrl}/analysis/sessions/${sessionId}/exports/${format}`,
      { credentials: "include", headers },
    );
    if (!response.ok) {
      throw new ApiError(response.status, `HTTP ${response.status}`);
    }
    return response.blob();
  }
}
