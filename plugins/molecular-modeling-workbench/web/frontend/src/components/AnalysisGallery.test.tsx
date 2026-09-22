import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AnalysisSession } from "../api/types";
import { AnalysisGallery } from "./AnalysisGallery";

const SESSION: AnalysisSession = {
  session_id: "analysis-1",
  source_run_id: "run-1",
  task_run_id: "task-1",
  source_stage: "md_prod",
  status: "completed",
  created_at: "2026-09-18T12:00:00+00:00",
  source_kind: "completed",
  science: {
    tpr_sha256: "a".repeat(64),
    xtc_sha256: "b".repeat(64),
    edr_sha256: "c".repeat(64),
    group: "backbone",
    fit_group: "protein",
    begin_ps: 0,
    end_ps: 1000,
    eq_start_ns: 20,
    cli_version: "1.0",
    science_schema_version: "1.0",
    science_source_artifact_sha256: "d".repeat(64),
  },
  style: {
    colors: { system: "#4a90e2", comparison: "#e95c4b" },
    font_family: "sans-serif",
    font_size: 8,
    fig_size: [6.8, 7.5],
    style_schema_version: "1.0",
  },
  exports: {
    png: "/analysis/sessions/analysis-1/exports/png",
    svg: "/analysis/sessions/analysis-1/exports/svg",
    pdf: "/analysis/sessions/analysis-1/exports/pdf",
  },
};

describe("AnalysisGallery", () => {
  it("labels formal provenance, data reference, and all export formats", () => {
    render(
      <AnalysisGallery
        sessions={[SESSION]}
        canApprove
        previewUrls={{ "analysis-1": "blob:preview" }}
        onApprove={vi.fn()}
        onRestyle={vi.fn()}
        onExport={vi.fn()}
      />,
    );
    expect(screen.getByTestId("analysis-gallery")).toHaveTextContent(
      "实时监控不作为分析结果",
    );
    expect(screen.getByTestId("analysis-analysis-1")).toHaveTextContent(
      "已完成阶段",
    );
    expect(screen.getByTestId("analysis-analysis-1")).toHaveTextContent(
      "bbbbbbbbbbbb",
    );
    expect(screen.getByTestId("preview-analysis-1")).toHaveAttribute(
      "src",
      "blob:preview",
    );
    expect(screen.getByTestId("analysis-analysis-1")).toHaveTextContent(
      "温度、压力、势能、RMSD 与 RMSF",
    );
    for (const format of ["png", "svg", "pdf"]) {
      expect(screen.getByTestId(`export-analysis-1-${format}`)).toBeEnabled();
    }
  });

  it("only asks the backend to approve analysis and export", () => {
    const onApprove = vi.fn();
    const onExport = vi.fn();
    const onRestyle = vi.fn();
    render(
      <AnalysisGallery
        sessions={[SESSION]}
        canApprove
        onApprove={onApprove}
        onRestyle={onRestyle}
        onExport={onExport}
      />,
    );
    fireEvent.click(screen.getByTestId("approve-analysis"));
    fireEvent.change(screen.getByLabelText("字号"), {
      target: { value: "12" },
    });
    fireEvent.click(screen.getByTestId("restyle-analysis-1"));
    fireEvent.click(screen.getByTestId("export-analysis-1-pdf"));
    expect(onApprove).toHaveBeenCalledOnce();
    expect(onRestyle).toHaveBeenCalledWith(
      "analysis-1",
      expect.objectContaining({ font_size: 12 }),
    );
    expect(onExport).toHaveBeenCalledWith("analysis-1", "pdf");
    expect(document.body.textContent).not.toMatch(/docker|shell|gmx\s+mdrun/i);
  });

  it("disables unavailable exports and approval for an incomplete stage", () => {
    render(
      <AnalysisGallery
        sessions={[{ ...SESSION, exports: {} }]}
        canApprove={false}
        onApprove={vi.fn()}
        onRestyle={vi.fn()}
        onExport={vi.fn()}
      />,
    );
    expect(screen.getByTestId("approve-analysis")).toBeDisabled();
    expect(screen.getByTestId("export-analysis-1-png")).toBeDisabled();
    expect(screen.getByTestId("restyle-analysis-1")).toBeEnabled();
  });
});
