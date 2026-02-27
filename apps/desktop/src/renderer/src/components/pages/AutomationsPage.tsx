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

/* ── Tier badge ─────────────────────────────────────────────────── */
function TierBadge({ tier }: { tier: string }) {
  const cfg: Record<string, { bg: string; color: string; label: string; dot: string }> = {
    approve: { bg: "rgba(220,38,38,0.08)", color: "#b91c1c", label: "Approval Required", dot: "#ef4444" },
    notify:  { bg: "rgba(59,130,246,0.08)", color: "#1d4ed8", label: "Notification",     dot: "#3b82f6" },
    auto:    { bg: "rgba(22,163,74,0.08)",  color: "#15803d", label: "Auto",             dot: "#22c55e" },
  };
  const c = cfg[tier] ?? cfg.auto;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "2px 8px", borderRadius: 100, background: c.bg, color: c.color, fontSize: 11, fontWeight: 600 }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: c.dot, flexShrink: 0 }} />
      {c.label}
    </span>
  );
}

/* ── Rich Approve-tier card ─────────────────────────────────────── */
function ApproveCard({ item, onDone }: { item: ApprovalItem; onDone: (id: string) => void }) {
  const { busy, approve, reject } = useApprovalAction(item.taskId, onDone);

  return (
    <div className="animate-fadeup animate-border-pulse" style={{
      border: "1.5px solid rgba(220,38,38,0.25)",
      borderRadius: 12,
      background: "rgba(255,241,241,0.6)",
      padding: "16px 18px",
      display: "flex",
      flexDirection: "column",
      gap: 12,
    }}>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <TierBadge tier="approve" />
          <span style={{ fontSize: 11, color: "var(--t3)" }}>
            {item.age} · by <span style={{ color: "var(--t2)", fontWeight: 500 }}>{item.requestedBy}</span>
          </span>
        </div>
        <span style={{
          fontSize: 10, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase",
          color: "#b91c1c", background: "rgba(220,38,38,0.08)", padding: "2px 8px", borderRadius: 6,
        }}>
          Blocking
        </span>
      </div>

      {/* Summary */}
      <p style={{ fontSize: 13, color: "var(--t1)", lineHeight: 1.6, margin: 0 }}>
        {item.summary}
      </p>

      {/* Task reference */}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 10, fontWeight: 600, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Task</span>
        <code style={{ fontSize: 11, color: "var(--t3)", background: "rgba(0,0,0,0.04)", padding: "1px 6px", borderRadius: 4 }}>
          {item.taskId.slice(0, 8)}…
        </code>
      </div>

      {/* Actions */}
      <div style={{ display: "flex", gap: 8, paddingTop: 4 }}>
        <button
          type="button"
          className="primary-btn"
          onClick={approve}
          disabled={busy}
          style={{ fontSize: 12, padding: "6px 16px" }}
        >
          {busy ? "…" : "✓  Approve & Resume"}
        </button>
        <button
          type="button"
          className="warn-btn"
          onClick={reject}
          disabled={busy}
          style={{ fontSize: 12, padding: "6px 16px" }}
        >
          ✕  Reject
        </button>
      </div>
    </div>
  );
}

/* ── Notify-tier card ───────────────────────────────────────────── */
function NotifyCard({ item, onDismiss }: { item: ApprovalItem; onDismiss: (id: string) => void }) {
  return (
    <div className="animate-fadeup" style={{
      border: "1px solid rgba(59,130,246,0.2)",
      borderRadius: 12,
      background: "rgba(239,246,255,0.5)",
      padding: "14px 18px",
      display: "flex",
      alignItems: "flex-start",
      gap: 12,
    }}>
      {/* Blue left accent */}
      <div style={{ width: 3, minHeight: 40, borderRadius: 2, background: "#3b82f6", flexShrink: 0, marginTop: 2 }} />

      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <TierBadge tier="notify" />
          <span style={{ fontSize: 11, color: "var(--t3)" }}>
            {item.age} · by <span style={{ color: "var(--t2)", fontWeight: 500 }}>{item.requestedBy}</span>
          </span>
        </div>
        <p style={{ fontSize: 13, color: "var(--t1)", lineHeight: 1.5, margin: 0 }}>{item.summary}</p>
      </div>

      <button
        type="button"
        onClick={() => onDismiss(item.id)}
        aria-label="Dismiss notification"
        style={{
          background: "transparent",
          border: "1px solid rgba(59,130,246,0.25)",
          borderRadius: 6,
          padding: "4px 10px",
          fontSize: 11,
          color: "#1d4ed8",
          cursor: "pointer",
          flexShrink: 0,
          marginTop: 2,
        }}
      >
        Dismiss
      </button>
    </div>
  );
}

/* ── Stat pill ──────────────────────────────────────────────────── */
function StatPill({ value, label, color }: { value: number; label: string; color: string }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      padding: "8px 16px", borderRadius: 10, background: "var(--canvas)",
      border: "1px solid var(--border)", minWidth: 72, gap: 2,
    }}>
      <span style={{ fontSize: 20, fontWeight: 700, color, letterSpacing: "-0.02em", lineHeight: 1 }}>{value}</span>
      <span style={{ fontSize: 10, color: "var(--t3)", fontWeight: 500, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</span>
    </div>
  );
}

/* ── Policy row item ────────────────────────────────────────────── */
function PolicyRow({ label, value, on }: { label: string; value?: string; on?: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "7px 0", borderBottom: "1px solid var(--border)" }}>
      <span style={{ fontSize: 12, color: "var(--t2)" }}>{label}</span>
      {value !== undefined ? (
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--t1)", background: "rgba(0,0,0,0.04)", padding: "1px 8px", borderRadius: 6 }}>{value}</span>
      ) : (
        <span style={{
          fontSize: 11, fontWeight: 600, padding: "1px 8px", borderRadius: 100,
          background: on ? "rgba(22,163,74,0.1)" : "rgba(0,0,0,0.06)",
          color: on ? "#15803d" : "var(--t3)",
        }}>
          {on ? "ON" : "OFF"}
        </span>
      )}
    </div>
  );
}

/* ── Main page ─────────────────────────────────────────────────────── */
export default function AutomationsPage({ inbox, approvals, policy }: AutomationsPageProps): JSX.Element {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const dismiss = useCallback((id: string) => setDismissed((prev) => new Set([...prev, id])), []);

  const visible = approvals.filter((a) => !dismissed.has(a.id) && !dismissed.has(a.taskId));
  const pendingApprove = visible.filter((a) => a.tier === "approve");
  const pendingNotify  = visible.filter((a) => a.tier === "notify");

  const activeTasks    = inbox.filter((t) => !["complete","fail","reject"].some((s) => t.status.toLowerCase().includes(s)));
  const completedToday = inbox.length - activeTasks.length;
  const totalPending   = pendingApprove.length + pendingNotify.length;

  return (
    <section className="workspace-page">

      {/* ── Page header ─────────────────────────────────────────── */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div>
            <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--t1)", letterSpacing: "-0.02em", margin: 0 }}>Automations</h2>
            <p style={{ fontSize: 13, color: "var(--t3)", marginTop: 4 }}>
              Human-in-the-loop control center — approve, reject, or dismiss AI decisions before they proceed.
            </p>
          </div>
          {/* Live stats */}
          <div style={{ display: "flex", gap: 8 }}>
            <StatPill value={pendingApprove.length} label="Approvals" color={pendingApprove.length > 0 ? "#b91c1c" : "var(--t2)"} />
            <StatPill value={pendingNotify.length}  label="Notify"    color={pendingNotify.length  > 0 ? "#1d4ed8" : "var(--t2)"} />
            <StatPill value={activeTasks.length}    label="Active"    color="var(--t2)" />
          </div>
        </div>
      </div>

      {/* ── Urgent approval banner ───────────────────────────────── */}
      {pendingApprove.length > 0 && (
        <div style={{
          background: "rgba(220,38,38,0.05)", border: "1px solid rgba(220,38,38,0.2)",
          borderRadius: 10, padding: "10px 14px", marginBottom: 20,
          display: "flex", alignItems: "center", gap: 10,
        }}>
          <span style={{ fontSize: 16 }}>🔴</span>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#b91c1c" }}>
            {pendingApprove.length} task{pendingApprove.length > 1 ? "s" : ""} blocked — waiting for your decision
          </span>
        </div>
      )}

      {/* ── Pending human approvals ──────────────────────────────── */}
      {pendingApprove.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "var(--t3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Awaiting Approval
            </span>
            <span style={{
              fontSize: 11, fontWeight: 600, padding: "1px 7px", borderRadius: 100,
              background: "rgba(220,38,38,0.12)", color: "#b91c1c",
            }}>{pendingApprove.length}</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {pendingApprove.map((item) => (
              <ApproveCard key={item.id} item={item} onDone={dismiss} />
            ))}
          </div>
        </div>
      )}

      {/* ── Gate notifications ───────────────────────────────────── */}
      {pendingNotify.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "var(--t3)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Gate Notifications
            </span>
            <span style={{
              fontSize: 11, fontWeight: 600, padding: "1px 7px", borderRadius: 100,
              background: "rgba(59,130,246,0.12)", color: "#1d4ed8",
            }}>{pendingNotify.length}</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {pendingNotify.map((item) => (
              <NotifyCard key={item.id} item={item} onDismiss={dismiss} />
            ))}
          </div>
        </div>
      )}

      {/* ── All-clear empty state ────────────────────────────────── */}
      {totalPending === 0 && (
        <div style={{
          textAlign: "center", padding: "40px 24px", marginBottom: 24,
          border: "1px dashed var(--border)", borderRadius: 14,
          background: "rgba(22,163,74,0.02)",
        }}>
          <div style={{ fontSize: 32, marginBottom: 10 }}>✅</div>
          <p style={{ fontSize: 14, fontWeight: 600, color: "var(--t1)", margin: "0 0 4px" }}>All clear</p>
          <p style={{ fontSize: 13, color: "var(--t3)", margin: 0 }}>
            No pending approvals or notifications. The engine is running autonomously.
          </p>
        </div>
      )}

      {/* ── Summary strip ───────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>

        {/* Queue health */}
        <div className="workspace-card">
          <div className="workspace-card-head">
            <div>
              <h3>Queue health</h3>
              <p>Live task counts from inbox</p>
            </div>
            <span style={{
              width: 8, height: 8, borderRadius: "50%", flexShrink: 0, marginTop: 4,
              background: activeTasks.length > 0 ? "#22c55e" : "var(--border-strong)",
              boxShadow: activeTasks.length > 0 ? "0 0 0 3px rgba(34,197,94,0.2)" : "none",
            }} />
          </div>
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
            {[
              ["Active tasks",       activeTasks.length,    "var(--t1)"],
              ["Completed / failed", completedToday,        "var(--t3)"],
              ["Pending approvals",  pendingApprove.length, pendingApprove.length > 0 ? "#b91c1c" : "var(--t3)"],
              ["Notifications",      pendingNotify.length,  pendingNotify.length > 0 ? "#1d4ed8" : "var(--t3)"],
            ].map(([label, val, color]) => (
              <div key={String(label)} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ fontSize: 12, color: "var(--t3)" }}>{String(label)}</span>
                <span style={{ fontSize: 13, fontWeight: 700, color: String(color) }}>{String(val)}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Policy snapshot */}
        <div className="workspace-card">
          <div className="workspace-card-head">
            <div>
              <h3>Governance policy</h3>
              <p>Active from control plane</p>
            </div>
            <span style={{
              fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 100,
              background: "rgba(79,70,229,0.08)", color: "#4338ca",
            }}>
              {policy?.defaultTier ?? "—"}
            </span>
          </div>
          {policy ? (
            <div style={{ marginTop: 8 }}>
              <PolicyRow label="Default tier"          value={policy.defaultTier} />
              <PolicyRow label="Deep rigour"           on={policy.deepRigour} />
              <PolicyRow label="High-risk approvals"   on={policy.requireApprovalHighRisk} />
              <PolicyRow label="Prod secret approvals" on={policy.requireApprovalProdSecrets} />
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingTop: 8 }}>
                <span style={{ fontSize: 12, color: "var(--t3)" }}>Notify channels</span>
                <div style={{ display: "flex", gap: 4 }}>
                  {policy.notifyChannels?.length
                    ? policy.notifyChannels.map((ch) => (
                        <span key={ch} style={{ fontSize: 10, fontWeight: 600, padding: "1px 6px", borderRadius: 4, background: "rgba(0,0,0,0.06)", color: "var(--t2)" }}>{ch}</span>
                      ))
                    : <span style={{ fontSize: 11, color: "var(--t4)" }}>none</span>
                  }
                </div>
              </div>
            </div>
          ) : (
            <p style={{ fontSize: 12, color: "var(--t4)", marginTop: 10 }}>Policy data unavailable.</p>
          )}
        </div>
      </div>
    </section>
  );
}
