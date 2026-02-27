interface ApprovalCardProps {
  taskId: string;
  onApprove: () => void;
  onReject: () => void;
}

export default function ApprovalCard({ onApprove, onReject }: ApprovalCardProps) {
  return (
    <div className="approval-card animate-fadeup animate-border-pulse">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-base">✋</span>
        <p className="text-sm font-semibold" style={{ color: "#b45309" }}>
          Your approval is needed
        </p>
      </div>
      <p className="text-xs mb-4" style={{ color: "var(--t3)" }}>
        Review the agent work above and approve to continue, or reject to stop.
      </p>
      <div className="flex gap-2">
        <button type="button" className="primary-btn" onClick={onApprove}>
          Approve &amp; Resume
        </button>
        <button type="button" className="warn-btn" onClick={onReject}>
          Reject
        </button>
      </div>
    </div>
  );
}
