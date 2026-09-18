import { useState } from "react";
import type { Run, RunStatus } from "../api/types";

export interface ResumeInput {
  stage: string;
  attempt_id: number;
  cpt_path: string;
  tpr_path: string;
  expected_checksum?: string;
  cpt_step?: number;
  log_step?: number;
}

export interface ExtendInput {
  target_ns: number;
  frozen_cpt_path: string;
  tpr_path: string;
}

export interface RunControlsProps {
  run: Run;
  approved: boolean;
  graceSeconds?: number;
  cptValidation?: { valid: boolean; reason?: string } | null;
  onStop: () => void;
  onResume: (input: ResumeInput) => void;
  onRetry: (reason: string) => void;
  onExtend: (input: ExtendInput) => void;
  onForceKill: () => void;
}

export function RunControls({
  run,
  approved,
  graceSeconds,
  cptValidation,
  onStop,
  onResume,
  onRetry,
  onExtend,
  onForceKill,
}: RunControlsProps) {
  const [retryReason, setRetryReason] = useState("");
  const [confirmResume, setConfirmResume] = useState(false);
  const [confirmForceKill, setConfirmForceKill] = useState(false);
  const status: RunStatus = run.status;
  const graceText =
    graceSeconds === undefined
      ? "≥ max(2×checkpoint 间隔, 15 分钟)"
      : `${graceSeconds} 秒`;

  return (
    <section className="run-controls" data-testid="run-controls">
      <h3>控制操作</h3>
      <p data-testid="run-status">
        状态：<span className={`status-${status}`}>{status}</span>
      </p>
      {!approved && (
        <p data-testid="unapproved-notice">
          未批准：无可执行操作，请先完成策略审批。
        </p>
      )}

      {status === "running" && (
        <div className="op" data-testid="op-stop">
          <button
            type="button"
            disabled={!approved}
            onClick={onStop}
            data-testid="stop-button"
          >
            安全停止（SIGTERM）
          </button>
          <p className="grace-info" data-testid="grace-info">
            grace：{graceText}
          </p>
        </div>
      )}

      {status === "attention" && (
        <div className="op" data-testid="op-force-kill">
          <p className="cpt-note">
            checkpoint 校验：
            {cptValidation
              ? cptValidation.valid
                ? "通过"
                : `未通过：${cptValidation.reason ?? "未知原因"}`
              : "待校验"}
          </p>
          <label>
            <input
              type="checkbox"
              checked={confirmForceKill}
              onChange={(event) => setConfirmForceKill(event.target.checked)}
              data-testid="force-kill-authorize"
            />
            我理解强杀（SIGKILL）不产生新 checkpoint
          </label>
          <button
            type="button"
            disabled={!approved || !confirmForceKill}
            onClick={onForceKill}
            data-testid="force-kill-button"
          >
            强杀
          </button>
        </div>
      )}

      {status === "interrupted" && (
        <div className="op" data-testid="op-resume">
          <p className="cpt-note" data-testid="cpt-validation">
            checkpoint 校验：
            {cptValidation
              ? cptValidation.valid
                ? "通过"
                : `未通过：${cptValidation.reason ?? "未知原因"}`
              : "待校验"}
          </p>
          <label>
            <input
              type="checkbox"
              checked={confirmResume}
              onChange={(event) => setConfirmResume(event.target.checked)}
              data-testid="resume-confirm"
            />
            确认从 checkpoint 恢复（生成新 attempt）
          </label>
          <button
            type="button"
            disabled={!approved || !confirmResume || !cptValidation?.valid}
            onClick={() =>
              onResume({
                stage: run.stage,
                attempt_id: 0,
                cpt_path: "",
                tpr_path: "",
              })
            }
            data-testid="resume-button"
          >
            恢复
          </button>
        </div>
      )}

      {status === "failed" && (
        <div className="op" data-testid="op-retry">
          <input
            type="text"
            value={retryReason}
            onChange={(event) => setRetryReason(event.target.value)}
            placeholder="填写重试原因"
            data-testid="retry-reason"
          />
          <button
            type="button"
            disabled={!approved || retryReason.trim() === ""}
            onClick={() => onRetry(retryReason)}
            data-testid="retry-button"
          >
            失败重试
          </button>
        </div>
      )}

      <div className="op" data-testid="op-extend">
        <p className="extend-source">
          延长：冻结 checkpoint → 派生新 TPR（convert-tpr），需审批（T3.4）
        </p>
        <button
          type="button"
          disabled={!approved}
          onClick={() =>
            onExtend({ target_ns: 0, frozen_cpt_path: "", tpr_path: "" })
          }
          data-testid="extend-button"
        >
          延长时长
        </button>
      </div>
    </section>
  );
}
