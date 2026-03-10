/* ------------------------------------------------------------------ */
/*  AgentDetailPanel — right-side panel in the Neural Calibration Map  */
/*  Shows: selected agent output · files written · gate results         */
/*  When nothing selected: shows current running agent automatically    */
/* ------------------------------------------------------------------ */
import type { TaskStep, GateResult } from "../types";
import type { CollaborationData, CostData } from "./AgentTimeline";
import ResponseRenderer from "./ResponseRenderer";
import {
  canonicalStepLabel as canonicalStepLabelForStep,
  resolveCanonicalRole,
} from "../lib/agentIdentity";

/* ═══════════════════════════════════════════════════════════════════ */
/*  Role metadata — Professional titles + colours                       */
/* ═══════════════════════════════════════════════════════════════════ */
const ROLE_META: Record<string, { label: string; subtitle: string; color: string; icon: string }> = {
  master:   { label: "Chief Architect",   subtitle: "Orchestrator",          color: "#4ade80", icon: "CA" },
  planner:  { label: "Project Manager",   subtitle: "Planning & Design",     color: "#a78bfa", icon: "PM" },
  coder:    { label: "Software Engineer", subtitle: "Implementation",        color: "#4ade80", icon: "SE" },
  reviewer: { label: "Code Reviewer",     subtitle: "Code Review",           color: "#60a5fa", icon: "CR" },
  security: { label: "Security Engineer", subtitle: "Security Audit",        color: "#f87171", icon: "SC" },
  qa:       { label: "QA Engineer",       subtitle: "Quality Assurance",     color: "#fb923c", icon: "QA" },
  devops:   { label: "DevOps Engineer",   subtitle: "Infrastructure",        color: "#818cf8", icon: "DO" },
  sre:      { label: "SRE Engineer",      subtitle: "Reliability",           color: "#2dd4bf", icon: "SR" },
  lead:     { label: "Tech Lead",         subtitle: "Technical Leadership",  color: "#a3a3a3", icon: "TL" },
  rigour:   { label: "Rigour Gates",      subtitle: "Rigour Analysis",       color: "#22d3ee", icon: "RG" },
  trinity:  { label: "Rigour Gates",      subtitle: "Rigour Analysis",       color: "#22d3ee", icon: "RG" },
  memory:   { label: "Knowledge Base",    subtitle: "Semantic Memory",       color: "#c084fc", icon: "KB" },
  docs:     { label: "Technical Writer",  subtitle: "Documentation",         color: "#a8a29e", icon: "TW" },
};

function roleMeta(role: string) {
  const r = resolveCanonicalRole(role);
  if (ROLE_META[r]) return ROLE_META[r];

  return { label: r.charAt(0).toUpperCase() + r.slice(1), subtitle: "Agent", color: "#a3a3a3", icon: "AG" };
}

function resolveBaseRole(role: string): string {
  return resolveCanonicalRole(role);
}

function isWorkRole(role: string): boolean {
  return !["master", "memory", "rigour", "trinity"].includes(role);
}

function canonicalStepLabel(step: TaskStep): string {
  return canonicalStepLabelForStep(step);
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
  activeFixPacket?: Record<string, unknown> | null;
  downstreamLockReason?: string | null;
  supervisoryDecisions?: Array<Record<string, unknown>>;
  spawnHistory?: Array<Record<string, unknown>>;
  debateHistory?: Array<Record<string, unknown>>;
  riskActionQueue?: Array<Record<string, unknown>>;
  requiredApprovalActions?: Array<Record<string, unknown>>;
  agentLearningUpdates?: Record<string, Array<Record<string, unknown>>>;
  behaviorChangeAudit?: Array<Record<string, unknown>>;
  roleLearningMetrics?: Record<string, Record<string, unknown>>;
  totalFiles:    number;
  expectedAgents?: number;
  nextExpectedRole?: string | null;
  nextExpectedReason?: string | null;
  replanCount:   number;
  onOpenFiles:   (agent: string, files: string[]) => void;
  onApprove?:    () => void;
  onReject?:     () => void;
  isApproval:    boolean;
}

function RuntimeTruthSection({
  activeRole,
  activeFixPacket,
  downstreamLockReason,
  supervisoryDecisions,
  spawnHistory,
  debateHistory,
  riskActionQueue,
  requiredApprovalActions,
  agentLearningUpdates,
  behaviorChangeAudit,
  roleLearningMetrics,
}: {
  activeRole: string | null;
  activeFixPacket?: Record<string, unknown> | null;
  downstreamLockReason?: string | null;
  supervisoryDecisions?: Array<Record<string, unknown>>;
  spawnHistory?: Array<Record<string, unknown>>;
  debateHistory?: Array<Record<string, unknown>>;
  riskActionQueue?: Array<Record<string, unknown>>;
  requiredApprovalActions?: Array<Record<string, unknown>>;
  agentLearningUpdates?: Record<string, Array<Record<string, unknown>>>;
  behaviorChangeAudit?: Array<Record<string, unknown>>;
  roleLearningMetrics?: Record<string, Record<string, unknown>>;
}) {
  const fixPacket = activeFixPacket && Object.keys(activeFixPacket).length > 0 ? activeFixPacket : null;
  const fixRole = String(fixPacket?.role || "").trim().toLowerCase();
  const visibleForRole =
    !activeRole || !fixRole || resolveCanonicalRole(activeRole) === resolveCanonicalRole(fixRole);
  const items = Array.isArray(fixPacket?.items)
    ? (fixPacket?.items as Array<Record<string, unknown>>)
    : [];
  const masterDecisions = (supervisoryDecisions ?? []).slice(-2);
  const riskEvents = (riskActionQueue ?? []).slice(-3);
  const approvalRequests = (requiredApprovalActions ?? []).filter(
    (item) => !activeRole || resolveCanonicalRole(String(item.role || "")) === resolveCanonicalRole(activeRole),
  );
  const spawnEvents = (spawnHistory ?? []).filter(
    (item) => !activeRole || resolveCanonicalRole(String(item.parent_role || item.role || "")) === resolveCanonicalRole(activeRole),
  ).slice(-3);
  const debateEvents = (debateHistory ?? []).filter(
    (item) =>
      !activeRole ||
      resolveCanonicalRole(String(item.role || item.from_role || item.to_role || "")) ===
        resolveCanonicalRole(activeRole),
  ).slice(-2);
  const roleLearning = Object.entries(agentLearningUpdates ?? {}).find(
    ([role]) => !activeRole || resolveCanonicalRole(role) === resolveCanonicalRole(activeRole),
  )?.[1] ?? [];
  const learningMetrics =
    Object.entries(roleLearningMetrics ?? {}).find(
      ([role]) => !activeRole || resolveCanonicalRole(role) === resolveCanonicalRole(activeRole),
    )?.[1] ?? null;
  const learningAudit = (behaviorChangeAudit ?? []).filter(
    (item) => !activeRole || resolveCanonicalRole(String(item.role || "")) === resolveCanonicalRole(activeRole),
  ).slice(-2);

  if (
    !fixPacket &&
    !downstreamLockReason &&
    masterDecisions.length === 0 &&
    riskEvents.length === 0 &&
    approvalRequests.length === 0 &&
    spawnEvents.length === 0 &&
    debateEvents.length === 0 &&
    roleLearning.length === 0 &&
    !learningMetrics &&
    learningAudit.length === 0
  ) {
    return null;
  }

  return (
    <div className="adp-section">
      <div className="adp-section-hdr">
        <span className="adp-section-icon">🧭</span>
        <span className="adp-section-title">Execution truth</span>
      </div>
      {fixPacket && visibleForRole && (
        <div className="adp-comms-item" style={{ marginTop: 8 }}>
          <div className="adp-comms-header">
            <span className="adp-comms-badge debate">Fix packet</span>
            <span className="adp-comms-kind">
              attempt {String(fixPacket.attempt || "1")}/{String(fixPacket.max_attempts || "1")}
            </span>
          </div>
          {downstreamLockReason && (
            <p className="adp-comms-snippet">{downstreamLockReason}</p>
          )}
          {items.slice(0, 3).map((item, idx) => (
            <p key={idx} className="adp-comms-snippet">
              {String(item.message || item.gate_id || "Remediation required")}
            </p>
          ))}
        </div>
      )}
      {!fixPacket && downstreamLockReason && (
        <p className="adp-no-output" style={{ marginTop: 6 }}>
          {downstreamLockReason}
        </p>
      )}
      {masterDecisions.length > 0 && (
        <div className="adp-comms-list" style={{ marginTop: 8 }}>
          {masterDecisions.map((decision, idx) => (
            <div key={`master-${idx}`} className="adp-comms-item">
              <div className="adp-comms-header">
                <span className="adp-comms-badge consult">Master decision</span>
                <span className="adp-comms-kind">
                  {String(decision.execution_mode || "linear")}
                </span>
              </div>
              <p className="adp-comms-snippet">
                {String(decision.summary || decision.reasoning || "Supervisory decision recorded.")}
              </p>
            </div>
          ))}
        </div>
      )}
      {approvalRequests.length > 0 && (
        <div className="adp-comms-list" style={{ marginTop: 8 }}>
          {approvalRequests.map((approval, idx) => (
            <div key={`approval-${idx}`} className="adp-comms-item">
              <div className="adp-comms-header">
                <span className="adp-comms-badge challenge">Approval required</span>
                <span className="adp-comms-kind">
                  {String(approval.kind || approval.checkpoint || "risk_action")}
                </span>
              </div>
              <p className="adp-comms-snippet">
                {String(approval.summary || approval.reason || "Operator approval required.")}
              </p>
            </div>
          ))}
        </div>
      )}
      {riskEvents.length > 0 && (
        <div className="adp-comms-list" style={{ marginTop: 8 }}>
          {riskEvents.map((risk, idx) => (
            <div key={`risk-${idx}`} className="adp-comms-item">
              <div className="adp-comms-header">
                <span className="adp-comms-badge debate">Governance</span>
                <span className="adp-comms-kind">{String(risk.type || risk.action || "risk")}</span>
              </div>
              <p className="adp-comms-snippet">
                {String(risk.summary || risk.reason || risk.action || "Governance event recorded.")}
              </p>
            </div>
          ))}
        </div>
      )}
      {spawnEvents.length > 0 && (
        <div className="adp-comms-list" style={{ marginTop: 8 }}>
          {spawnEvents.map((spawn, idx) => (
            <div key={`spawn-${idx}`} className="adp-comms-item">
              <div className="adp-comms-header">
                <span className="adp-comms-badge consult">Spawn branch</span>
                <span className="adp-comms-kind">
                  {String(spawn.specialist_role || spawn.spawn_kind || "specialist")}
                </span>
              </div>
              <p className="adp-comms-snippet">
                {String(
                  (spawn.bounded_assignment as string | undefined) ||
                  (spawn.description as string | undefined) ||
                  "Bounded specialist branch created."
                )}
              </p>
              {spawn.merge_back_contract ? (
                <p className="adp-comms-snippet">
                  {`Merge-back: ${String((spawn.merge_back_contract as Record<string, unknown>).child_role || "specialist")} -> ${String((spawn.merge_back_contract as Record<string, unknown>).parent_role || activeRole || "parent")}`}
                </p>
              ) : null}
            </div>
          ))}
        </div>
      )}
      {debateEvents.length > 0 && (
        <div className="adp-comms-list" style={{ marginTop: 8 }}>
          {debateEvents.map((debate, idx) => (
            <div key={`debate-runtime-${idx}`} className="adp-comms-item">
              <div className="adp-comms-header">
                <span className="adp-comms-badge debate">Debate</span>
                <span className="adp-comms-kind">
                  {String(debate.type || "debate")}
                </span>
              </div>
              <p className="adp-comms-snippet">
                {String(
                  debate.summary ||
                    debate.action_delta ||
                    debate.reviewer_feedback ||
                    "Debate event recorded.",
                )}
              </p>
            </div>
          ))}
        </div>
      )}
      {(roleLearning.length > 0 || learningAudit.length > 0) && (
        <div className="adp-comms-list" style={{ marginTop: 8 }}>
          {roleLearning.slice(0, 2).map((item, idx) => (
            <div key={`learn-${idx}`} className="adp-comms-item">
              <div className="adp-comms-header">
                <span className="adp-comms-badge consult">Role learning</span>
                <span className="adp-comms-kind">
                  {String(item.score || item.kind || "candidate")}
                </span>
              </div>
              <p className="adp-comms-snippet">
                {String(item.summary || item.pattern || item.reason || "Promoted role pattern.")}
              </p>
            </div>
          ))}
          {learningAudit.map((item, idx) => (
            <div key={`audit-${idx}`} className="adp-comms-item">
              <div className="adp-comms-header">
                <span className="adp-comms-badge debate">Behavior change</span>
                <span className="adp-comms-kind">{String(item.role || activeRole || "role")}</span>
              </div>
              <p className="adp-comms-snippet">
                {String(item.summary || item.reason || item.change || "Behavior updated from promoted learning.")}
              </p>
            </div>
          ))}
        </div>
      )}
      {learningMetrics && (
        <div className="adp-comms-item" style={{ marginTop: 8 }}>
          <div className="adp-comms-header">
            <span className="adp-comms-badge consult">Policy tuning</span>
            <span className="adp-comms-kind">
              {String(learningMetrics.update_count || 0)} updates
            </span>
          </div>
          <p className="adp-comms-snippet">
            Top score {String(learningMetrics.top_score || 0)} · avg {String(learningMetrics.avg_score || 0)} ·
            promotions {String(learningMetrics.promotions || 0)} · behavior changes {String(learningMetrics.behavior_changes || 0)}
          </p>
        </div>
      )}
    </div>
  );
}

function DebateSection({ role, collab }: { role: string; collab: CollaborationData | null }) {
  if (!collab) return null;
  const decisions = collab.events.filter((event) => {
    if (event.type !== "debate_adjudicated") return false;
    return (
      resolveCanonicalRole(event.from_role || "") === resolveCanonicalRole(role) ||
      resolveCanonicalRole(event.to_role || "") === resolveCanonicalRole(role) ||
      resolveCanonicalRole(String(event.role || "")) === resolveCanonicalRole(role)
    );
  }).slice(-2);
  if (decisions.length === 0) return null;

  return (
    <div className="adp-section">
      <div className="adp-section-hdr">
        <span className="adp-section-icon">DB</span>
        <span className="adp-section-title">Debate adjudication</span>
      </div>
      <div className="adp-comms-list">
        {decisions.map((event, index) => (
          <div key={`debate-${index}`} className="adp-comms-item">
            <div className="adp-comms-header">
              <span className="adp-comms-badge debate">Adjudicated</span>
              <span className="adp-comms-kind">
                {String(event.selected_next_owner || event.to_role || "owner selected")}
              </span>
            </div>
            <p className="adp-comms-snippet">
              {String(event.action_delta || event.content || "Debate resolved with a concrete next owner.")}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════ */
/*  Sub-components                                                      */
/* ═══════════════════════════════════════════════════════════════════ */

function GatePill({ gate }: { gate: GateResult }) {
  const label = gateDisplayLabel(gate);
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

function gateDisplayLabel(gate: GateResult): string {
  if (gate.gate === "persona") return "persona boundary";
  if (gate.gate === "contract") return "output contract";
  if (gate.gate === "no-files") return "no files";
  if (gate.gate !== "rigour") return gate.gate;

  const msg = String(gate.message || "").trim();
  const fromBracket = msg.match(/^\[([^\]]+)\]/)?.[1];
  const fromPrefix = msg.match(/^([a-z0-9_.-]+)\s*:/i)?.[1];
  const fromRule = msg.match(/(?:rule|check)\s*[:=]\s*([a-z0-9_.-]+)/i)?.[1];
  const raw = fromBracket || fromPrefix || fromRule || "";
  if (raw) return raw.replace(/[_-]+/g, " ").slice(0, 40);
  if ((gate.violation_count ?? 0) > 0) return `rigour violation`;
  return "rigour check";
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
  const responseByRequest = Object.fromEntries(
    collab.messages
      .filter(m => m.type === "consult_response" && m.linked_to)
      .map(m => [String(m.linked_to), m]),
  );

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
          const isDebateDecision = e.type === "debate_adjudicated";
          const arrow      = isRequest ? "→" : isResponse ? "←" : "↔";
          const otherRaw   = isRequest ? e.to_role : isDebateDecision ? e.selected_next_owner : e.from_role;
          const otherLabel = roleMeta(otherRaw || "agent").label;
          const color      = isDebate || isDebateDecision ? "#fb923c" : "#60a5fa";
          const msg = e.message_id ? msgMap[e.message_id] : null;
          const response = e.message_id ? responseByRequest[e.message_id] : null;
          const snippet = isRequest
            ? (msg?.content ?? e.question_preview ?? "")
            : isResponse
              ? (response?.content ?? e.response_preview ?? "")
              : isDebateDecision
                ? `Next owner: ${roleMeta(e.selected_next_owner ?? "agent").label}. `
                  + `${Array.isArray(e.feedback_sources) ? e.feedback_sources.length : 0} feedback source(s).`
                : (e.reviewer_feedback ?? "");
          return (
            <div key={i} className="adp-consult-card">
              <div className="adp-consult-row">
                <span className="adp-consult-arrow" style={{ color }}>{arrow}</span>
                <span className="adp-consult-peer" style={{ color }}>
                  {isDebate || isDebateDecision ? `Debate rd ${e.round ?? ""}` : otherLabel}
                </span>
                <span className="adp-consult-type">
                  {isDebateDecision ? "adjudicated" : isDebate ? "debate" : isRequest ? "asked" : "replied"}
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
    ["agent_consult_requested", "agent_consult_completed", "debate_round", "debate_adjudicated"].includes(e.type)
  ).slice(-10);
  if (comms.length === 0) return null;

  const msgMap = Object.fromEntries(collab.messages.map(m => [m.id, m]));
  const responseByRequest = Object.fromEntries(
    collab.messages
      .filter(m => m.type === "consult_response" && m.linked_to)
      .map(m => [String(m.linked_to), m]),
  );

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
          const isDebateDecision = e.type === "debate_adjudicated";
          const fromLabel = roleMeta(e.from_role ?? "system").label;
          const toLabel   = roleMeta((isDebateDecision ? e.selected_next_owner : e.to_role) ?? "agent").label;
          const msg = e.message_id ? msgMap[e.message_id] : null;
          const response = e.message_id ? responseByRequest[e.message_id] : null;
          const text = isDebate
            ? (e.reviewer_feedback ?? "")
            : isDebateDecision
              ? `Next owner: ${toLabel}. Feedback sources: ${
                  Array.isArray(e.feedback_sources) ? e.feedback_sources.length : 0
                }.`
            : e.type === "agent_consult_requested"
              ? (msg?.content ?? e.question_preview ?? "")
              : (response?.content ?? e.response_preview ?? "");
          return (
            <div key={i} className="adp-comms-item">
              <div className="adp-comms-header">
                {isDebate || isDebateDecision ? (
                  <span className="adp-comms-badge debate">
                    {isDebateDecision ? `Adjudicated rd ${e.round ?? i + 1}` : `Debate rd ${e.round ?? i + 1}`}
                  </span>
                ) : (
                  <span className="adp-comms-badge consult">{fromLabel} → {toLabel}</span>
                )}
                <span className="adp-comms-kind">
                  {e.type === "agent_consult_requested"
                    ? "asked"
                    : e.type === "agent_consult_completed"
                      ? "replied"
                      : isDebateDecision
                        ? "decision"
                        : "feedback"}
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
          <span className="adp-agent-codename" style={{ color: meta.color }}>{canonicalStepLabel(step)}</span>
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

function CacheSection({ step }: { step: TaskStep }) {
  const savedTokens = step.cache_saved_tokens ?? 0;
  const savedCostUsd = step.cache_saved_cost_usd ?? 0;
  const cachedInput = step.cached_input_tokens ?? 0;
  const cacheWrite = step.cache_write_tokens ?? 0;
  const source = String(step.cache_source || "none");
  if (source === "none" && savedTokens <= 0 && savedCostUsd <= 0 && cachedInput <= 0 && cacheWrite <= 0) {
    return null;
  }

  const sourceLabel =
    source === "provider"
      ? "Provider prompt cache"
      : source === "rigovo_exact"
        ? "Rigovo exact cache"
        : source === "rigovo_semantic"
          ? "Rigovo semantic cache"
          : source;

  return (
    <div className="adp-section">
      <div className="adp-section-hdr">
        <span className="adp-section-icon">🗄️</span>
        <span className="adp-section-title">Cache</span>
      </div>
      <p className="adp-no-output" style={{ marginTop: 6 }}>
        {sourceLabel}
      </p>
      <div className="adp-file-list" style={{ marginTop: 8 }}>
        {cachedInput > 0 && <span className="adp-file-chip">cached input {cachedInput.toLocaleString()} tok</span>}
        {cacheWrite > 0 && <span className="adp-file-chip">cache write {cacheWrite.toLocaleString()} tok</span>}
        {savedTokens > 0 && <span className="adp-file-chip">saved {savedTokens.toLocaleString()} tok</span>}
        {savedCostUsd > 0 && <span className="adp-file-chip">saved ${savedCostUsd.toFixed(4)}</span>}
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
  const grouped = new Map<string, { gate: GateResult; count: number }>();
  for (const g of step.gate_results) {
    const key = `${g.passed ? "1" : "0"}|${g.deep ? "1" : "0"}|${gateDisplayLabel(g)}`;
    const existing = grouped.get(key);
    if (existing) existing.count += 1;
    else grouped.set(key, { gate: g, count: 1 });
  }
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
        {Array.from(grouped.values()).map(({ gate, count }, i) => (
          <span key={i} className="inline-flex items-center gap-1">
            <GatePill gate={gate} />
            {count > 1 && (
              <span style={{ fontSize: "0.72em", opacity: 0.7, marginLeft: -2 }}>x{count}</span>
            )}
          </span>
        ))}
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
  activeFixPacket, downstreamLockReason, supervisoryDecisions, spawnHistory, debateHistory, riskActionQueue,
  requiredApprovalActions, agentLearningUpdates, behaviorChangeAudit, roleLearningMetrics,
  totalFiles, expectedAgents, nextExpectedRole, nextExpectedReason, replanCount, onOpenFiles, onApprove, onReject, isApproval,
}: AgentDetailPanelProps) {

  const activeRole = resolveActiveRole(selectedRole, steps);
  const step = activeRole ? steps.find(s => s.agent === activeRole) : null;
  const syntheticRole = activeRole && !step ? resolveBaseRole(activeRole) : null;
  const activeBaseRole = step?.agent_role || (activeRole ? resolveBaseRole(activeRole) : null);
  const activeCostKey = (step?.agent_instance || activeRole || "").toLowerCase();
  const agentCost =
    activeRole
      ? (
        costs?.per_agent?.[activeCostKey]?.cost_usd ??
        (activeBaseRole ? costs?.per_agent?.[activeBaseRole]?.cost_usd : undefined) ??
        step?.cost_usd
      )
      : undefined;
  const completedCount = (() => {
    const byRole = new Map<string, boolean>();
    steps.forEach((s) => {
      const role = resolveBaseRole(s.agent_role || s.agent);
      if (!isWorkRole(role)) return;
      const prev = byRole.get(role) ?? false;
      byRole.set(role, prev || s.status === "complete");
    });
    return Array.from(byRole.values()).filter(Boolean).length;
  })();
  const totalAgentCount = expectedAgents && expectedAgents > 0
    ? expectedAgents
    : new Set(
      steps
        .map((s) => resolveBaseRole(s.agent_role || s.agent))
        .filter((r) => isWorkRole(r)),
    ).size;
  const isActive = !taskStatus.toLowerCase().includes("complete") && !taskStatus.toLowerCase().includes("fail") && !taskStatus.toLowerCase().includes("reject");
  const hasRunning = steps.some(s => s.status === "running");
  const gateRemediationPending =
    String(nextExpectedReason || "").toLowerCase().includes("gate remediation");
  const budgetApprovalPending =
    String(nextExpectedReason || "").toLowerCase().includes("token extension approval");

  return (
    <div className="adp-root">

      {isApproval && <ApprovalBanner onApprove={onApprove} onReject={onReject} />}

      {!activeRole && !isApproval && <EmptyPanel taskStatus={taskStatus} />}

      {activeRole && step && (
        <div className="adp-content">
          <AgentHeader step={step} role={activeBaseRole || activeRole} agentCost={agentCost} />
          <RuntimeTruthSection
            activeRole={activeBaseRole || activeRole}
            activeFixPacket={activeFixPacket}
            downstreamLockReason={downstreamLockReason}
            supervisoryDecisions={supervisoryDecisions}
            spawnHistory={spawnHistory}
            debateHistory={debateHistory}
            riskActionQueue={riskActionQueue}
            requiredApprovalActions={requiredApprovalActions}
            agentLearningUpdates={agentLearningUpdates}
            behaviorChangeAudit={behaviorChangeAudit}
            roleLearningMetrics={roleLearningMetrics}
          />
          {isActive && !hasRunning && step.status === "complete" && totalAgentCount > completedCount && (
            <div className="adp-section" style={{ marginTop: 8 }}>
              <div className="adp-section-hdr">
                <span className="adp-section-icon">⏳</span>
                <span className="adp-section-title">
                  {budgetApprovalPending
                    ? "Awaiting token extension approval"
                    : gateRemediationPending
                    ? `Remediating gate failure${nextExpectedRole ? `: ${nextExpectedRole}` : ""}`
                    : `Waiting for next agent${nextExpectedRole ? `: ${nextExpectedRole}` : ""}`}
                </span>
              </div>
              {nextExpectedReason && (
                <p className="adp-no-output" style={{ marginTop: 6 }}>
                  Reason: {nextExpectedReason}
                </p>
              )}
            </div>
          )}
          <ExecutionLogSection step={step} />
          <CacheSection step={step} />
          <GateSection step={step} />
          <FileList
            files={step.files_changed}
            agent={activeRole}
            onOpen={() => onOpenFiles(activeRole, step.files_changed)}
          />
          <DebateSection role={activeBaseRole || activeRole} collab={collab} />
          <ConsultationList role={activeBaseRole || activeRole} collab={collab} />
          <AgentOutput step={step} />
          <TeamCommsPanel collab={collab} />
        </div>
      )}

      {activeRole && !step && syntheticRole && (
        <div className="adp-content">
          <div className="adp-agent-hdr">
            <div
              className="adp-agent-badge"
              style={{
                borderColor: roleMeta(syntheticRole).color + "44",
                background: roleMeta(syntheticRole).color + "12",
              }}
            >
              <span className="adp-agent-icon">{roleMeta(syntheticRole).icon}</span>
              <div>
                <span className="adp-agent-codename" style={{ color: roleMeta(syntheticRole).color }}>
                  {roleMeta(syntheticRole).label}
                </span>
                <span className="adp-agent-role">{roleMeta(syntheticRole).subtitle}</span>
              </div>
              <span className="adp-agent-status" style={{ color: "#a3a3a3" }}>
                ACTIVE
              </span>
            </div>
          </div>

          {syntheticRole === "master" && (
            <div className="adp-section">
              <div className="adp-section-hdr">
                <span className="adp-section-icon">🧭</span>
                <span className="adp-section-title">Orchestration</span>
              </div>
              <p className="adp-no-output" style={{ marginTop: 6 }}>
                {isActive
                  ? `Coordinating pipeline execution. ${nextExpectedRole ? `Next owner: ${nextExpectedRole}.` : ""}`
                  : "Run orchestration completed."}
              </p>
              <RuntimeTruthSection
                activeRole={syntheticRole}
                activeFixPacket={activeFixPacket}
                downstreamLockReason={downstreamLockReason}
                supervisoryDecisions={supervisoryDecisions}
                spawnHistory={spawnHistory}
                debateHistory={debateHistory}
                riskActionQueue={riskActionQueue}
                requiredApprovalActions={requiredApprovalActions}
                agentLearningUpdates={agentLearningUpdates}
                behaviorChangeAudit={behaviorChangeAudit}
                roleLearningMetrics={roleLearningMetrics}
              />
            </div>
          )}

          {(syntheticRole === "trinity" || syntheticRole === "rigour") && (
            <div className="adp-section">
              <div className="adp-section-hdr">
                <span className="adp-section-icon">⚡</span>
                <span className="adp-section-title">Rigour gate summary</span>
              </div>
              {(() => {
                const allGates = steps.flatMap((s) => s.gate_results ?? []);
                const failed = allGates.filter((g) => !g.passed);
                const passed = allGates.filter((g) => g.passed);
                return (
                  <>
                    <p className="adp-no-output" style={{ marginTop: 6 }}>
                      {failed.length > 0
                        ? `${failed.length} failed · ${passed.length} passed`
                        : `${passed.length} passed`}
                    </p>
                    {failed.slice(0, 5).map((g, i) => (
                      <p key={i} className="adp-comms-snippet">
                        {String(g.message || g.gate || "Gate violation")}
                      </p>
                    ))}
                  </>
                );
              })()}
            </div>
          )}
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
              {completedCount}/{totalAgentCount}
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
          {(requiredApprovalActions?.length ?? 0) > 0 && (
            <>
              <span className="adp-sum-sep" />
              <span className="adp-sum-item">
                <span className="adp-sum-num" style={{ color: "#f87171" }}>
                  {requiredApprovalActions?.length ?? 0}
                </span>
                <span className="adp-sum-lbl">approvals</span>
              </span>
            </>
          )}
        </div>
      )}
    </div>
  );
}
