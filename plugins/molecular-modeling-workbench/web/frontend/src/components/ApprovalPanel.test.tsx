import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ApprovalPanel } from "./ApprovalPanel";
import type { Approval, Strategy } from "../api/types";

const STRATEGY: Strategy = {
  stages: ["em", "nvt", "npt", "md_prod"],
  duration_ns: 100,
};

const APPROVAL: Approval = {
  approval_id: "appr-1",
  kind: "strategy",
  payload_hash: "x".repeat(64),
  sidecar_path: "/work/approvals/appr-1.json",
  approved_by: "user",
  approved_at: "2026-09-18T12:00:00+00:00",
  lineage: {},
  confirmed: true,
};

describe("ApprovalPanel", () => {
  it("shows the unapproved state and calls onApprove on click", () => {
    const onApprove = vi.fn();
    render(
      <ApprovalPanel
        runId="r1"
        strategy={STRATEGY}
        approval={null}
        onApprove={onApprove}
      />,
    );
    expect(screen.getByTestId("approval-state")).toHaveTextContent("未批准");
    fireEvent.click(screen.getByTestId("approve-button"));
    expect(onApprove).toHaveBeenCalledWith("strategy", STRATEGY);
  });

  it("shows re-approve for an existing approval", () => {
    render(
      <ApprovalPanel
        runId="r1"
        strategy={STRATEGY}
        approval={APPROVAL}
        onApprove={vi.fn()}
      />,
    );
    expect(screen.getByTestId("approval-state")).toHaveTextContent("已批准");
    expect(screen.getByTestId("approve-button")).toHaveTextContent("再批准");
  });

  it("shows the 7-day receipt warning when expiring or expired", () => {
    render(
      <ApprovalPanel
        runId="r1"
        strategy={STRATEGY}
        approval={null}
        receiptStatus={{
          receipt_path: "/work/receipt.json",
          status: "expiring",
          age_days: 6.5,
          remaining_days: 0.5,
          message: "Environment receipt expires soon; plan to re-verify.",
        }}
        onApprove={vi.fn()}
      />,
    );
    expect(screen.getByTestId("receipt-warning")).toHaveTextContent(
      "expires soon",
    );
  });
});
