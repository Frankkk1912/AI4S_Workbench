import { describe, expect, it } from "vitest";
import { ApiClient, type FetchLike } from "./client";

interface Call {
  url: string;
  method: string;
  body?: unknown;
  headers?: Record<string, string>;
}

function mockFetch(): { fn: FetchLike; calls: Call[] } {
  const calls: Call[] = [];
  const fn: FetchLike = async (input, init) => {
    const headers = (init?.headers ?? {}) as Record<string, string>;
    calls.push({
      url: String(input),
      method: init?.method ?? "GET",
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
      headers,
    });
    return {
      ok: true,
      status: 200,
      json: async () => ({ run_id: "r1", status: "running" }),
    } as unknown as Response;
  };
  return { fn, calls };
}

describe("ApiClient operation mapping", () => {
  it("maps stop/resume/retry/approve to the correct endpoints", async () => {
    const { fn, calls } = mockFetch();
    const api = new ApiClient("http://127.0.0.1:8765", "tok", fn);

    await api.stopRun("r1", { receipt_path: "/w/receipt.json" });
    expect(calls[0].url).toBe("http://127.0.0.1:8765/runs/r1/stop");
    expect(calls[0].method).toBe("POST");
    expect(calls[0].headers?.["X-AI4S-Request"]).toBe("1");
    expect(calls[0].headers?.Authorization).toBe("Bearer tok");

    await api.resumeRun("r1", {
      stage: "md_prod",
      attempt_id: 1,
      cpt_path: "/w/cpt",
      tpr_path: "/w/tpr",
    });
    expect(calls[1].url).toContain("/runs/r1/resume");

    await api.retryRun("r1", {
      reason: "fix inputs",
      strategy: {},
      receipt_path: "/w/r",
    });
    expect(calls[2].url).toContain("/runs/r1/retry");

    await api.approveRun("r1", { stages: ["em"] }, "extension");
    expect(calls[3].url).toContain("/runs/r1/approve");
    expect((calls[3].body as { kind: string }).kind).toBe("extension");
  });

  it("maps analysis approval and gallery reads through the backend", async () => {
    const { fn, calls } = mockFetch();
    const api = new ApiClient("http://127.0.0.1:8765", "tok", fn);
    await api.getAnalysisSessions("r1");
    await api.approveAnalysis({
      request_id: "analysis-1",
      run_id: "r1",
      source_kind: "completed",
      source_stage: "md_prod",
      group: "backbone",
      fit_group: "protein",
      eq_start_ns: 20,
      style: {
        colors: {},
        font_family: "sans-serif",
        font_size: 8,
        fig_size: [6.8, 7.5],
        style_schema_version: "1.0",
      },
    });
    expect(calls[0].url).toContain("/analysis/runs/r1/sessions");
    expect(calls[1].url).toContain("/analysis/sessions");
    expect(calls[1].method).toBe("POST");
    expect(calls[1].headers?.["X-AI4S-Request"]).toBe("1");
    expect((calls[1].body as { source_kind: string }).source_kind).toBe(
      "completed",
    );

    await api.restyleAnalysis("analysis-1", "redraw-1", {
      colors: { system: "#123456" },
      font_family: "serif",
      font_size: 12,
      fig_size: [10, 8],
      style_schema_version: "1.0",
    });
    expect(calls[2].url).toContain("/analysis/sessions/analysis-1/style");
    expect(calls[2].method).toBe("POST");
    expect(calls[2].headers?.["X-AI4S-Request"]).toBe("1");
    expect((calls[2].body as { request_id: string }).request_id).toBe(
      "redraw-1",
    );
  });

  it("does not send the CSRF header on GET requests", async () => {
    const { fn, calls } = mockFetch();
    const api = new ApiClient("http://127.0.0.1:8765", "tok", fn);
    await api.getRun("r1");
    expect(calls[0].method).toBe("GET");
    expect(calls[0].headers?.["X-AI4S-Request"]).toBeUndefined();
    expect(calls[0].headers?.Authorization).toBe("Bearer tok");
  });
});
