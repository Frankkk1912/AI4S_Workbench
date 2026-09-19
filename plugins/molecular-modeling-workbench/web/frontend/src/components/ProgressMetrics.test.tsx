import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProgressMetrics } from "./ProgressMetrics";
import type { ProgressData } from "../api/types";

function progress(overrides: Partial<ProgressData> = {}): ProgressData {
  return {
    checked_at: "2026-09-18T12:00:00+00:00",
    step: 1000,
    total_steps: 50000,
    percent: 2,
    ns_per_day: 12.3,
    eta: "1d 2h",
    stale: false,
    source: "monitoring",
    ...overrides,
  };
}

describe("ProgressMetrics", () => {
  it("renders 未知 (not a fake 0) for missing ETA and throughput", () => {
    render(
      <ProgressMetrics
        progress={progress({ eta: "unavailable", ns_per_day: null })}
      />,
    );
    expect(screen.getByTestId("metric-eta")).toHaveTextContent("未知");
    expect(screen.getByTestId("metric-throughput")).toHaveTextContent("未知");
    expect(screen.getByTestId("metric-eta")).not.toHaveTextContent("0");
  });

  it("marks stale data and monitoring source explicitly", () => {
    render(<ProgressMetrics progress={progress({ stale: true })} />);
    expect(screen.getByTestId("stale-label")).toBeInTheDocument();
    expect(screen.getByTestId("monitoring-label")).toHaveTextContent(
      "monitoring",
    );
  });

  it("shows the last-updated timestamp", () => {
    render(<ProgressMetrics progress={progress()} />);
    expect(screen.getByTestId("metric-updated")).toHaveTextContent("最近更新");
  });
});
