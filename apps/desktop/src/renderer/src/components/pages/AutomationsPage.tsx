import { useCallback, useState } from "react";
import type { ApprovalItem, InboxTask } from "../../types";
import { API_BASE } from "../../api";

type PolicySnapshot = {
  defaultTier: string;
  deepRigour: boolean;
  requireApprovalHighRisk: boolean;
  requireApprovalProdSecrets: boolean;
  notifyChannels: string[];
};

interface AutomationsPageProps {
  inbox: InboxTask[];
  approvals: ApprovalItem[];
  policy: PolicySnapshot | null;
}

/* ── Per-card loading + dismissed state ─────────────────────────── */
function useApprovalAction(taskId: string, onDone: (id: string) => void) {
  const [busy, setBusy] = useState(false);

  const act = useCallback(
    async (action: "approve" | "deny") => {
      if (busy) return;
      setBusy(true);
      try {
        await fetch(`${API_BASE}/v1/tasks/${taskId}/${action}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ actor: "operator" }),
        });
        onDone(taskId);
      } catch {
        // best-effort
      } finally {
        setBusy(false);
      }
    },
    [busy, taskId, onDone],
  );

  return { busy, approve: () => act("approve"), reject: () => act("deny") };
}

/* ── Approve-tier card (blocks until human decision) ──────────────── */
function ApproveCard({
  item,
  onDone,
}: {
  item: ApprovalItem;
  onDone: (id: string) => void;
}) {
  const { busy, approve, reject } = useApprovalAction(item.taskId, onDone);

  return (
    <div className="approval-card animate-fadeup animate-border-pulse">
      <div className="approval-card-meta">
        <span className="tier-chip tier-approve">approve</span>
        <span className="approval-card-age">{item.age}</span>
        <span className="approval-card-by">by {item.requestedBy}</span>
      </div>
      <p className="approval-card-summary">{item.summary}</p>
      <div className="approval-card-actions">
        <button
          type="button"
          className="primary-btn"
          onClick={approve}
          disabled={busy}
        >
          {busy ? "…" : "Approve & Resume"}
        </button>
        <button
          type="button"
          className="warn-btn"
          onClick={reject}
          disabled={busy}
        >
          Reject
        </button>
      </div>
    </div>
  );
}

/* ── Notify-tier card (informational, no action required) ─────────── */
function NotifyCard({ item, onDismiss }: { item: ApprovalItem; onDismiss: (id: string) => void }) {
  return (
    <div className="notify-card animate-fadeup">
      <div className="approval-card-meta">
        <span className="tier-chip tier-notify">notify</span>
        <span className="approval-card-age">{item.age}</span>
        <span className="approval-card-by">by {item.requestedBy}</span>
      </div>
      <p className="approval-card-summary">{item.summary}</p>
      <button
        type="button"
        className="notify-card-dismiss"
        onClick={() => onDismiss(item.id)}
        aria-label="Dismiss notification"
      >
        Dismiss
      </button>
    </div>
  );
}

/* ── Main page ─────────────────────────────────────────────────────── */
export default function AutomationsPage({
  inbox,
  approvals,
  policy,
}: AutomationsPageProps): JSX.Element {
  // Local dismissal — items removed from view without a server call
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const dismiss = useCallback((id: string) => {
    setDismissed((prev) => new Set([...prev, id]));
  }, []);

  const visible = approvals.filter((a) => !dismissed.has(a.id) && !dismissed.has(a.taskId));
  const pendingApprove = visible.filter((a) => a.tier === "approve");
  const pendingNotify = visible.filter((a) => a.tier === "notify");

  const activeTasks = inbox.filter((task) => {
    const status = task.status.toLowerCase();
    return (
      !status.includes("complete") &&
      !status.includes("fail") &&
      !status.includes("reject")
    );
  });
  const completedTasks = inbox.length - activeTasks.length;

  return (
    <section className="workspace-page">
      <div className="workspace-page-header">
        <h2>Automations</h2>
        <p>Live operational state from inbox, approvals, and governance policy APIs.</p>
      </div>

      {/* ── Pending human approvals ──────────────────────────────── */}
      {pendingApprove.length > 0 && (
        <div className="approvals-section">
          <h3 className="approvals-section-title">
            Awaiting your approval
            <span className="approvals-count">{pendingApprove.length}</span>
          </h3>
          <div className="approvals-list">
            {pendingApprove.map((item) => (
              <ApproveCard key={item.id} item={item} onDone={dismiss} />
            ))}
          </div>
        </div>
      )}

      {/* ── Gate notifications (notify tier — informational) ──────── */}
      {pendingNotify.length > 0 && (
        <div className="approvals-section">
          <h3 className="approvals-section-title">
            Gate notifications
            <span className="approvals-count notify">{pendingNotify.length}</span>
          </h3>
          <div className="approvals-list">
            {pendingNotify.map((item) => (
              <NotifyCard key={item.id} item={item} onDismiss={dismiss} />
            ))}
          </div>
        </div>
      )}

      {/* ── Summary + policy cards ───────────────────────────────── */}
      <div className="workspace-grid">
        <article className="workspace-card">
          <div className="workspace-card-head">
            <div>
              <h3>Queue health</h3>
              <p>From `GET /v1/ui/inbox` and `GET /v1/ui/approvals`</p>
            </div>
          </div>
          <p className="workspace-card-copy">
            Active tasks: <strong>{activeTasks.length}</strong> · Completed/failed:{" "}
            <strong>{completedTasks}</strong> · Pending approvals:{" "}
            <strong>{pendingApprove.length}</strong> · Notifications:{" "}
            <strong>{pendingNotify.length}</strong>
          </p>
        </article>

        <article className="workspace-card">
          <div className="workspace-card-head">
            <div>
              <h3>Policy snapshot</h3>
              <p>From `GET /v1/control/state` policy</p>
            </div>
          </div>
          {policy ? (
            <p className="workspace-card-copy">
              Default tier: <strong>{policy.defaultTier}</strong> · Deep rigour:{" "}
              <strong>{policy.deepRigour ? "on" : "off"}</strong> · High-risk approvals:{" "}
              <strong>{policy.requireApprovalHighRisk ? "on" : "off"}</strong> · Prod secret
              approvals: <strong>{policy.requireApprovalProdSecrets ? "on" : "off"}</strong>
            </p>
          ) : (
            <p className="workspace-card-copy">Policy API data unavailable.</p>
          )}
        </article>

        <article className="workspace-card">
          <div className="workspace-card-head">
            <div>
              <h3>Notify channels</h3>
              <p>From `policy.notifyChannels`</p>
            </div>
          </div>
          <p className="workspace-card-copy">
            {policy?.notifyChannels?.length
              ? policy.notifyChannels.join(", ")
              : "No channels configured."}
          </p>
        </article>
      </div>
    </section>
  );
}
