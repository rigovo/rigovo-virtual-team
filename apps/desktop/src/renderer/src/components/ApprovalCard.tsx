/* ------------------------------------------------------------------ */
/*  ApprovalCard — attention-grabbing approval request                 */
/* ------------------------------------------------------------------ */

interface ApprovalCardProps {
  taskId: string;
  onApprove: () => void;
  onReject: () => void;
}

export default function ApprovalCard({ onApprove, onReject }: ApprovalCardProps) {
  return (
    <div className="approval-card animate-fadeup animate-border-pulse">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">{"\u270B"}</span>
        <p className="text-sm font-bold text-amber-300">Your approval is needed</p>
      </div>
      <p className="text-xs text-amber-200/70 mb-4">
        Review the agent work above and approve to continue, or reject to stop the pipeline.
      </p>
      <div className="flex gap-2">
        <button type="button" className="primary-btn text-sm" onClick={onApprove}>
          Approve & Resume
        </button>
        <button type="button" className="warn-btn text-sm" onClick={onReject}>
          Reject
        </button>
      </div>
    </div>
  );
}
