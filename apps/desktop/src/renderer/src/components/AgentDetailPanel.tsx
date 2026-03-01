/* ------------------------------------------------------------------ */
/*  AgentDetailPanel — right-side panel in the Neural Calibration Map  */
/*  Shows: selected agent output · files written · gate results         */
/*  When nothing selected: shows current running agent automatically    */
/* ------------------------------------------------------------------ */
import type { TaskStep, GateResult } from "../types";
import type { CollaborationData, CostData } from "./AgentTimeline";
import ResponseRenderer from "./ResponseRenderer";

/* ═══════════════════════════════════════════════════════════════════ */
/*  Role metadata — Matrix codenames + colours                          */
/* ═══════════════════════════════════════════════════════════════════ */
const ROLE_META: Record<string, { label: string; subtitle: string; color: string; icon: string }> = {
  master:   { label: "Master Agent", subtitle: "Orchestrator",        color: "#4ade80", icon: "◎"  },
  planner:  { label: "Planner",      subtitle: "Architecture",        color: "#a78bfa", icon: "🧠" },
  coder:    { label: "Coder",        subtitle: "Engineering",         color: "#4ade80", icon: "💻" },
  reviewer: { label: "Reviewer",     subtitle: "Code Review",         color: "#60a5fa", icon: "🔎" },
  security: { label: "Security",     subtitle: "Audit",               color: "#f87171", icon: "🔐" },
  qa:       { label: "QA",           subtitle: "Quality Assurance",   color: "#fb923c", icon: "🧪" },
  devops:   { label: "DevOps",       subtitle: "Infrastructure",      color: "#f87171", icon: "⚙️"  },
  sre:      { label: "SRE",          subtitle: "Reliability",         color: "#2dd4bf", icon: "📈" },
  lead:     { label: "Lead",         subtitle: "Tech Lead",           color: "#a3a3a3", icon: "🎯" },
  rigour:   { label: "Rigour",       subtitle: "Quality Gates",       color: "#22d3ee", icon: "⚡" },
  memory:   { label: "Memory",       subtitle: "Context Store",       color: "#c084fc", icon: "🧬" },
};

function roleMeta(role: string) {
  const r = role.toLowerCase();
  return ROLE_META[r] ?? { label: r.charAt(0).toUpperCase() + r.slice(1), subtitle: "Agent", color: "#a3a3a3", icon: "🤖" };
}

/* ═══════════════════════════════════════════════════════════════════ */
/*  Props                                                               */
/* ═══════════════════════════════════════════════════════════════════ */
export interface AgentDetailPanelProps {
  steps:         TaskStep[];
  taskStatus:    string;
  selectedRole:  string | null;         // null = auto-select running agent
  collab:        CollaborationData | null;
  costs:         CostData | null;
  totalFiles:    number;
  replanCount:   number;
  onOpenFiles:   (agent: string, files: string[]) => void;
  onApprove?:    () => void;
  onReject?:     () => void;
  isApproval:    boolean;
}

/* ═══════════════════════════════════════════════════════════════════ */
/*  Sub-components                                                      */
/* ═══════════════════════════════════════════════════════════════════ */

function GatePill({ gate }: { gate: GateResult }) {
  return (
    <span
      className="adp-gate-pill"
      style={{ color: gate.passed ? "#4ade80" : "#f87171",
               borderColor: gate.passed ? "#4ade8033" : "#f8717133",
               background: gate.passed ? "#4ade8010" : "#f8717110" }}
      title={gate.message}
    >
      {gate.passed ? "✓" : "✗"} {gate.gate}
    </span>
  );
}

function FileList({ files, onOpen, agent }: { files: string[]; onOpen: () => void; agent: string }) {
  if (files.length === 0) return null;
  return (
    <div className="adp-section">
      <div className="adp-section-hdr">
        <span className="adp-section-icon">📁</span>
        <span className="adp-section-title">Files written</span>
        <button type="button" className="adp-files-btn" onClick={onOpen}>
          View {files.length} file{files.length !== 1 ? "s" : ""}
        </button>
      </div>
      <div className="adp-file-list">
        {files.slice(0, 8).map(f => (
          <span key={f} className="adp-file-chip" title={f}>
            {f.split("/").pop() ?? f}
          </span>
        ))}
        {files.length > 8 && (
          <span className="adp-file-chip adp-file-more">+{files.length - 8} more</span>
        )}
      </div>
    </div>
  );
}

function ConsultationList({ role, collab }: { role: string; collab: CollaborationData | null }) {
  if (!collab) return null;
  const events = collab.events.filter(
    e => e.from_role === role || e.to_role === role
  ).slice(-6);
  if (events.length === 0) return null;

  const msgMap = Object.fromEntries(collab.messages.map(m => [m.id, m]));

  return (
    <div className="adp-section">
      <div className="adp-section-hdr">
        <span className="adp-section-icon">💬</span>
        <span className="adp-section-title">Consultations</span>
        <span className="adp-consult-count">{events.length}</span>
      </div>
      <div className="adp-consult-list">
        {events.map((e, i) => {
          const isRequest  = e.type === "agent_consult_requested";
          const isResponse = e.type === "agent_consult_completed";
          const isDebate   = e.type === "debate_round";
          const arrow      = isRequest ? "→" : isResponse ? "←" : "↔";
          const other      = isRequest ? e.to_role : e.from_role;
          const color      = isDebate ? "#fb923c" : "#60a5fa";
          const msg        = e.message_id ? msgMap[e.message_id] : null;
          const snippet    = msg?.content ?? (isDebate ? e.reviewer_feedback : null) ?? "";
          return (
            <div key={i} className="adp-consult-card">
              <div className="adp-consult-row">
                <span className="adp-consult-arrow" style={{ color }}>{arrow}</span>
                <span className="adp-consult-peer" style={{ color }}>
                  {isDebate ? `Debate rd ${e.round ?? ""}` : (other ?? "agent")}
                </span>
                <span className="adp-consult-type">
                  {isDebate ? "debate" : isRequest ? "asked" : "replied"}
                </span>
              </div>
              {snippet && (
                <p className="adp-consult-snippet">
                  {snippet.slice(0, 140)}{snippet.length > 140 ? "…" : ""}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ── TeamCommsPanel — all inter-agent communications ── */
function TeamCommsPanel({ collab }: { collab: CollaborationData | null }) {
  if (!collab) return null;
  const comms = collab.events.filter(e =>
    ["agent_consult_requested", "agent_consult_completed", "debate_round"].includes(e.type)
  ).slice(-10);
  if (comms.length === 0) return null;

  const msgMap = Object.fromEntries(collab.messages.map(m => [m.id, m]));

  return (
    <div className="adp-section">
      <div className="adp-section-hdr">
        <span className="adp-section-icon">🗣️</span>
        <span className="adp-section-title">Team comms</span>
        <span className="adp-consult-count" style={{ background: "rgba(251,146,60,0.15)", color: "#fb923c" }}>
          {collab.summary.consult_requests + (collab.summary.debate_rounds > 0 ? collab.summary.debate_rounds : 0)}
        </span>
      </div>
      <div className="adp-comms-list">
        {comms.map((e, i) => {
          const isDebate = e.type === "debate_round";
          const from = e.from_role ?? "system";
          const to   = e.to_role ?? "";
          const msg  = e.message_id ? msgMap[e.message_id] : null;
          const text = msg?.content ?? (isDebate ? (e.reviewer_feedback ?? "") : "");
          return (
            <div key={i} className="adp-comms-item">
              <div className="adp-comms-header">
                {isDebate ? (
                  <span className="adp-comms-badge debate">Debate rd {e.round ?? i + 1}</span>
                ) : (
                  <span className="adp-comms-badge consult">{from} → {to}</span>
                )}
                <span className="adp-comms-kind">
                  {e.type === "agent_consult_requested" ? "asked" : e.type === "agent_consult_completed" ? "replied" : "feedback"}
                </span>
              </div>
              {text && (
                <p className="adp-comms-snippet">
                  {text.slice(0, 150)}{text.length > 150 ? "…" : ""}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════ */
/*  Empty state — no task running yet                                   */
/* ═══════════════════════════════════════════════════════════════════ */
function EmptyPanel({ taskStatus }: { taskStatus: string }) {
  const st = taskStatus.toLowerCase();
  const isComplete = st.includes("complete");
  const isFailed   = st.includes("fail") || st.includes("reject");

  return (
    <div className="adp-empty">
      <span className="adp-empty-icon">
        {isComplete ? "✓" : isFailed ? "✕" : "◎"}
      </span>
      <p className="adp-empty-title">
        {isComplete ? "Run complete" : isFailed ? "Run failed" : "Awaiting agents"}
      </p>
      <p className="adp-empty-desc">
        {isComplete
          ? "All agents finished. Click any node on the map to review its work."
          : isFailed
          ? "Click a failed node to see what went wrong."
          : "Click any active node on the map to see its output here."}
      </p>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════ */
/*  Approval banner                                                     */
/* ═══════════════════════════════════════════════════════════════════ */
function ApprovalBanner({ onApprove, onReject }: { onApprove?: () => void; onReject?: () => void }) {
  return (
    <div className="adp-approval">
      <div className="adp-approval-icon">✋</div>
      <p className="adp-approval-title">Your approval is needed</p>
      <p className="adp-approval-desc">
        Review the plan on the left, then approve to continue or reject to stop.
      </p>
      <div className="adp-approval-btns">
        <button type="button" className="adp-approve-btn" onClick={onApprove}>
          Approve &amp; Continue
        </button>
        <button type="button" className="adp-reject-btn" onClick={onReject}>
          Reject
        </button>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════ */
/*  AgentHeader — badge + status indicator + cost                       */
/* ═══════════════════════════════════════════════════════════════════ */
interface AgentHeaderProps {
  step:      TaskStep;
  role:      string;
  agentCost: number | undefined;
}

function statusColor(status: string): string {
  if (status === "complete") return "#4ade80";
  if (status === "failed")   return "#f87171";
  if (status === "running")  return "#60a5fa";
  return "#a3a3a3";
}

function AgentHeader({ step, role, agentCost }: AgentHeaderProps) {
  const meta = roleMeta(role);
  return (
    <div className="adp-agent-hdr">
      <div className="adp-agent-badge" style={{ borderColor: meta.color + "44", background: meta.color + "12" }}>
        <span className="adp-agent-icon">{meta.icon}</span>
        <div>
          <span className="adp-agent-codename" style={{ color: meta.color }}>{meta.label}</span>
          <span className="adp-agent-role">{meta.subtitle}</span>
        </div>
        <span className="adp-agent-status" style={{ color: statusColor(step.status) }}>
          {step.status === "running" ? (
            <span className="adp-running-dot"><span /><span /><span /></span>
          ) : step.status.toUpperCase()}
        </span>
      </div>
      {agentCost !== undefined && agentCost > 0 && (
        <span className="adp-cost-badge">${agentCost.toFixed(4)}</span>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════ */
/*  AgentOutput — output body section                                   */
/* ═══════════════════════════════════════════════════════════════════ */
function AgentOutput({ step }: { step: TaskStep }) {
  return (
    <div className="adp-section adp-output-section">
      <div className="adp-section-hdr">
        <span className="adp-section-icon">📋</span>
        <span className="adp-section-title">Output</span>
      </div>
      <div className="adp-output-body">
        {step.status === "running" && !step.output ? (
          <div className="adp-working">
            <span className="adp-working-dot"><span /><span /><span /></span>
            <span>Working…</span>
          </div>
        ) : step.output ? (
          <ResponseRenderer output={step.output} maxHeightClass="max-h-none" />
        ) : (
          <p className="adp-no-output">
            {step.status === "failed"
              ? "Agent stopped before producing output."
              : "No textual output for this step."}
          </p>
        )}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════ */
/*  GateSection — gate results summary + pills                          */
/* ═══════════════════════════════════════════════════════════════════ */
function GateSection({ step }: { step: TaskStep }) {
  const passed = step.gate_results.filter(g =>  g.passed).length;
  const failed = step.gate_results.filter(g => !g.passed).length;
  if (step.gate_results.length === 0) return null;
  return (
    <div className="adp-section">
      <div className="adp-section-hdr">
        <span className="adp-section-icon">⚡</span>
        <span className="adp-section-title">Rigour gates</span>
        <span className="adp-gate-summary" style={{ color: failed > 0 ? "#f87171" : "#4ade80" }}>
          {failed > 0 ? `${failed} failed` : `${passed} passed`}
        </span>
      </div>
      <div className="adp-gate-pills">
        {step.gate_results.map((g, i) => <GatePill key={i} gate={g} />)}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════ */
/*  Main component                                                      */
/* ═══════════════════════════════════════════════════════════════════ */
function resolveActiveRole(selectedRole: string | null, steps: TaskStep[]): string | null {
  if (selectedRole) return selectedRole;
  const running = steps.find(s => s.status === "running");
  if (running) return running.agent;
  const lastDone = steps.filter(s => s.status === "complete").slice(-1)[0];
  return lastDone?.agent ?? null;
}

export default function AgentDetailPanel({
  steps, taskStatus, selectedRole, collab, costs,
  totalFiles, replanCount, onOpenFiles, onApprove, onReject, isApproval,
}: AgentDetailPanelProps) {

  const activeRole = resolveActiveRole(selectedRole, steps);
  const step = activeRole ? steps.find(s => s.agent === activeRole) : null;
  const agentCost = activeRole ? costs?.per_agent?.[activeRole.toLowerCase()]?.cost_usd : undefined;

  return (
    <div className="adp-root">

      {isApproval && <ApprovalBanner onApprove={onApprove} onReject={onReject} />}

      {!activeRole && !isApproval && <EmptyPanel taskStatus={taskStatus} />}

      {activeRole && step && (
        <div className="adp-content">
          <AgentHeader step={step} role={activeRole} agentCost={agentCost} />
          <GateSection step={step} />
          <FileList
            files={step.files_changed}
            agent={activeRole}
            onOpen={() => onOpenFiles(activeRole, step.files_changed)}
          />
          <ConsultationList role={activeRole} collab={collab} />
          <AgentOutput step={step} />
          <TeamCommsPanel collab={collab} />
        </div>
      )}

      {!activeRole && !isApproval && collab && (
        <div className="adp-content">
          <TeamCommsPanel collab={collab} />
        </div>
      )}

      {/* ── Bottom summary strip ── */}
      {steps.length > 0 && (
        <div className="adp-summary-strip">
          <span className="adp-sum-item">
            <span className="adp-sum-num">{totalFiles}</span>
            <span className="adp-sum-lbl">files</span>
          </span>
          <span className="adp-sum-sep" />
          <span className="adp-sum-item">
            <span className="adp-sum-num">
              {steps.filter(s => s.status === "complete").length}/{steps.length}
            </span>
            <span className="adp-sum-lbl">agents</span>
          </span>
          {replanCount > 0 && (
            <>
              <span className="adp-sum-sep" />
              <span className="adp-sum-item">
                <span className="adp-sum-num" style={{ color: "#fb923c" }}>{replanCount}</span>
                <span className="adp-sum-lbl">replans</span>
              </span>
            </>
          )}
          {(collab?.summary?.debate_rounds ?? 0) > 0 && (
            <>
              <span className="adp-sum-sep" />
              <span className="adp-sum-item">
                <span className="adp-sum-num" style={{ color: "#fb923c" }}>
                  {collab!.summary.debate_rounds}
                </span>
                <span className="adp-sum-lbl">debates</span>
              </span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
