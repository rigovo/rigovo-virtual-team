/* ------------------------------------------------------------------ */
/*  AgentDetailPanel — right-side panel in the Neural Calibration Map  */
/*  Shows: selected agent output · files written · gate results         */
/*  When nothing selected: shows current running agent automatically    */
/* ------------------------------------------------------------------ */
import type { TaskStep, GateResult } from "../types";
import type { CollaborationData, CostData } from "./AgentTimeline";
import ResponseRenderer from "./ResponseRenderer";

/* ═══════════════════════════════════════════════════════════════════ */
/*  Role metadata — Professional titles + colours                       */
/* ═══════════════════════════════════════════════════════════════════ */
const ROLE_META: Record<string, { label: string; subtitle: string; color: string; icon: string }> = {
  master:   { label: "Chief Architect",     subtitle: "Orchestrator",        color: "#4ade80", icon: "◎"  },
  planner:  { label: "Project Manager",     subtitle: "Planning & Design",   color: "#a78bfa", icon: "🧠" },
  coder:    { label: "Software Engineer",   subtitle: "Implementation",      color: "#4ade80", icon: "💻" },
  reviewer: { label: "Code Reviewer",       subtitle: "Code Review",         color: "#60a5fa", icon: "🔎" },
  security: { label: "Security Engineer",   subtitle: "Security Audit",      color: "#f87171", icon: "🔐" },
  qa:       { label: "QA Engineer",         subtitle: "Quality Assurance",   color: "#fb923c", icon: "🧪" },
  devops:   { label: "DevOps Engineer",     subtitle: "Infrastructure",      color: "#818cf8", icon: "⚙️"  },
  sre:      { label: "SRE Engineer",        subtitle: "Reliability",         color: "#2dd4bf", icon: "📈" },
  lead:     { label: "Tech Lead",           subtitle: "Technical Leadership",color: "#a3a3a3", icon: "🎯" },
  rigour:   { label: "Quality Gates",       subtitle: "Rigour Analysis",     color: "#22d3ee", icon: "⚡" },
  memory:   { label: "Knowledge Base",      subtitle: "Semantic Memory",     color: "#c084fc", icon: "🧬" },
  docs:     { label: "Technical Writer",    subtitle: "Documentation",       color: "#a8a29e", icon: "📝" },
};

/** Map of instance agent keyword → base role key (for "backend-engineer-1" etc.) */
const BASE_ROLE_KW: Record<string, string> = {
  backend: "coder", frontend: "coder", engineer: "coder", developer: "coder",
  dev: "coder", programmer: "coder", implementer: "coder",
  planner: "planner", architect: "planner",
  reviewer: "reviewer", review: "reviewer",
  qa: "qa", tester: "qa", test: "qa",
  security: "security", sec: "security",
  devops: "devops", infra: "devops", deploy: "devops",
  sre: "sre", reliability: "sre", ops: "sre",
  docs: "docs", documentation: "docs", writer: "docs",
  lead: "lead", coordinator: "lead",
};

function roleMeta(role: string) {
  const r = role.toLowerCase();
  if (ROLE_META[r]) return ROLE_META[r];

  // Instance agent resolution: "backend-engineer-1" → coder
  const parts = r.split("-").filter(p => !/^\d+$/.test(p));
  for (const part of parts) {
    const baseKey = BASE_ROLE_KW[part];
    if (baseKey && ROLE_META[baseKey]) {
      const humanLabel = role.split("-").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
      return { ...ROLE_META[baseKey], label: humanLabel };
    }
  }

  return { label: r.charAt(0).toUpperCase() + r.slice(1), subtitle: "Agent", color: "#a3a3a3", icon: "🤖" };
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
  const label = gate.gate === "persona" ? "persona boundary"
    : gate.gate === "contract" ? "output contract"
    : gate.gate === "no-files" ? "no files"
    : gate.gate;
  return (
    <span
      className="adp-gate-pill"
      style={{ color: gate.passed ? "#4ade80" : "#f87171",
               borderColor: gate.passed ? "#4ade8033" : "#f8717133",
               background: gate.passed ? "#4ade8010" : "#f8717110" }}
      title={gate.message}
    >
      {gate.passed ? "✓" : "✗"} {label}
      {gate.violation_count != null && gate.violation_count > 0 && !gate.passed && (
        <span style={{ opacity: 0.7, marginLeft: 3 }}>({gate.violation_count})</span>
      )}
      {gate.deep && (
        <span style={{ opacity: 0.6, marginLeft: 3, fontSize: "0.75em" }}>DEEP</span>
      )}
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
          const otherRaw   = isRequest ? e.to_role : e.from_role;
          const otherLabel = roleMeta(otherRaw || "agent").label;
          const color      = isDebate ? "#fb923c" : "#60a5fa";
          const msg        = e.message_id ? msgMap[e.message_id] : null;
          const snippet    = msg?.content ?? (isDebate ? e.reviewer_feedback : null) ?? "";
          return (
            <div key={i} className="adp-consult-card">
              <div className="adp-consult-row">
                <span className="adp-consult-arrow" style={{ color }}>{arrow}</span>
                <span className="adp-consult-peer" style={{ color }}>
                  {isDebate ? `Debate rd ${e.round ?? ""}` : otherLabel}
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
          const fromLabel = roleMeta(e.from_role ?? "system").label;
          const toLabel   = roleMeta(e.to_role ?? "agent").label;
          const msg  = e.message_id ? msgMap[e.message_id] : null;
          const text = msg?.content ?? (isDebate ? (e.reviewer_feedback ?? "") : "");
          return (
            <div key={i} className="adp-comms-item">
              <div className="adp-comms-header">
                {isDebate ? (
                  <span className="adp-comms-badge debate">Debate rd {e.round ?? i + 1}</span>
                ) : (
                  <span className="adp-comms-badge consult">{fromLabel} → {toLabel}</span>
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
/*  ExecutionLog — Phase 14 verification: commands run + exit codes      */
/* ═══════════════════════════════════════════════════════════════════ */
function ExecutionLogSection({ step }: { step: TaskStep }) {
  if (!step.execution_log || step.execution_log.length === 0) return null;

  const statusColor = step.execution_verified ? "#4ade80" : "#a3a3a3";
  const statusLabel = step.execution_verified ? "Verified" : "Unverified";

  return (
    <div className="adp-section">
      <div className="adp-section-hdr">
        <span className="adp-section-icon">⚙️</span>
        <span className="adp-section-title">Execution Log</span>
        <span className="adp-gate-summary" style={{ color: statusColor }}>
          {statusLabel}
        </span>
      </div>
      <div className="adp-exec-log">
        {step.execution_log.map((entry, i) => (
          <div key={i} className="adp-exec-entry">
            <div className="adp-exec-cmd">
              <span className="adp-exec-cmd-text" title={entry.command}>
                {entry.command.length > 60 ? `${entry.command.substring(0, 57)}…` : entry.command}
              </span>
              <span
                className="adp-exec-code"
                style={{
                  background: entry.exit_code === 0 ? "#4ade8020" : "#f8717120",
                  color: entry.exit_code === 0 ? "#4ade80" : "#f87171",
                }}
              >
                {entry.exit_code === 0 ? "✓" : "✗"} {entry.exit_code}
              </span>
            </div>
            {entry.summary && (
              <p className="adp-exec-summary">{entry.summary.substring(0, 120)}</p>
            )}
          </div>
        ))}
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
  const totalViolations = step.gate_results.reduce((sum, g) => sum + (g.violation_count ?? 0), 0);
  const hasPersona = step.gate_results.some(g => g.gate === "persona");
  const hasDeep = step.gate_results.some(g => g.deep);
  if (step.gate_results.length === 0) return null;
  return (
    <div className="adp-section">
      <div className="adp-section-hdr">
        <span className="adp-section-icon">⚡</span>
        <span className="adp-section-title">
          Rigour gates
          {hasDeep && <span style={{ fontSize: "0.75em", opacity: 0.6, marginLeft: 4 }}>(deep)</span>}
        </span>
        <span className="adp-gate-summary" style={{ color: failed > 0 ? "#f87171" : "#4ade80" }}>
          {failed > 0
            ? hasPersona
              ? "persona violation"
              : totalViolations > 0
                ? `${totalViolations} violation${totalViolations === 1 ? "" : "s"}`
                : `${failed} failed`
            : `${passed} passed`}
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
          <ExecutionLogSection step={step} />
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
