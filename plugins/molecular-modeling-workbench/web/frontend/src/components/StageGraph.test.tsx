import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StageGraph } from "./StageGraph";
import type { StageState } from "./StageGraph";

const STAGES: StageState[] = [
  { stage: "em", label: "EM", status: "completed" },
  { stage: "nvt", label: "NVT", status: "running" },
  { stage: "npt", label: "NPT", status: "queued" },
  { stage: "md_prod", label: "Prod", status: "queued" },
];

describe("StageGraph", () => {
  it("renders each stage status", () => {
    render(<StageGraph stages={STAGES} />);
    expect(screen.getByTestId("stage-status-em")).toHaveTextContent(
      "completed",
    );
    expect(screen.getByTestId("stage-status-nvt")).toHaveTextContent("running");
  });

  it("shows 待数据 for edr-derived diagnostics while a stage is incomplete", () => {
    render(<StageGraph stages={STAGES} />);
    expect(screen.getByTestId("diagnostics-pending")).toHaveTextContent(
      "待数据",
    );
    expect(screen.getByTestId("diagnostics")).toHaveTextContent("不读半写文件");
  });

  it("shows diagnostics available for a completed stage", () => {
    render(<StageGraph stages={STAGES} diagnosticsAvailable />);
    expect(screen.getByTestId("diagnostics")).toHaveTextContent("可分析");
  });
});
