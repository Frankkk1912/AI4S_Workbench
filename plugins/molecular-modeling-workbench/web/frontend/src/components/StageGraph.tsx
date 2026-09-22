import type { RunStatus, StageId } from "../api/types";

export interface StageState {
  stage: StageId;
  label: string;
  status: RunStatus;
}

export interface StageGraphProps {
  stages: StageState[];
  diagnosticsAvailable?: boolean;
}

const DEFAULT_STAGES: StageState[] = [
  { stage: "em", label: "EM", status: "queued" },
  { stage: "nvt", label: "NVT", status: "queued" },
  { stage: "npt", label: "NPT", status: "queued" },
  { stage: "md_prod", label: "Prod", status: "queued" },
];

export function StageGraph({
  stages = DEFAULT_STAGES,
  diagnosticsAvailable = false,
}: StageGraphProps) {
  return (
    <section className="stage-graph" data-testid="stage-graph">
      <h3>阶段状态</h3>
      <ol className="stepper">
        {stages.map((stage) => (
          <li
            key={stage.stage}
            className={`step status-${stage.status}`}
            data-testid={`stage-${stage.stage}`}
          >
            <span className="step-label">{stage.label}</span>
            <span
              className="badge status"
              data-testid={`stage-status-${stage.stage}`}
            >
              {stage.status}
            </span>
          </li>
        ))}
      </ol>
      <div className="diagnostics" data-testid="diagnostics">
        {diagnosticsAvailable ? (
          <span>edr 派生诊断曲线：可分析（已完成 / 受控冻结快照）</span>
        ) : (
          <span>
            诊断曲线：
            <span data-testid="diagnostics-pending">待数据</span>
            <span className="note">
              （正式分析仅针对已完成或受控冻结快照，不读半写文件）
            </span>
          </span>
        )}
      </div>
    </section>
  );
}
