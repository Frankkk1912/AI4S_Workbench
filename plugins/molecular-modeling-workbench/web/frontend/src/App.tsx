import { useMemo, useState } from "react";
import { ApiClient } from "./api/client";
import { nativeEventSourceFactory } from "./api/stream";
import type {
    Approval,
    ParamsDiff,
    ProgressData,
    Run,
    Strategy,
} from "./api/types";
import { StageGraph } from "./components/StageGraph";
import { ProgressMetrics } from "./components/ProgressMetrics";
import { LiveLog } from "./components/LiveLog";
import { ErrorView } from "./components/ErrorView";
import { ParamsReview } from "./components/ParamsReview";
import { ApprovalPanel } from "./components/ApprovalPanel";
import { RunControls } from "./components/RunControls";

const DEMO_STRATEGY: Strategy = {
    stages: ["em", "nvt", "npt", "md_prod"],
    mdp_templates: { em: { name: "em.mdp" } },
    duration_ns: 100,
    constraints: { threads: 8, profile: "linux-gpu" },
};

const STAGE_ORDER = ["em", "nvt", "npt", "md_prod"] as const;

export default function App() {
    const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:8765");
    const [token, setToken] = useState(
        () => localStorage.getItem("md-workbench-token") ?? "",
    );
    const [runId, setRunId] = useState("");
    const [run, setRun] = useState<Run | null>(null);
    const [approval, setApproval] = useState<Approval | null>(null);
    const [params, setParams] = useState<ParamsDiff | null>(null);
    const [progress, setProgress] = useState<ProgressData | null>(null);
    const [error, setError] = useState<string | null>(null);

    const client = useMemo(
        () => new ApiClient(baseUrl, token),
        [baseUrl, token],
    );

    const load = async () => {
        setError(null);
        try {
            localStorage.setItem("md-workbench-token", token);
            const [runDoc, approvalDoc, paramsDoc] = await Promise.all([
                client.getRun(runId),
                client.getApproval(runId),
                client.getParamsDiff({ stage: "md_prod" }),
            ]);
            setRun(runDoc);
            setApproval(approvalDoc.approval);
            setParams(paramsDoc);
        } catch (caught) {
            setError(caught instanceof Error ? caught.message : String(caught));
        }
    };

    const createSource = useMemo(
        () =>
            nativeEventSourceFactory(
                `${baseUrl}/stream/log?log=&total_steps=50000000`,
            ),
        [baseUrl],
    );

    const stages =
        run === null
            ? []
            : STAGE_ORDER.map((stage) => ({
                  stage,
                  label: stage === "md_prod" ? "Prod" : stage.toUpperCase(),
                  status:
                      run.stage === stage
                          ? run.status
                          : run.stage === "em" && stage !== "em"
                            ? "queued"
                            : "queued",
              }));

    return (
        <main className="app">
            <header>
                <h1>MD Local Workbench</h1>
                <p>本地单用户 MD 仿真工作台（前端核心 UI，M4）</p>
            </header>

            <section className="connection">
                <label>
                    后端{" "}
                    <input
                        value={baseUrl}
                        onChange={(e) => setBaseUrl(e.target.value)}
                    />
                </label>
                <label>
                    token{" "}
                    <input
                        value={token}
                        onChange={(e) => setToken(e.target.value)}
                    />
                </label>
                <label>
                    run_id{" "}
                    <input
                        value={runId}
                        onChange={(e) => setRunId(e.target.value)}
                    />
                </label>
                <button type="button" onClick={load}>
                    加载
                </button>
            </section>

            {error && (
                <ErrorView receipt={{ returncode: null, stderr: error }} />
            )}

            {run && (
                <RunControls
                    run={run}
                    approved={approval?.confirmed === true}
                    onStop={async () => {
                        await client.stopRun(runId, { receipt_path: "" });
                    }}
                    onResume={async (input) => {
                        await client.resumeRun(runId, input);
                    }}
                    onRetry={async (reason) => {
                        await client.retryRun(runId, {
                            reason,
                            strategy: DEMO_STRATEGY,
                            receipt_path: "",
                        });
                    }}
                    onExtend={async () => {
                        await client.approveRun(
                            runId,
                            { ...DEMO_STRATEGY, extension: { target_ns: 200 } },
                            "extension",
                        );
                    }}
                    onForceKill={() => {
                        // Force kill (SIGKILL) is a runner-side operation (T3.3) with no
                        // HTTP endpoint in M3; the explicit authorization UI is wired here.
                    }}
                />
            )}

            {run && (
                <StageGraph
                    stages={stages}
                    diagnosticsAvailable={
                        run.stage === "md_prod" && run.status === "completed"
                    }
                />
            )}

            {progress && <ProgressMetrics progress={progress} />}

            <LiveLog createSource={createSource} onProgress={setProgress} />

            {params && <ParamsReview params={params} />}

            {run && (
                <ApprovalPanel
                    runId={runId}
                    strategy={DEMO_STRATEGY}
                    approval={approval}
                    onApprove={async (kind, strategy) => {
                        await client.approveRun(runId, strategy, kind);
                    }}
                />
            )}
        </main>
    );
}
