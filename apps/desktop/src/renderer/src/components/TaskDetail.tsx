/* ------------------------------------------------------------------ */
/*  TaskDetail — multi-panel task view                                 */
/*  Left:  agent conversation timeline                                 */
/*  Right: tabbed side panel (files, activity log, cost breakdown)     */
/* ------------------------------------------------------------------ */
import { useCallback, useEffect, useState } from "react";
import type { InboxTask, TaskDetail as TaskDetailType, TaskStep } from "../types";
import { tierClass, statusClass } from "../defaults";
import { API_BASE, readJson } from "../api";
import AgentTimeline from "./AgentTimeline";
import ApprovalCard from "./ApprovalCard";
import FileViewer from "./FileViewer";

interface TaskDetailProps {
  task: InboxTask;
  detail: TaskDetailType | null;
  onAction: (path: string, body: Record<string, unknown>) => void;
  actionMsg: string;
}

/* ---- Side panel types ---- */
interface AuditEntry { id: string; action: string; agent_role: string; summary: string; created_at: string | null }
interface CostData { total_tokens: number; total_cost_usd: number; per_agent: Record<string, { input_tokens: number; output_tokens: number; cost_usd: number; model: string }> }
interface FilesData { files: string[]; by_agent: Record<string, string[]> }
interface CollaborationData {
  task_id: string;
  status: string;
  summary: {
    consult_requests: number;
    consult_completions: number;
    debate_rounds: number;
    integration_invoked: number;
    integration_blocked: number;
    replan_triggered: number;
    replan_failed: number;
  };
  events: Array<{
    type: string;
    role?: string;
    from_role?: string;
    to_role?: string;
    message_id?: string;
    round?: number;
    reviewer_feedback?: string;
    kind?: string;
    plugin_id?: string;
    target_id?: string;
    operation?: string;
    blocked_reason?: string;
    status?: string;
    created_at?: number | string;
  }>;
  messages: Array<{
    id: string;
    type: string;
    from_role: string;
    to_role: string;
    content: string;
    status: string;
    linked_to?: string;
    created_at?: number;
  }>;
}
interface GovernanceData {
  task_id: string;
  status: string;
  summary: {
    allow: number;
    deny: number;
    pending: number;
    approval_events: number;
    replan_events: number;
    policy_events: number;
    quality_gate_events: number;
  };
  timeline: Array<{
    ts: string | null;
    category: string;
    decision: "allow" | "deny" | "pending" | "info";
    action: string;
    actor: string;
    summary: string;
    metadata: Record<string, unknown>;
    source: string;
  }>;
}
interface MissionData {
  task_id: string;
  task_status: string;
  task_type: string;
  risk: { level: "low" | "medium" | "high"; points: number };
  cost: { total_tokens: number; total_cost_usd: number };
  team: { size: number; roles: string[] };
  workflow: {
    replan_triggered: number;
    replan_failed: number;
    approvals_requested: number;
    approvals_granted: number;
    approvals_denied: number;
    gate_failed: number;
    agent_failed: number;
    agent_retried: number;
  };
  policies: {
    parallel_agents: boolean;
    consultation_enabled: boolean;
    subagents_enabled: boolean;
    replan_enabled: boolean;
    max_replans_per_task: number;
    filesystem_sandbox: string;
    worktree_mode: string;
    plugins_enabled: boolean;
    connector_tools: boolean;
    mcp_tools: boolean;
    action_tools: boolean;
    plugin_trust_floor: string;
    approval_required_actions_allowed: boolean;
    sensitive_payload_keys_allowed: boolean;
    quality_gate_enabled: boolean;
    debate_enabled: boolean;
    debate_max_rounds: number;
  };
  decision_trace: Array<{
    ts: string | null;
    action: string;
    summary: string;
    actor: string;
    metadata: Record<string, unknown>;
  }>;
}

type SideTab = "files" | "activity" | "collab" | "governance" | "cost";

/* ---- Role colors (for side panels) ---- */
const ROLE_COLORS: Record<string, string> = {
  planner: "text-violet-600", lead: "text-purple-600", coder: "text-sky-600",
  reviewer: "text-emerald-600", qa: "text-amber-600", security: "text-rose-600",
  devops: "text-indigo-600", sre: "text-cyan-600", docs: "text-stone-500",
  orchestrator: "text-indigo-600", rigour: "text-emerald-600", system: "text-[var(--ui-text-muted)]",
};
const roleColor = (r: string) => ROLE_COLORS[r.toLowerCase()] ?? "text-[var(--ui-text-muted)]";

/* ---- Pipeline phase info (for processing state) ---- */
const PHASE_INFO: Record<string, { icon: string; title: string; desc: string }> = {
  classifying: { icon: "\uD83E\uDDE0", title: "Analyzing your request", desc: "Reading your task and determining the type of work — feature, bugfix, refactor, infra..." },
  routing:     { icon: "\uD83D\uDDFA\uFE0F", title: "Assembling the right team", desc: "Selecting which agents to involve based on task complexity and type." },
  assembling:  { icon: "\u2699\uFE0F", title: "Setting up the pipeline", desc: "Building the execution plan — which agents run in sequence, which in parallel." },
  pending:     { icon: "\u23F3", title: "Queued", desc: "Your task is in the queue and will start shortly." },
};

function getPhase(status: string) {
  for (const [key, info] of Object.entries(PHASE_INFO)) {
    if (status.includes(key)) return info;
  }
  return { icon: "\uD83D\uDD04", title: "Processing", desc: "Your task is being processed..." };
}

/* ================================================================== */
/*  ProcessingState — shown while task has no agent steps yet          */
/* ================================================================== */
function ProcessingState({ status }: { status: string }) {
  const st = status.toLowerCase();
  const isFailed = st.includes("fail") || st.includes("reject");
  const isCompleted = st.includes("complete");
  const isTerminal = isFailed || isCompleted;

  // Terminal states — show result, not a spinner
  if (isTerminal) {
    return (
      <div className="animate-fadeup rounded-2xl border border-[var(--ui-border)] bg-[rgba(0,0,0,0.02)] p-5">
        <div className="flex items-center gap-3">
          <div className={`flex h-10 w-10 items-center justify-center rounded-2xl text-lg ${isFailed ? "bg-rose-500/15" : "bg-emerald-500/15"}`}>
            {isFailed ? "✕" : "✓"}
          </div>
          <div>
            <p className="text-sm font-semibold text-[var(--ui-text)]">Master Brain</p>
            <p className="text-[11px] text-[var(--ui-text-muted)]">{isFailed ? "Run ended with failures" : "Run finished successfully"}</p>
          </div>
        </div>
        <p className="mt-3 text-[13px] text-[var(--ui-text-muted)]">
          {isFailed ? "Review evidence and retry from the failed phase." : "All queued agents completed and governance checks passed."}
        </p>
      </div>
    );
  }

  // Active states — show progress animation
  const phase = getPhase(status);
  return (
    <div className="animate-fadeup rounded-2xl border border-[var(--ui-border)] bg-[rgba(0,0,0,0.02)] p-5">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[rgba(0,0,0,0.04)] text-lg">
          {phase.icon}
        </div>
        <div>
          <p className="text-sm font-semibold text-[var(--ui-text)]">Master Brain</p>
          <p className="text-[11px] text-[var(--ui-text-muted)]">Coordinating virtual team</p>
        </div>
      </div>
      <div className="mt-4 rounded-xl border border-[var(--ui-border)] bg-[rgba(0,0,0,0.03)] p-4">
        <h3 className="text-sm font-semibold text-[var(--ui-text)]">{phase.title}</h3>
        <p className="mt-1 text-[13px] text-[var(--ui-text-muted)] leading-relaxed">{phase.desc}</p>
      </div>
      <div className="mt-3 flex items-center gap-2 text-[var(--ui-text-muted)]">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-1" />
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-2" />
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-3" />
        <span className="text-[11px] italic">Planning in progress…</span>
      </div>
    </div>
  );
}

function MissionControl({ mission }: { mission: MissionData | null }) {
  if (!mission) return null;
  const riskClass =
    mission.risk.level === "high"
      ? "text-rose-600 bg-rose-500/10 border-rose-200"
      : mission.risk.level === "medium"
        ? "text-amber-600 bg-amber-500/10 border-amber-200"
        : "text-emerald-600 bg-emerald-500/10 border-emerald-200";
  return (
    <div className="mb-4 rounded-2xl border border-[var(--ui-border)] bg-[rgba(0,0,0,0.015)] p-4 animate-fadeup">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--ui-text-muted)]">Mission Control</span>
        <span className={`rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase ${riskClass}`}>
          Risk {mission.risk.level}
        </span>
        <span className="rounded-md bg-[rgba(0,0,0,0.03)] px-2 py-0.5 text-[10px] text-[var(--ui-text-muted)]">
          Team {mission.team.size} agent{mission.team.size === 1 ? "" : "s"}
        </span>
        <span className="rounded-md bg-[rgba(0,0,0,0.03)] px-2 py-0.5 text-[10px] text-[var(--ui-text-muted)]">
          Tokens {mission.cost.total_tokens.toLocaleString()}
        </span>
        <span className="rounded-md bg-[rgba(0,0,0,0.03)] px-2 py-0.5 text-[10px] text-emerald-600">
          ${mission.cost.total_cost_usd.toFixed(4)}
        </span>
      </div>
      <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2">
        <div className="rounded-xl border border-[var(--ui-border)] bg-[rgba(0,0,0,0.015)] p-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--ui-text-muted)]">Master Brain Signals</p>
          <div className="mt-2 flex flex-wrap gap-1.5 text-[10px]">
            <span className="rounded bg-[rgba(0,0,0,0.03)] px-2 py-0.5 text-[var(--ui-text-muted)]">Parallel: {mission.policies.parallel_agents ? "on" : "off"}</span>
            <span className="rounded bg-[rgba(0,0,0,0.03)] px-2 py-0.5 text-[var(--ui-text-muted)]">Consult: {mission.policies.consultation_enabled ? "on" : "off"}</span>
            <span className="rounded bg-[rgba(0,0,0,0.03)] px-2 py-0.5 text-[var(--ui-text-muted)]">Debate: {mission.policies.debate_enabled ? `on (${mission.policies.debate_max_rounds})` : "off"}</span>
            <span className="rounded bg-[rgba(0,0,0,0.03)] px-2 py-0.5 text-[var(--ui-text-muted)]">Replan: {mission.policies.replan_enabled ? `on (${mission.policies.max_replans_per_task})` : "off"}</span>
          </div>
          <p className="mt-2 text-[10px] text-[var(--ui-text-muted)]">
            Replans {mission.workflow.replan_triggered} · Retries {mission.workflow.agent_retried} · Agent failures {mission.workflow.agent_failed}
          </p>
        </div>
        <div className="rounded-xl border border-[var(--ui-border)] bg-[rgba(0,0,0,0.015)] p-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--ui-text-muted)]">Policy & Trust</p>
          <div className="mt-2 flex flex-wrap gap-1.5 text-[10px]">
            <span className="rounded bg-[rgba(0,0,0,0.03)] px-2 py-0.5 text-[var(--ui-text-muted)]">Sandbox: {mission.policies.filesystem_sandbox}</span>
            <span className="rounded bg-[rgba(0,0,0,0.03)] px-2 py-0.5 text-[var(--ui-text-muted)]">Worktree: {mission.policies.worktree_mode}</span>
            <span className="rounded bg-[rgba(0,0,0,0.03)] px-2 py-0.5 text-[var(--ui-text-muted)]">Plugins: {mission.policies.plugins_enabled ? "on" : "off"}</span>
            <span className="rounded bg-[rgba(0,0,0,0.03)] px-2 py-0.5 text-[var(--ui-text-muted)]">Trust: {mission.policies.plugin_trust_floor}</span>
            <span className="rounded bg-[rgba(0,0,0,0.03)] px-2 py-0.5 text-[var(--ui-text-muted)]">MCP: {mission.policies.mcp_tools ? "on" : "off"}</span>
          </div>
          <p className="mt-2 text-[10px] text-[var(--ui-text-muted)]">
            Approvals {mission.workflow.approvals_granted}/{mission.workflow.approvals_requested} · Gate failures {mission.workflow.gate_failed}
          </p>
        </div>
      </div>
      <div className="mt-3 rounded-xl border border-[var(--ui-border)] bg-[rgba(0,0,0,0.03)] p-3">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--ui-text-muted)]">Decision Trace</p>
        <div className="max-h-40 overflow-y-auto space-y-1.5">
          {mission.decision_trace.slice(-12).map((evt, idx) => (
            <div key={`${evt.action}-${idx}`} className="flex items-start gap-2 text-[11px]">
              <span className="w-14 flex-shrink-0 font-mono text-[10px] text-[var(--ui-text-subtle)]">
                {evt.ts ? new Date(evt.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "--:--"}
              </span>
              <span className="rounded bg-[rgba(0,0,0,0.03)] px-1.5 py-0.5 text-[10px] text-[var(--ui-text-muted)]">{evt.actor || "system"}</span>
              <span className="text-[var(--ui-text-secondary)]">{evt.summary || evt.action}</span>
            </div>
          ))}
          {mission.decision_trace.length === 0 && (
            <p className="text-[11px] text-[var(--ui-text-subtle)]">No decision trace recorded yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}

/* ================================================================== */
/*  SidePanel — files / activity / cost tabs                           */
/* ================================================================== */
function SidePanel({ task, detail, steps }: { task: InboxTask; detail: TaskDetailType | null; steps: TaskStep[] }) {
  const [tab, setTab] = useState<SideTab>("governance");
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [costs, setCosts] = useState<CostData | null>(null);
  const [files, setFiles] = useState<FilesData | null>(null);
  const [collab, setCollab] = useState<CollaborationData | null>(null);
  const [gov, setGov] = useState<GovernanceData | null>(null);

  /* Fetch enrichment data */
  const fetchSide = useCallback(async () => {
    if (task.id.startsWith("demo-")) return;
    const [a, c, f, cb, gv] = await Promise.all([
      readJson<{ entries: AuditEntry[] }>(`${API_BASE}/v1/tasks/${task.id}/audit`),
      readJson<CostData>(`${API_BASE}/v1/tasks/${task.id}/costs`),
      readJson<FilesData>(`${API_BASE}/v1/tasks/${task.id}/files`),
      readJson<CollaborationData>(`${API_BASE}/v1/tasks/${task.id}/collaboration`),
      readJson<GovernanceData>(`${API_BASE}/v1/tasks/${task.id}/governance`),
    ]);
    if (a?.entries) setAudit(a.entries);
    if (c) setCosts(c);
    if (f) setFiles(f);
    if (cb) setCollab(cb);
    if (gv) setGov(gv);
  }, [task.id]);

  useEffect(() => { void fetchSide(); }, [fetchSide]);
  // Re-fetch when steps change
  useEffect(() => { void fetchSide(); }, [steps.length, fetchSide]);

  /* Build file list from detail steps if API didn't return any */
  const allFiles = files?.files.length
    ? files
    : {
        files: [...new Set(steps.flatMap((s) => s.files_changed))],
        by_agent: steps.reduce<Record<string, string[]>>((acc, s) => {
          if (s.files_changed.length) acc[s.agent] = s.files_changed;
          return acc;
        }, {}),
      };

  const fileCount = allFiles.files.length;
  const auditCount = audit.length;
  const hasSteps = steps.length > 0;

  return (
    <div className="side-panels flex flex-col gap-3 min-h-0">
      {/* Tab bar */}
      <div className="flex items-center gap-1 bg-[rgba(0,0,0,0.02)] rounded-xl p-1">
        {([
          ["files", `Files${fileCount ? ` (${fileCount})` : ""}`],
          ["activity", `Log${auditCount ? ` (${auditCount})` : ""}`],
          ["collab", `Collab${collab?.events?.length ? ` (${collab.events.length})` : ""}`],
          ["governance", `Governance${gov?.timeline?.length ? ` (${gov.timeline.length})` : ""}`],
          ["cost", "Cost"],
        ] as [SideTab, string][]).map(([t, label]) => (
          <button key={t} type="button" onClick={() => setTab(t)}
            className={`side-tab flex-1 text-center ${tab === t ? "active" : ""}`}>
            {label}
          </button>
        ))}
      </div>

      {/* ── Files tab — Monaco-based viewer ── */}
      {tab === "files" && (
        <div className="panel flex-1 min-h-0 flex flex-col">
          <div className="panel-header">
            <span className="text-[10px]">{"\uD83D\uDCC1"}</span>
            <span className="panel-header-label">Changed files</span>
            <span className="ml-auto text-[10px] text-[var(--ui-text-subtle)]">{fileCount} file{fileCount !== 1 ? "s" : ""}</span>
          </div>
          <div className="panel-body flex-1 min-h-0">
            <FileViewer
              taskId={task.id}
              filesByAgent={allFiles.by_agent}
              allFiles={allFiles.files}
            />
          </div>
        </div>
      )}

      {/* ── Activity tab ── */}
      {tab === "activity" && (
        <div className="panel flex-1 min-h-0 flex flex-col">
          <div className="panel-header">
            <span className="text-[10px]">{"\uD83D\uDCCB"}</span>
            <span className="panel-header-label">Activity log</span>
            <span className="ml-auto text-[10px] text-[var(--ui-text-subtle)]">{auditCount} events</span>
          </div>
          <div className="panel-body flex-1 min-h-0 overflow-y-auto">
            {/* Build entries from detail if no audit API data */}
            {auditCount === 0 && detail && (
              <ActivityFromDetail detail={detail} />
            )}
            {audit.map((e, i) => (
              <div key={e.id || i} className="flex items-start gap-2.5 px-3 py-2 border-b border-[var(--ui-border)] hover:bg-[rgba(0,0,0,0.015)] transition-colors">
                <span className="text-[10px] font-mono text-[var(--ui-text-subtle)] tabular-nums w-14 flex-shrink-0 pt-0.5">
                  {e.created_at ? new Date(e.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "--:--"}
                </span>
                <span className={`mt-1 h-1.5 w-1.5 rounded-full flex-shrink-0 ${
                  e.action.includes("complete") || e.action.includes("passed") ? "bg-emerald-500" :
                  e.action.includes("start") ? "bg-sky-500" :
                  e.action.includes("fail") ? "bg-rose-500" :
                  "bg-[var(--ui-text-subtle)]"
                }`} />
                <div className="flex-1 min-w-0">
                  <span className={`text-[10px] font-semibold ${roleColor(e.agent_role || "system")}`}>
                    {e.agent_role ? e.agent_role.charAt(0).toUpperCase() + e.agent_role.slice(1) : "System"}
                  </span>
                  <span className="text-[10px] text-[var(--ui-text-muted)] ml-1.5">{e.summary}</span>
                </div>
              </div>
            ))}
            {auditCount === 0 && !detail && (
              <p className="text-xs text-[var(--ui-text-subtle)] py-4 text-center">No events yet</p>
            )}
          </div>
        </div>
      )}

      {/* ── Collaboration tab ── */}
      {tab === "collab" && (
        <div className="panel flex-1 min-h-0 flex flex-col">
          <div className="panel-header">
            <span className="text-[10px]">{"\uD83E\uDD1D"}</span>
            <span className="panel-header-label">Agent collaboration</span>
          </div>
          <div className="panel-body flex-1 min-h-0 overflow-y-auto px-3 py-3">
            <div className="mb-3 grid grid-cols-2 gap-2 text-[10px]">
              <div className="rounded-md bg-[rgba(0,0,0,0.03)] px-2 py-1 text-[var(--ui-text-muted)]">
                Consult: <span className="text-[var(--ui-text)]">{collab?.summary.consult_completions ?? 0}/{collab?.summary.consult_requests ?? 0}</span>
              </div>
              <div className="rounded-md bg-[rgba(0,0,0,0.03)] px-2 py-1 text-[var(--ui-text-muted)]">
                Debate rounds: <span className="text-[var(--ui-text)]">{collab?.summary.debate_rounds ?? 0}</span>
              </div>
              <div className="rounded-md bg-[rgba(0,0,0,0.03)] px-2 py-1 text-[var(--ui-text-muted)]">
                Integrations: <span className="text-[var(--ui-text)]">{collab?.summary.integration_invoked ?? 0}</span>
              </div>
              <div className="rounded-md bg-[rgba(0,0,0,0.03)] px-2 py-1 text-[var(--ui-text-muted)]">
                Blocked: <span className="text-rose-600">{collab?.summary.integration_blocked ?? 0}</span>
              </div>
            </div>

            <div className="space-y-2">
              {(collab?.events || []).slice(-30).map((e, idx) => {
                const label =
                  e.type === "agent_consult_requested"
                    ? `${e.from_role || "agent"} asked ${e.to_role || "agent"}`
                    : e.type === "agent_consult_completed"
                      ? `${e.to_role || "agent"} replied to ${e.from_role || "agent"}`
                      : e.type === "debate_round"
                        ? `Debate round ${e.round || 0}`
                        : e.type === "integration_invoked"
                          ? `${e.role || "agent"} used ${e.kind || "integration"}:${e.operation || "op"}`
                          : e.type === "integration_blocked"
                            ? `${e.role || "agent"} blocked by policy (${e.blocked_reason || "blocked"})`
                            : e.type;
                const ts = typeof e.created_at === "number"
                  ? new Date(e.created_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
                  : "--:--";
                return (
                  <div key={`${e.type}-${idx}`} className="rounded-md border border-[var(--ui-border)] bg-[rgba(0,0,0,0.015)] px-2 py-1.5">
                    <div className="flex items-center gap-2">
                      <span className="w-14 flex-shrink-0 text-[10px] font-mono text-[var(--ui-text-subtle)]">{ts}</span>
                      <span className="text-[10px] text-[var(--ui-text-secondary)]">{label}</span>
                    </div>
                    {e.reviewer_feedback && (
                      <p className="mt-1 text-[10px] text-amber-700/90 line-clamp-2">{e.reviewer_feedback}</p>
                    )}
                  </div>
                );
              })}
              {(!collab || collab.events.length === 0) && (
                <p className="py-3 text-center text-xs text-[var(--ui-text-subtle)]">No collaboration events recorded yet</p>
              )}
            </div>

            {collab?.messages?.length ? (
              <div className="mt-3 border-t border-[var(--ui-border)] pt-3">
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--ui-text-muted)]">A2A message thread</p>
                <div className="space-y-1.5">
                  {collab.messages.slice(-20).map((m) => (
                    <div key={m.id} className="rounded-md bg-[rgba(0,0,0,0.015)] px-2 py-1 text-[10px] text-[var(--ui-text-muted)]">
                      <span className={roleColor(m.from_role || "system")}>{m.from_role || "agent"}</span>
                      <span className="mx-1 text-[var(--ui-text-subtle)]">→</span>
                      <span className={roleColor(m.to_role || "system")}>{m.to_role || "agent"}</span>
                      <span className="mx-1 text-[var(--ui-text-subtle)]">·</span>
                      <span className="text-[var(--ui-text-muted)]">{String(m.content || "").slice(0, 140)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}

      {/* ── Governance tab ── */}
      {tab === "governance" && (
        <div className="panel flex-1 min-h-0 flex flex-col">
          <div className="panel-header">
            <span className="text-[10px]">{"\u2696\uFE0F"}</span>
            <span className="panel-header-label">Governance timeline</span>
          </div>
          <div className="panel-body flex-1 min-h-0 overflow-y-auto px-3 py-3">
            <div className="mb-3 grid grid-cols-3 gap-2 text-[10px]">
              <div className="rounded-md bg-emerald-500/10 px-2 py-1 text-emerald-700">
                Allow: <span className="font-semibold">{gov?.summary.allow ?? 0}</span>
              </div>
              <div className="rounded-md bg-rose-500/10 px-2 py-1 text-rose-700">
                Deny: <span className="font-semibold">{gov?.summary.deny ?? 0}</span>
              </div>
              <div className="rounded-md bg-amber-500/10 px-2 py-1 text-amber-700">
                Pending: <span className="font-semibold">{gov?.summary.pending ?? 0}</span>
              </div>
            </div>

            <div className="space-y-2">
              {(gov?.timeline || []).slice(-40).map((g, idx) => {
                const badgeCls =
                  g.decision === "allow"
                    ? "bg-emerald-500/15 text-emerald-700 border-emerald-200"
                    : g.decision === "deny"
                      ? "bg-rose-500/15 text-rose-700 border-rose-200"
                      : g.decision === "pending"
                        ? "bg-amber-500/15 text-amber-700 border-amber-200"
                        : "bg-[rgba(0,0,0,0.03)] text-[var(--ui-text-muted)] border-[var(--ui-border)]";
                const ts = g.ts ? new Date(g.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "--:--";
                return (
                  <div key={`${g.action}-${idx}`} className="rounded-md border border-[var(--ui-border)] bg-[rgba(0,0,0,0.015)] px-2 py-1.5">
                    <div className="flex items-center gap-2">
                      <span className="w-14 flex-shrink-0 text-[10px] font-mono text-[var(--ui-text-subtle)]">{ts}</span>
                      <span className={`rounded border px-1.5 py-0.5 text-[10px] uppercase ${badgeCls}`}>{g.decision}</span>
                      <span className="rounded bg-[rgba(0,0,0,0.03)] px-1.5 py-0.5 text-[10px] text-[var(--ui-text-muted)]">{g.category}</span>
                      <span className="text-[10px] text-[var(--ui-text-muted)]">{g.actor}</span>
                    </div>
                    <p className="mt-1 text-[10px] text-[var(--ui-text-secondary)]">{g.summary || g.action}</p>
                  </div>
                );
              })}
              {(!gov || gov.timeline.length === 0) && (
                <p className="py-3 text-center text-xs text-[var(--ui-text-subtle)]">No governance events recorded yet</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Cost tab ── */}
      {tab === "cost" && (
        <div className="panel flex-1 min-h-0 flex flex-col">
          <div className="panel-header">
            <span className="text-[10px]">{"\u26A1"}</span>
            <span className="panel-header-label">Cost breakdown</span>
          </div>
          <div className="panel-body flex-1 min-h-0 overflow-y-auto px-3 py-3">
            {/* Totals */}
            <div className="flex items-center justify-between mb-4 pb-3 border-b border-[var(--ui-border)]">
              <div>
                <p className="text-[10px] text-[var(--ui-text-subtle)] uppercase tracking-wider">Total tokens</p>
                <p className="text-sm font-semibold text-[var(--ui-text)] tabular-nums">
                  {(costs?.total_tokens || detail?.cost?.total_tokens || 0).toLocaleString()}
                </p>
              </div>
              <div className="text-right">
                <p className="text-[10px] text-[var(--ui-text-subtle)] uppercase tracking-wider">Total cost</p>
                <p className="text-sm font-semibold text-emerald-600 tabular-nums">
                  ${(costs?.total_cost_usd || detail?.cost?.total_cost_usd || 0).toFixed(4)}
                </p>
              </div>
            </div>

            {/* Per-agent breakdown */}
            {costs?.per_agent && Object.keys(costs.per_agent).length > 0 ? (
              <div className="space-y-2.5">
                {Object.entries(costs.per_agent).map(([role, data]) => (
                  <div key={role} className="flex items-center gap-2.5">
                    <span className={`text-[10px] font-semibold w-16 ${roleColor(role)}`}>
                      {role.charAt(0).toUpperCase() + role.slice(1)}
                    </span>
                    {/* Bar */}
                    <div className="flex-1 h-2 rounded-full bg-[rgba(0,0,0,0.03)] overflow-hidden">
                      <div
                        className="h-full rounded-full bg-[var(--ui-text)]"
                        style={{ width: `${Math.min(100, ((data.input_tokens + data.output_tokens) / (costs.total_tokens || 1)) * 100)}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-[var(--ui-text-muted)] tabular-nums w-14 text-right">
                      ${data.cost_usd.toFixed(3)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              /* Fallback from detail.cost */
              detail?.cost ? (
                <p className="text-xs text-[var(--ui-text-muted)]">Per-agent breakdown not available yet.</p>
              ) : (
                <p className="text-xs text-[var(--ui-text-subtle)] text-center py-4">No cost data yet</p>
              )
            )}

            {/* Model info */}
            {costs?.per_agent && Object.values(costs.per_agent).some((d) => d.model) && (
              <div className="mt-4 pt-3 border-t border-[var(--ui-border)]">
                <p className="text-[10px] text-[var(--ui-text-subtle)] uppercase tracking-wider mb-2">Models used</p>
                <div className="flex flex-wrap gap-1.5">
                  {[...new Set(Object.values(costs.per_agent).map((d) => d.model).filter(Boolean))].map((m) => (
                    <span key={m} className="text-[10px] bg-[rgba(0,0,0,0.03)] text-[var(--ui-text-muted)] px-2 py-0.5 rounded-md">{m}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* Fallback activity log built from TaskDetail steps */
function ActivityFromDetail({ detail }: { detail: TaskDetailType }) {
  const entries: Array<{ time: string; agent: string; event: string; type: string }> = [];
  if (detail.created_at) entries.push({ time: detail.created_at, agent: "system", event: `Task created — ${detail.task_type || "classifying"}`, type: "system" });
  if (detail.started_at) entries.push({ time: detail.started_at, agent: "orchestrator", event: `Pipeline started (${detail.steps.length} agents)`, type: "system" });
  for (const step of detail.steps) {
    if (step.started_at) entries.push({ time: step.started_at, agent: step.agent, event: "Started working", type: "start" });
    if (step.completed_at && step.status === "complete") entries.push({ time: step.completed_at, agent: step.agent, event: `Completed${step.files_changed.length ? ` — ${step.files_changed.length} files` : ""}`, type: "complete" });
    if (step.completed_at && step.status === "failed") entries.push({ time: step.completed_at, agent: step.agent, event: "Failed", type: "fail" });
    for (const g of step.gate_results) {
      if (step.completed_at) entries.push({ time: step.completed_at, agent: "rigour", event: `${g.gate}: ${g.passed ? "passed" : "failed"}`, type: g.passed ? "complete" : "fail" });
    }
  }
  entries.sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime());

  return (
    <>
      {entries.map((e, i) => (
        <div key={i} className="flex items-start gap-2.5 px-3 py-2 border-b border-[var(--ui-border)]">
          <span className="text-[10px] font-mono text-[var(--ui-text-subtle)] tabular-nums w-14 flex-shrink-0 pt-0.5">
            {(() => { try { return new Date(e.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); } catch { return "--:--"; } })()}
          </span>
          <span className={`mt-1 h-1.5 w-1.5 rounded-full flex-shrink-0 ${
            e.type === "complete" ? "bg-emerald-500" : e.type === "start" ? "bg-sky-500" : e.type === "fail" ? "bg-rose-500" : "bg-[var(--ui-text-subtle)]"
          }`} />
          <div className="flex-1 min-w-0">
            <span className={`text-[10px] font-semibold ${roleColor(e.agent)}`}>
              {e.agent.charAt(0).toUpperCase() + e.agent.slice(1)}
            </span>
            <span className="text-[10px] text-[var(--ui-text-muted)] ml-1.5">{e.event}</span>
          </div>
        </div>
      ))}
    </>
  );
}

/* ================================================================== */
/*  AgentStatusStrip — compact pipeline overview                       */
/* ================================================================== */
function AgentStatusStrip({ steps }: { steps: TaskStep[] }) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {steps.map((step, i) => (
        <div key={i}
          className={`flex items-center gap-1 rounded-lg border border-[var(--ui-border)] bg-[rgba(0,0,0,0.02)] px-2 py-1 ${
            step.status === "running" ? "animate-border-pulse" : ""
          }`}
          title={`${step.agent}: ${step.status}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${
            step.status === "complete" ? "bg-emerald-500" :
            step.status === "running" ? "bg-sky-500 animate-pulse" :
            step.status === "failed" ? "bg-rose-500" : "bg-[var(--ui-text-subtle)]"
          }`} />
          <span className={`text-[10px] font-medium ${roleColor(step.agent)}`}>
            {step.agent.charAt(0).toUpperCase() + step.agent.slice(1)}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ================================================================== */
/*  TaskDetail — main export                                           */
/* ================================================================== */
export default function TaskDetail({ task, detail, onAction, actionMsg }: TaskDetailProps) {
  const [mission, setMission] = useState<MissionData | null>(null);
  const st = task.status.toLowerCase();
  const isApproval = st.includes("approval");
  const isCompleted = st.includes("complete");
  const isFailed = st.includes("fail") || st.includes("reject");
  const isActive = !isApproval && !isCompleted && !isFailed;  // running, classifying, routing, assembling, pending, quality_check, etc.
  const canResume = isFailed;  // Only failed/rejected tasks can be resumed
  const hasSteps = detail && detail.steps.length > 0;
  const isProcessing = !detail || !hasSteps;

  useEffect(() => {
    if (task.id.startsWith("demo-")) {
      setMission(null);
      return;
    }
    let alive = true;
    void (async () => {
      const data = await readJson<MissionData>(`${API_BASE}/v1/tasks/${task.id}/mission`);
      if (alive) setMission(data);
    })();
    return () => { alive = false; };
  }, [task.id, detail?.steps.length]);

  return (
    <div className="animate-fadeup h-full flex flex-col">
      {/* ── Header bar ── */}
      <div className="mb-4 pb-3 border-b border-[var(--ui-border)] flex-shrink-0">
        <h2 className="text-base font-bold text-[var(--ui-text)] leading-tight">{task.title}</h2>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className={tierClass(task.tier)}>{task.tier}</span>
          <span className={statusClass(task.status)}>{task.status}</span>
          {detail?.task_type && (
            <span className="text-[10px] rounded-md px-2 py-0.5 bg-[rgba(0,0,0,0.04)] text-[var(--ui-text-secondary)] font-medium">
              {detail.task_type}
            </span>
          )}
          <span className="text-[10px] text-[var(--ui-text-subtle)]">{"\u00B7"} {task.updatedAt}</span>

          {/* Action buttons — inline with header */}
          <div className="ml-auto flex items-center gap-2">
            {isApproval && (<>
              <button type="button" className="primary-btn text-xs py-1.5 px-3"
                onClick={() => onAction(`/v1/tasks/${task.id}/approve`, { action: "approve", resume_now: true })}>
                Approve
              </button>
              <button type="button" className="warn-btn text-xs py-1.5 px-3"
                onClick={() => onAction(`/v1/tasks/${task.id}/abort`, { reason: "Rejected" })}>
                Reject
              </button>
            </>)}
            {isActive && (
              <button type="button" className="warn-btn text-xs py-1.5 px-3"
                onClick={() => onAction(`/v1/tasks/${task.id}/abort`, { reason: "Aborted by user" })}>
                Abort
              </button>
            )}
            {canResume && (
              <button type="button" className="ghost-btn text-xs py-1.5 px-3"
                onClick={() => onAction(`/v1/tasks/${task.id}/resume`, { resume_now: true })}>
                Resume
              </button>
            )}
            {actionMsg && <span className="text-[10px] text-[var(--ui-text-muted)]">{actionMsg}</span>}
          </div>
        </div>

        {/* Agent pipeline strip */}
        {hasSteps && (
          <div className="mt-2.5">
            <AgentStatusStrip steps={detail.steps} />
          </div>
        )}
      </div>

      <MissionControl mission={mission} />

      {/* ── Multi-panel content ── */}
      {isProcessing ? (
        <ProcessingState status={task.status} />
      ) : (
        <div className="task-layout flex-1 min-h-0">
          {/* Left — Agent conversation */}
          <div className="overflow-y-auto pr-2">
            <AgentTimeline steps={detail.steps} taskType={detail.task_type} />

            {isApproval && (
              <div className="mt-4">
                <ApprovalCard
                  taskId={task.id}
                  onApprove={() => onAction(`/v1/tasks/${task.id}/approve`, { action: "approve", resume_now: true })}
                  onReject={() => onAction(`/v1/tasks/${task.id}/abort`, { reason: "Rejected" })}
                />
              </div>
            )}
          </div>

          {/* Right — Side panels */}
          <SidePanel task={task} detail={detail} steps={detail.steps} />
        </div>
      )}
    </div>
  );
}
