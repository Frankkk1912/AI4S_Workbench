import type {
    Approval,
    ApprovalKind,
    ReceiptStatus,
    Strategy,
} from "../api/types";

export interface ApprovalPanelProps {
    runId: string;
    strategy: Strategy;
    approval: Approval | null;
    receiptStatus?: ReceiptStatus | null;
    disabled?: boolean;
    onApprove: (kind: ApprovalKind, strategy: Strategy) => void | Promise<void>;
}

export function ApprovalPanel({
    runId,
    strategy,
    approval,
    receiptStatus,
    disabled,
    onApprove,
}: ApprovalPanelProps) {
    const approved = approval?.confirmed === true;
    return (
        <section className="approval-panel" data-testid="approval-panel">
            <h3>策略审批</h3>
            <p className="run-id" data-testid="approval-run-id">
                run: {runId}
            </p>
            {receiptStatus && receiptStatus.status !== "fresh" && (
                <div
                    className={`receipt-warning ${receiptStatus.status}`}
                    data-testid="receipt-warning"
                    role="status"
                >
                    {receiptStatus.message}
                </div>
            )}
            <p data-testid="approval-state">
                {approved ? `已批准（${approval?.kind}）` : "未批准"}
            </p>
            <button
                type="button"
                data-testid="approve-button"
                disabled={disabled ?? false}
                onClick={() => onApprove("strategy", strategy)}
            >
                {approved ? "再批准" : "批准"}
            </button>
        </section>
    );
}
