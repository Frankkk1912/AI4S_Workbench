import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { RunControls } from "./RunControls";
import type { Run } from "../api/types";

function run(status: Run["status"]): Run {
  return {
    run_id: "r1",
    request_id: "req-1",
    project: "nrlp3",
    stage: "md_prod",
    status,
    work_dir: "/work",
  };
}

function props(status: Run["status"], approved = true) {
  return {
    run: run(status),
    approved,
    onStop: vi.fn(),
    onResume: vi.fn(),
    onRetry: vi.fn(),
    onExtend: vi.fn(),
    onForceKill: vi.fn(),
  };
}

describe("RunControls", () => {
  it("maps safe stop to onStop for a running run and shows grace", () => {
    const p = props("running");
    render(<RunControls {...p} />);
    expect(screen.getByTestId("grace-info")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("stop-button"));
    expect(p.onStop).toHaveBeenCalled();
  });

  it("disables every operation when not approved", () => {
    const p = props("running", false);
    render(<RunControls {...p} />);
    expect(screen.getByTestId("unapproved-notice")).toBeInTheDocument();
    expect(screen.getByTestId("stop-button")).toBeDisabled();
    expect(screen.getByTestId("extend-button")).toBeDisabled();
  });

  it("shows interrupted (not running) and requires confirmation + valid cpt", () => {
    const p = props("interrupted");
    render(<RunControls {...p} cptValidation={{ valid: true }} />);
    expect(screen.getByTestId("run-status")).toHaveTextContent("interrupted");
    expect(screen.getByTestId("run-status")).not.toHaveTextContent("running");
    expect(screen.getByTestId("resume-button")).toBeDisabled();
    fireEvent.click(screen.getByTestId("resume-confirm"));
    fireEvent.click(screen.getByTestId("resume-button"));
    expect(p.onResume).toHaveBeenCalled();
  });

  it("requires explicit authorization for force kill in attention state", () => {
    const p = props("attention");
    render(<RunControls {...p} />);
    expect(screen.getByTestId("force-kill-button")).toBeDisabled();
    fireEvent.click(screen.getByTestId("force-kill-authorize"));
    fireEvent.click(screen.getByTestId("force-kill-button"));
    expect(p.onForceKill).toHaveBeenCalled();
  });

  it("requires a reason for failed retry and maps it to onRetry", () => {
    const p = props("failed");
    render(<RunControls {...p} />);
    expect(screen.getByTestId("retry-button")).toBeDisabled();
    fireEvent.change(screen.getByTestId("retry-reason"), {
      target: { value: "fix mdp" },
    });
    fireEvent.click(screen.getByTestId("retry-button"));
    expect(p.onRetry).toHaveBeenCalledWith("fix mdp");
  });

  it("maps extend to onExtend and describes the frozen-cpt -> new-TPR chain", () => {
    const p = props("running");
    render(<RunControls {...p} />);
    expect(screen.getByTestId("op-extend")).toHaveTextContent(
      "冻结 checkpoint",
    );
    fireEvent.click(screen.getByTestId("extend-button"));
    expect(p.onExtend).toHaveBeenCalled();
  });
});
