import { useEffect, useMemo, useState } from "react";
import { ApiClient } from "./api/client";
import { nativeEventSourceFactory } from "./api/stream";
import type {
    AnalysisExportFormat,
    AnalysisSession,
    AnalysisStyle,
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
import { AnalysisGallery } from "./components/AnalysisGallery";

const DEMO_STRATEGY: Strategy = {
    stages: ["em", "nvt", "npt", "md_prod"],
    mdp_templates: { em: { name: "em.mdp" } },
    duration_ns: 100,
    constraints: { threads: 8, profile: "linux-gpu" },
};

const STAGE_ORDER = ["em", "nvt", "npt", "md_prod"] as const;

export default function App() {
    const [baseUrl, setBaseUrl] = useState("");
    const [token, setToken] = useState("");
    const [handoffComplete, setHandoffComplete] = useState(false);
    const [runId, setRunId] = useState("");
    const [run, setRun] = useState<Run | null>(null);
    const [approval, setApproval] = useState<Approval | null>(null);
    const [params, setParams] = useState<ParamsDiff | null>(null);
    const [progress, setProgress] = useState<ProgressData | null>(null);
    const [analysisSessions, setAnalysisSessions] = useState<AnalysisSession[]>(
        [],
    );
    const [analysisPreviews, setAnalysisPreviews] = useState<
        Record<string, string>
    >({});
    const [error, setError] = useState<string | null>(null);

    const client = useMemo(
        () => new ApiClient(baseUrl, token),
        [baseUrl, token],
    );

    useEffect(
        () => () => {
            for (const url of Object.values(analysisPreviews))
                URL.revokeObjectURL(url);
        },
        [analysisPreviews],
    );

    const setSessionsAndPreviews = async (sessions: AnalysisSession[]) => {
        const previews: Record<string, string> = {};
        for (const session of sessions) {
            if (session.exports.png) {
                const blob = await client.downloadAnalysisExport(
                    session.session_id,
                    "png",
                );
                previews[session.session_id] = URL.createObjectURL(blob);
            }
        }
        setAnalysisSessions(sessions);
        setAnalysisPreviews(previews);
    };

    const load = async () => {
        setError(null);
        try {
            if (!token) throw new Error("请输入后端启动时显示的一次性本地 token");
            await client.establishHandoff();
            setHandoffComplete(true);
            setToken("");
            const [runDoc, approvalDoc, paramsDoc, analysisDoc] =
                await Promise.all([
                    client.getRun(runId),
                    client.getApproval(runId),
                    client.getParamsDiff({ stage: "md_prod" }),
                    client.getAnalysisSessions(runId),
                ]);
            setRun(runDoc);
            setApproval(approvalDoc.approval);
            setParams(paramsDoc);
            await setSessionsAndPreviews(analysisDoc.sessions);
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
                <p>本地单用户 MD 仿真工作台</p>
            </header>

            {!handoffComplete && (
                <aside className="security-guide" role="note">
                    首次访问：输入后端启动时显示的 token。token 保存在本机 0600
                    文件中，成功交接后浏览器仅使用 HttpOnly 同源 cookie；页面不会将
                    token 写入 localStorage。关闭 Pi 会停止服务；仅注销用户时能否继续
                    取决于 systemd user linger，未确认前不要假定可跨注销运行。
                </aside>
            )}

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
                        type="password"
                        autoComplete="off"
                        value={token}
                        onChange={(e) => {
                            setToken(e.target.value);
                            setHandoffComplete(false);
                        }}
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

            {run && (
                <AnalysisGallery
                    sessions={analysisSessions}
                    previewUrls={analysisPreviews}
                    canApprove={
                        run.stage === "md_prod" && run.status === "completed"
                    }
                    onApprove={async () => {
                        await client.approveAnalysis({
                            request_id: `analysis-${runId}-${Date.now()}`,
                            run_id: runId,
                            source_kind: "completed",
                            source_stage: "md_prod",
                            group: "backbone",
                            fit_group: "protein",
                            begin_ps: null,
                            end_ps: null,
                            eq_start_ns: 20,
                            style: {
                                colors: {},
                                font_family: "sans-serif",
                                font_size: 8,
                                fig_size: [6.8, 7.5],
                                style_schema_version: "1.0",
                            },
                        });
                        const refreshed =
                            await client.getAnalysisSessions(runId);
                        await setSessionsAndPreviews(refreshed.sessions);
                    }}
                    onRestyle={async (
                        sessionId: string,
                        style: AnalysisStyle,
                    ) => {
                        await client.restyleAnalysis(
                            sessionId,
                            `redraw-${sessionId}-${Date.now()}`,
                            style,
                        );
                        const refreshed =
                            await client.getAnalysisSessions(runId);
                        await setSessionsAndPreviews(refreshed.sessions);
                    }}
                    onExport={async (
                        sessionId: string,
                        format: AnalysisExportFormat,
                    ) => {
                        const blob = await client.downloadAnalysisExport(
                            sessionId,
                            format,
                        );
                        const url = URL.createObjectURL(blob);
                        const link = document.createElement("a");
                        link.href = url;
                        link.download = `${sessionId}.${format}`;
                        link.click();
                        URL.revokeObjectURL(url);
                    }}
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
