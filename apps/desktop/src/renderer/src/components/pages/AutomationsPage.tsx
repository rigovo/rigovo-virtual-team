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
  onOpenTask?: (taskId: string) => void;
  onRefreshQueue?: () => Promise<string | null>;
}

/* ── Per-card loading + dismissed state ─────────────────────────── */
function useApprovalAction(taskId: string, onDone: (id: string) => void) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const act = useCallback(
    async (action: "approve" | "deny") => {
      if (busy) return;
      setBusy(true);
      setError("");
      try {
        const res = await fetch(`${API_BASE}/v1/tasks/${taskId}/${action}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ actor: "operator" }),
        });
        if (!res.ok) {
          let detail = `HTTP ${res.status}`;
          try {
            const body = await res.json();
            if (typeof body?.detail === "string") detail = body.detail;
          } catch {
            /* keep fallback detail */
          }
          setError(`Action failed: ${detail}`);
          return;
        }
        onDone(taskId);
      } catch {
        setError("Action failed: network error");
      } finally {
        setBusy(false);
      }
    },
    [busy, taskId, onDone],
  );

  return { busy, error, approve: () => act("approve"), reject: () => act("deny") };
}

/* ── Tier badge ─────────────────────────────────────────────────── */
function TierBadge({ tier }: { tier: string }) {
  const cfg: Record<
    string,
    { bg: string; color: string; label: string; dot: string }
  > = {
    approve: {
      bg: "rgba(220,38,38,0.08)",
      color: "#b91c1c",
      label: "Approval Required",
      dot: "#ef4444",
    },
    notify: {
      bg: "var(--accent-bg)",
      color: "var(--accent-text)",
      label: "Notification",
      dot: "var(--accent)",
    },
    auto: {
      bg: "rgba(0,0,0,0.05)",
      color: "var(--t2)",
      label: "Auto",
      dot: "var(--t3)",
    },
  };
  const c = cfg[tier] ?? cfg.auto;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "2px 8px",
        borderRadius: 100,
        background: c.bg,
        color: c.color,
        fontSize: 11,
        fontWeight: 600,
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: c.dot,
          flexShrink: 0,
        }}
      />
      {c.label}
    </span>
  );
}

/* ── Rich Approve-tier card ─────────────────────────────────────── */
function ApproveCard({
  item,
  onDone,
  onOpenTask,
}: {
  item: ApprovalItem;
  onDone: (id: string) => void;
  onOpenTask?: (taskId: string) => void;
}) {
  const { busy, error, approve, reject } = useApprovalAction(item.taskId, onDone);

  return (
    <div
      className="animate-fadeup animate-border-pulse"
      style={{
        border: "1.5px solid rgba(220,38,38,0.25)",
        borderRadius: 12,
        background: "rgba(220,38,38,0.05)",
        padding: "16px 18px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      {/* Header row */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          <TierBadge tier="approve" />
          <span style={{ fontSize: 11, color: "var(--t3)" }}>
            {item.age} · by{" "}
            <span style={{ color: "var(--t2)", fontWeight: 500 }}>
              {item.requestedBy}
            </span>
          </span>
        </div>
        <span
          style={{
            fontSize: 10,
            fontWeight: 600,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            color: "#b91c1c",
            background: "rgba(220,38,38,0.08)",
            padding: "2px 8px",
            borderRadius: 6,
          }}
        >
          Blocking
        </span>
      </div>

      {/* Summary */}
      <p
        style={{ fontSize: 13, color: "var(--t1)", lineHeight: 1.6, margin: 0 }}
      >
        {item.summary}
      </p>

      {/* Task reference */}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span
          style={{
            fontSize: 10,
            fontWeight: 600,
            color: "var(--t4)",
            textTransform: "uppercase",
            letterSpacing: "0.05em",
          }}
        >
          Task
        </span>
        <code
          style={{
            fontSize: 11,
            color: "var(--t3)",
            background: "rgba(0,0,0,0.04)",
            padding: "1px 6px",
            borderRadius: 4,
          }}
        >
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
          {busy ? "..." : "Approve & Resume"}
        </button>
        <button
          type="button"
          className="warn-btn"
          onClick={reject}
          disabled={busy}
          style={{ fontSize: 12, padding: "6px 16px" }}
        >
          Reject
        </button>
        {onOpenTask && (
          <button
            type="button"
            className="ghost-btn"
            onClick={() => onOpenTask(item.taskId)}
            disabled={busy}
            style={{ fontSize: 12, padding: "6px 12px" }}
          >
            Open task
          </button>
        )}
      </div>
      {error && (
        <p style={{ margin: 0, fontSize: 11, color: "#b91c1c" }}>{error}</p>
      )}
    </div>
  );
}

/* ── Notify-tier card ───────────────────────────────────────────── */
function NotifyCard({
  item,
  onDismiss,
  onOpenTask,
}: {
  item: ApprovalItem;
  onDismiss: (id: string) => void;
  onOpenTask?: (taskId: string) => void;
}) {
  return (
    <div
      className="animate-fadeup"
      style={{
        border: "1px solid var(--border)",
        borderRadius: 12,
        background: "var(--canvas)",
        padding: "14px 18px",
        display: "flex",
        alignItems: "flex-start",
        gap: 12,
      }}
    >
      {/* Blue left accent */}
      <div
        style={{
          width: 3,
          minHeight: 40,
          borderRadius: 2,
          background: "var(--accent)",
          flexShrink: 0,
          marginTop: 2,
        }}
      />

      <div
        style={{
          flex: 1,
          minWidth: 0,
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <TierBadge tier="notify" />
          <span style={{ fontSize: 11, color: "var(--t3)" }}>
            {item.age} · by{" "}
            <span style={{ color: "var(--t2)", fontWeight: 500 }}>
              {item.requestedBy}
            </span>
          </span>
        </div>
        <p
          style={{
            fontSize: 13,
            color: "var(--t1)",
            lineHeight: 1.5,
            margin: 0,
          }}
        >
          {item.summary}
        </p>
      </div>

      <div style={{ display: "flex", gap: 6, flexShrink: 0, marginTop: 2 }}>
        {onOpenTask && (
          <button
            type="button"
            onClick={() => onOpenTask(item.taskId)}
            className="ghost-btn"
            style={{ padding: "4px 10px", fontSize: 11 }}
          >
            Open
          </button>
        )}
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
            color: "var(--accent-text)",
            cursor: "pointer",
          }}
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}

/* ── Stat pill ──────────────────────────────────────────────────── */
function StatPill({
  value,
  label,
  color,
}: {
  value: number;
  label: string;
  color: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        padding: "8px 16px",
        borderRadius: 10,
        background: "var(--canvas)",
        border: "1px solid var(--border)",
        minWidth: 72,
        gap: 2,
      }}
    >
      <span
        style={{
          fontSize: 20,
          fontWeight: 700,
          color,
          letterSpacing: "-0.02em",
          lineHeight: 1,
        }}
      >
        {value}
      </span>
      <span
        style={{
          fontSize: 10,
          color: "var(--t3)",
          fontWeight: 500,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}
      >
        {label}
      </span>
    </div>
  );
}

/* ── Policy row item ────────────────────────────────────────────── */
function PolicyRow({
  label,
  value,
  on,
}: {
  label: string;
  value?: string;
  on?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "7px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <span style={{ fontSize: 12, color: "var(--t2)" }}>{label}</span>
      {value !== undefined ? (
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: "var(--t1)",
            background: "rgba(0,0,0,0.04)",
            padding: "1px 8px",
            borderRadius: 6,
          }}
        >
          {value}
        </span>
      ) : (
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            padding: "1px 8px",
            borderRadius: 100,
            background: on ? "var(--accent-bg)" : "rgba(0,0,0,0.06)",
            color: on ? "var(--accent-text)" : "var(--t3)",
          }}
        >
          {on ? "ON" : "OFF"}
        </span>
      )}
    </div>
  );
}

/* ── Main page ─────────────────────────────────────────────────────── */
export default function AutomationsPage({
  inbox,
  approvals,
  policy,
  onOpenTask,
  onRefreshQueue,
}: AutomationsPageProps): JSX.Element {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [lane, setLane] = useState<"all" | "approve" | "notify">("all");
  const [refreshing, setRefreshing] = useState(false);
  const [pageMsg, setPageMsg] = useState("");
  const dismiss = useCallback(
    (id: string) => setDismissed((prev) => new Set([...prev, id])),
    [],
  );
  const refreshNow = useCallback(async () => {
    if (!onRefreshQueue || refreshing) return;
    setRefreshing(true);
    setPageMsg("");
    const err = await onRefreshQueue();
    setRefreshing(false);
    setPageMsg(err ? err : "Queue refreshed.");
    window.setTimeout(() => setPageMsg(""), 1800);
  }, [onRefreshQueue, refreshing]);

  const visible = approvals.filter(
    (a) => !dismissed.has(a.id) && !dismissed.has(a.taskId),
  );
  const pendingApprove = visible.filter((a) => a.tier === "approve");
  const pendingNotify = visible.filter((a) => a.tier === "notify");
  const shownApprove = lane === "notify" ? [] : pendingApprove;
  const shownNotify = lane === "approve" ? [] : pendingNotify;

  const activeTasks = inbox.filter(
    (t) =>
      !["complete", "fail", "reject"].some((s) =>
        t.status.toLowerCase().includes(s),
      ),
  );
  const completedToday = inbox.length - activeTasks.length;
  const totalPending = pendingApprove.length + pendingNotify.length;

  return (
    <section className="workspace-page">
      {/* ── Page header ─────────────────────────────────────────── */}
      <div style={{ marginBottom: 20 }}>
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <div>
            <h2
              style={{
                fontSize: 16,
                fontWeight: 700,
                color: "var(--t1)",
                letterSpacing: "-0.02em",
                margin: 0,
              }}
            >
              Automations
            </h2>
            <p style={{ fontSize: 13, color: "var(--t3)", marginTop: 4 }}>
              Human-in-the-loop control center — approve, reject, or dismiss AI
              decisions before they proceed.
            </p>
          </div>
          {/* Live stats */}
          <div style={{ display: "flex", gap: 8 }}>
            <StatPill
              value={pendingApprove.length}
              label="Approvals"
              color={pendingApprove.length > 0 ? "#b91c1c" : "var(--t2)"}
            />
            <StatPill
              value={pendingNotify.length}
              label="Notify"
              color={
                pendingNotify.length > 0 ? "var(--accent-text)" : "var(--t2)"
              }
            />
            <StatPill
              value={activeTasks.length}
              label="Active"
              color="var(--t2)"
            />
          </div>
        </div>
      </div>
      {pageMsg && (
        <div
          style={{
            marginBottom: 12,
            border: "1px solid var(--border)",
            borderRadius: 8,
            background: "var(--canvas)",
            padding: "8px 10px",
            fontSize: 12,
            color: "var(--t3)",
          }}
        >
          {pageMsg}
        </div>
      )}

      {/* ── Urgent approval banner ───────────────────────────────── */}
      {shownApprove.length > 0 && (
        <div
          style={{
            background: "rgba(220,38,38,0.05)",
            border: "1px solid rgba(220,38,38,0.2)",
            borderRadius: 10,
            padding: "10px 14px",
            marginBottom: 20,
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: "#ef4444",
              flexShrink: 0,
            }}
          />
          <span style={{ fontSize: 13, fontWeight: 600, color: "#b91c1c" }}>
            {shownApprove.length} task{shownApprove.length > 1 ? "s" : ""}{" "}
            blocked — waiting for your decision
          </span>
        </div>
      )}

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
          gap: 10,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", gap: 6 }}>
          {(
            [
              ["all", "All queue"],
              ["approve", "Blocking only"],
              ["notify", "Notify only"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className="ghost-btn"
              onClick={() => setLane(id)}
              style={
                lane === id
                  ? {
                      borderColor: "var(--accent)",
                      color: "var(--accent-text)",
                      background: "var(--accent-bg)",
                    }
                  : undefined
              }
            >
              {label}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {onRefreshQueue && (
            <button
              type="button"
              className="ghost-btn"
              onClick={() => void refreshNow()}
              disabled={refreshing}
            >
              {refreshing ? "Refreshing..." : "Refresh queue"}
            </button>
          )}
          {shownNotify.length > 0 && (
            <button
              type="button"
              className="ghost-btn"
              onClick={() =>
                setDismissed(
                  (prev) => new Set([...prev, ...shownNotify.map((n) => n.id)]),
                )
              }
            >
              Dismiss all notifications
            </button>
          )}
        </div>
      </div>

      {/* ── Pending human approvals ──────────────────────────────── */}
      {shownApprove.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 10,
            }}
          >
            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: "var(--t3)",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
              }}
            >
              Awaiting Approval
            </span>
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                padding: "1px 7px",
                borderRadius: 100,
                background: "rgba(220,38,38,0.12)",
                color: "#b91c1c",
              }}
            >
              {shownApprove.length}
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {shownApprove.map((item) => (
              <ApproveCard
                key={item.id}
                item={item}
                onDone={dismiss}
                onOpenTask={onOpenTask}
              />
            ))}
          </div>
        </div>
      )}

      {/* ── Gate notifications ───────────────────────────────────── */}
      {shownNotify.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 10,
            }}
          >
            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: "var(--t3)",
                textTransform: "uppercase",
                letterSpacing: "0.06em",
              }}
            >
              Gate Notifications
            </span>
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                padding: "1px 7px",
                borderRadius: 100,
                background: "var(--accent-bg)",
                color: "var(--accent-text)",
              }}
            >
              {shownNotify.length}
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {shownNotify.map((item) => (
              <NotifyCard
                key={item.id}
                item={item}
                onDismiss={dismiss}
                onOpenTask={onOpenTask}
              />
            ))}
          </div>
        </div>
      )}

      {/* ── All-clear empty state ────────────────────────────────── */}
      {totalPending === 0 && (
        <div
          style={{
            textAlign: "center",
            padding: "40px 24px",
            marginBottom: 24,
            border: "1px dashed var(--border)",
            borderRadius: 14,
            background: "rgba(0,0,0,0.01)",
          }}
        >
          <p
            style={{
              fontSize: 14,
              fontWeight: 600,
              color: "var(--t1)",
              margin: "0 0 4px",
            }}
          >
            All clear
          </p>
          <p style={{ fontSize: 13, color: "var(--t3)", margin: 0 }}>
            No pending approvals or notifications. The engine is running
            autonomously.
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
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                flexShrink: 0,
                marginTop: 4,
                background:
                  activeTasks.length > 0
                    ? "var(--accent)"
                    : "var(--border-strong)",
                boxShadow:
                  activeTasks.length > 0
                    ? "0 0 0 3px var(--accent-bg)"
                    : "none",
              }}
            />
          </div>
          <div
            style={{
              marginTop: 12,
              display: "flex",
              flexDirection: "column",
              gap: 6,
            }}
          >
            {[
              ["Active tasks", activeTasks.length, "var(--t1)"],
              ["Completed / failed", completedToday, "var(--t3)"],
              [
                "Pending approvals",
                pendingApprove.length,
                pendingApprove.length > 0 ? "#b91c1c" : "var(--t3)",
              ],
              [
                "Notifications",
                pendingNotify.length,
                pendingNotify.length > 0 ? "var(--accent-text)" : "var(--t3)",
              ],
            ].map(([label, val, color]) => (
              <div
                key={String(label)}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <span style={{ fontSize: 12, color: "var(--t3)" }}>
                  {String(label)}
                </span>
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: 700,
                    color: String(color),
                  }}
                >
                  {String(val)}
                </span>
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
            <span
              style={{
                fontSize: 10,
                fontWeight: 600,
                padding: "2px 8px",
                borderRadius: 100,
                background: "var(--accent-bg)",
                color: "var(--accent-text)",
              }}
            >
              {policy?.defaultTier ?? "—"}
            </span>
          </div>
          {policy ? (
            <div style={{ marginTop: 8 }}>
              <PolicyRow label="Default tier" value={policy.defaultTier} />
              <PolicyRow label="Deep rigour" on={policy.deepRigour} />
              <PolicyRow
                label="High-risk approvals"
                on={policy.requireApprovalHighRisk}
              />
              <PolicyRow
                label="Prod secret approvals"
                on={policy.requireApprovalProdSecrets}
              />
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  paddingTop: 8,
                }}
              >
                <span style={{ fontSize: 12, color: "var(--t3)" }}>
                  Notify channels
                </span>
                <div style={{ display: "flex", gap: 4 }}>
                  {policy.notifyChannels?.length ? (
                    policy.notifyChannels.map((ch) => (
                      <span
                        key={ch}
                        style={{
                          fontSize: 10,
                          fontWeight: 600,
                          padding: "1px 6px",
                          borderRadius: 4,
                          background: "rgba(0,0,0,0.06)",
                          color: "var(--t2)",
                        }}
                      >
                        {ch}
                      </span>
                    ))
                  ) : (
                    <span style={{ fontSize: 11, color: "var(--t4)" }}>
                      none
                    </span>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <p style={{ fontSize: 12, color: "var(--t4)", marginTop: 10 }}>
              Policy data unavailable.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
