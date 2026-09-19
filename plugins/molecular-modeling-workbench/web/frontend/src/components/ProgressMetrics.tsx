import {
  formatNumber,
  formatTimestamp,
  formatUnknown,
  UNKNOWN,
} from "../lib/format";
import type { ProgressData } from "../api/types";

export interface ProgressMetricsProps {
  progress: ProgressData;
  runNs?: number | null;
  targetNs?: number | null;
}

export function ProgressMetrics({
  progress,
  runNs,
  targetNs,
}: ProgressMetricsProps) {
  const eta = formatUnknown(progress.eta);
  const throughput =
    progress.ns_per_day === null || progress.ns_per_day === undefined
      ? UNKNOWN
      : formatNumber(progress.ns_per_day);
  const monitoring = progress.source === "monitoring";

  return (
    <section className="metrics" data-testid="progress-metrics">
      <div className="metrics-header">
        <h3>进度指标</h3>
        {monitoring && (
          <span className="badge monitoring" data-testid="monitoring-label">
            monitoring
          </span>
        )}
        {progress.stale && (
          <span className="badge stale" data-testid="stale-label">
            stale
          </span>
        )}
      </div>
      <dl className="metrics-grid">
        <div>
          <dt>step</dt>
          <dd data-testid="metric-step">
            {progress.step.toLocaleString()} /{" "}
            {progress.total_steps.toLocaleString()}
          </dd>
        </div>
        <div>
          <dt>已运行 ns</dt>
          <dd data-testid="metric-run-ns">
            {runNs === null || runNs === undefined
              ? UNKNOWN
              : formatNumber(runNs)}
          </dd>
        </div>
        <div>
          <dt>目标 ns</dt>
          <dd data-testid="metric-target-ns">
            {targetNs === null || targetNs === undefined
              ? UNKNOWN
              : formatNumber(targetNs)}
          </dd>
        </div>
        <div>
          <dt>ns/day</dt>
          <dd data-testid="metric-throughput">{throughput}</dd>
        </div>
        <div>
          <dt>ETA</dt>
          <dd data-testid="metric-eta">{eta}</dd>
        </div>
      </dl>
      <p className="metrics-updated" data-testid="metric-updated">
        最近更新：{formatTimestamp(progress.checked_at)}
      </p>
    </section>
  );
}
