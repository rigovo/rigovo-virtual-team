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

type SideTab = "files" | "activity" | "cost";

/* ---- Role colors (for side panels) ---- */
const ROLE_COLORS: Record<string, string> = {
  planner: "text-violet-400", lead: "text-purple-400", coder: "text-sky-400",
  reviewer: "text-emerald-400", qa: "text-amber-400", security: "text-rose-400",
  devops: "text-indigo-400", sre: "text-cyan-400", docs: "text-stone-400",
  orchestrator: "text-indigo-400", rigour: "text-emerald-400", system: "text-slate-500",
};
const roleColor = (r: string) => ROLE_COLORS[r.toLowerCase()] ?? "text-slate-400";

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
  const phase = getPhase(status);
  const steps = ["Understanding the request", "Classifying task type", "Selecting agents"];
  return (
    <div className="animate-fadeup">
      <div className="flex items-center gap-3 mb-4">
        <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-brand/15 ring-1 ring-brand/30 text-lg animate-pulse-glow">
          {phase.icon}
        </div>
        <div>
          <span className="text-sm font-semibold text-brand-light">Orchestrator</span>
          <span className="ml-2 text-[10px] text-slate-600">Master Brain</span>
        </div>
      </div>
      <div className="ml-[52px] rounded-2xl border border-brand/15 bg-brand/5 p-5">
        <h3 className="text-sm font-semibold text-slate-200 mb-1">{phase.title}</h3>
        <p className="text-[13px] text-slate-400 leading-relaxed mb-4">{phase.desc}</p>
        <div className="space-y-2.5">
          {steps.map((step, i) => (
            <div key={step} className="flex items-center gap-3 animate-fadeup" style={{ animationDelay: `${(i + 1) * 300}ms` }}>
              <div className={`flex h-5 w-5 items-center justify-center rounded-md text-[10px] ${
                i === 0 ? "bg-emerald-500/20 text-emerald-400" :
                i === 1 && status.includes("classif") ? "bg-sky-500/20 text-sky-400" :
                i === 1 ? "bg-emerald-500/20 text-emerald-400" :
                "bg-slate-700/50 text-slate-500"
              }`}>
                {i === 0 ? "\u2713" :
                 i === 1 && status.includes("classif") ? <span className="inline-block h-2.5 w-2.5 animate-spin rounded-full border border-sky-400/30 border-t-sky-400" /> :
                 i === 1 ? "\u2713" :
                 status.includes("rout") || status.includes("assembl") ? <span className="inline-block h-2.5 w-2.5 animate-spin rounded-full border border-sky-400/30 border-t-sky-400" /> : "\u00B7"}
              </div>
              <span className={`text-xs ${i <= 1 || status.includes("rout") || status.includes("assembl") ? "text-slate-300" : "text-slate-600"}`}>{step}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="ml-[52px] mt-3 flex items-center gap-2">
        <div className="flex items-center gap-1 text-brand-light/60">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-1" />
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-2" />
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-3" />
        </div>
        <span className="text-[11px] text-slate-600 italic">Orchestrator is thinking...</span>
      </div>
    </div>
  );
}

/* ================================================================== */
/*  SidePanel — files / activity / cost tabs                           */
/* ================================================================== */
function SidePanel({ task, detail, steps }: { task: InboxTask; detail: TaskDetailType | null; steps: TaskStep[] }) {
  const [tab, setTab] = useState<SideTab>("files");
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [costs, setCosts] = useState<CostData | null>(null);
  const [files, setFiles] = useState<FilesData | null>(null);

  /* Fetch enrichment data */
  const fetchSide = useCallback(async () => {
    if (task.id.startsWith("demo-")) return;
    const [a, c, f] = await Promise.all([
      readJson<{ entries: AuditEntry[] }>(`${API_BASE}/v1/tasks/${task.id}/audit`),
      readJson<CostData>(`${API_BASE}/v1/tasks/${task.id}/costs`),
      readJson<FilesData>(`${API_BASE}/v1/tasks/${task.id}/files`),
    ]);
    if (a?.entries) setAudit(a.entries);
    if (c) setCosts(c);
    if (f) setFiles(f);
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
      <div className="flex items-center gap-1 bg-white/[0.03] rounded-xl p-1">
        {([
          ["files", `Files${fileCount ? ` (${fileCount})` : ""}`],
          ["activity", `Log${auditCount ? ` (${auditCount})` : ""}`],
          ["cost", "Cost"],
        ] as [SideTab, string][]).map(([t, label]) => (
          <button key={t} type="button" onClick={() => setTab(t)}
            className={`side-tab flex-1 text-center ${tab === t ? "active" : ""}`}>
            {label}
          </button>
        ))}
      </div>

      {/* ── Files tab ── */}
      {tab === "files" && (
        <div className="panel flex-1 min-h-0 flex flex-col">
          <div className="panel-header">
            <span className="text-[10px]">{"\uD83D\uDCC1"}</span>
            <span className="panel-header-label">Changed files</span>
            <span className="ml-auto text-[10px] text-slate-600">{fileCount} file{fileCount !== 1 ? "s" : ""}</span>
          </div>
          <div className="panel-body flex-1 min-h-0 overflow-y-auto px-3 py-2">
            {!hasSteps && <p className="text-xs text-slate-600 py-4 text-center">No files yet</p>}
            {Object.entries(allFiles.by_agent).map(([agent, agentFiles]) => (
              <div key={agent} className="mb-3">
                <p className={`text-[10px] font-semibold uppercase tracking-wider mb-1 ${roleColor(agent)}`}>
                  {agent}
                </p>
                {agentFiles.map((f) => (
                  <p key={f} className="text-xs font-mono text-slate-400 py-0.5 flex items-center gap-1.5 hover:text-slate-300 transition-colors">
                    <span className="text-emerald-500/60 text-[10px]">+</span>
                    {f.replace(/^\//, "")}
                  </p>
                ))}
              </div>
            ))}
            {hasSteps && fileCount === 0 && (
              <p className="text-xs text-slate-600 py-4 text-center">Agents haven't written files yet</p>
            )}
          </div>
        </div>
      )}

      {/* ── Activity tab ── */}
      {tab === "activity" && (
        <div className="panel flex-1 min-h-0 flex flex-col">
          <div className="panel-header">
            <span className="text-[10px]">{"\uD83D\uDCCB"}</span>
            <span className="panel-header-label">Activity log</span>
            <span className="ml-auto text-[10px] text-slate-600">{auditCount} events</span>
          </div>
          <div className="panel-body flex-1 min-h-0 overflow-y-auto">
            {/* Build entries from detail if no audit API data */}
            {auditCount === 0 && detail && (
              <ActivityFromDetail detail={detail} />
            )}
            {audit.map((e, i) => (
              <div key={e.id || i} className="flex items-start gap-2.5 px-3 py-2 border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
                <span className="text-[10px] font-mono text-slate-600 tabular-nums w-14 flex-shrink-0 pt-0.5">
                  {e.created_at ? new Date(e.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "--:--"}
                </span>
                <span className={`mt-1 h-1.5 w-1.5 rounded-full flex-shrink-0 ${
                  e.action.includes("complete") || e.action.includes("passed") ? "bg-emerald-500" :
                  e.action.includes("start") ? "bg-sky-500" :
                  e.action.includes("fail") ? "bg-rose-500" :
                  "bg-slate-600"
                }`} />
                <div className="flex-1 min-w-0">
                  <span className={`text-[10px] font-semibold ${roleColor(e.agent_role || "system")}`}>
                    {e.agent_role ? e.agent_role.charAt(0).toUpperCase() + e.agent_role.slice(1) : "System"}
                  </span>
                  <span className="text-[10px] text-slate-500 ml-1.5">{e.summary}</span>
                </div>
              </div>
            ))}
            {auditCount === 0 && !detail && (
              <p className="text-xs text-slate-600 py-4 text-center">No events yet</p>
            )}
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
            <div className="flex items-center justify-between mb-4 pb-3 border-b border-white/5">
              <div>
                <p className="text-[10px] text-slate-600 uppercase tracking-wider">Total tokens</p>
                <p className="text-sm font-semibold text-slate-200 tabular-nums">
                  {(costs?.total_tokens || detail?.cost?.total_tokens || 0).toLocaleString()}
                </p>
              </div>
              <div className="text-right">
                <p className="text-[10px] text-slate-600 uppercase tracking-wider">Total cost</p>
                <p className="text-sm font-semibold text-emerald-400 tabular-nums">
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
                    <div className="flex-1 h-2 rounded-full bg-white/5 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-brand/40"
                        style={{ width: `${Math.min(100, ((data.input_tokens + data.output_tokens) / (costs.total_tokens || 1)) * 100)}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-slate-500 tabular-nums w-14 text-right">
                      ${data.cost_usd.toFixed(3)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              /* Fallback from detail.cost */
              detail?.cost ? (
                <p className="text-xs text-slate-500">Per-agent breakdown not available yet.</p>
              ) : (
                <p className="text-xs text-slate-600 text-center py-4">No cost data yet</p>
              )
            )}

            {/* Model info */}
            {costs?.per_agent && Object.values(costs.per_agent).some((d) => d.model) && (
              <div className="mt-4 pt-3 border-t border-white/5">
                <p className="text-[10px] text-slate-600 uppercase tracking-wider mb-2">Models used</p>
                <div className="flex flex-wrap gap-1.5">
                  {[...new Set(Object.values(costs.per_agent).map((d) => d.model).filter(Boolean))].map((m) => (
                    <span key={m} className="text-[10px] bg-white/5 text-slate-400 px-2 py-0.5 rounded-md">{m}</span>
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
        <div key={i} className="flex items-start gap-2.5 px-3 py-2 border-b border-white/[0.03]">
          <span className="text-[10px] font-mono text-slate-600 tabular-nums w-14 flex-shrink-0 pt-0.5">
            {(() => { try { return new Date(e.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); } catch { return "--:--"; } })()}
          </span>
          <span className={`mt-1 h-1.5 w-1.5 rounded-full flex-shrink-0 ${
            e.type === "complete" ? "bg-emerald-500" : e.type === "start" ? "bg-sky-500" : e.type === "fail" ? "bg-rose-500" : "bg-slate-600"
          }`} />
          <div className="flex-1 min-w-0">
            <span className={`text-[10px] font-semibold ${roleColor(e.agent)}`}>
              {e.agent.charAt(0).toUpperCase() + e.agent.slice(1)}
            </span>
            <span className="text-[10px] text-slate-500 ml-1.5">{e.event}</span>
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
          className={`flex items-center gap-1 rounded-lg border border-white/5 bg-surface/60 px-2 py-1 ${
            step.status === "running" ? "animate-border-pulse" : ""
          }`}
          title={`${step.agent}: ${step.status}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${
            step.status === "complete" ? "bg-emerald-500" :
            step.status === "running" ? "bg-sky-500 animate-pulse" :
            step.status === "failed" ? "bg-rose-500" : "bg-slate-600"
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
  const isApproval = task.status.includes("approval");
  const isRunning = task.status.includes("running") || task.status.includes("progress");
  const isDone = task.status.includes("complete") || task.status.includes("fail") || task.status.includes("paused");
  const hasSteps = detail && detail.steps.length > 0;
  const isProcessing = !detail || !hasSteps;

  return (
    <div className="animate-fadeup h-full flex flex-col">
      {/* ── Header bar ── */}
      <div className="mb-4 pb-3 border-b border-white/5 flex-shrink-0">
        <h2 className="text-base font-bold text-slate-100 leading-tight">{task.title}</h2>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className={tierClass(task.tier)}>{task.tier}</span>
          <span className={statusClass(task.status)}>{task.status}</span>
          {detail?.task_type && (
            <span className="text-[10px] rounded-md px-2 py-0.5 bg-brand/10 text-brand-light font-medium">
              {detail.task_type}
            </span>
          )}
          <span className="text-[10px] text-slate-600">{"\u00B7"} {task.updatedAt}</span>

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
            {isRunning && (
              <button type="button" className="warn-btn text-xs py-1.5 px-3"
                onClick={() => onAction(`/v1/tasks/${task.id}/abort`, { reason: "Paused" })}>
                Pause
              </button>
            )}
            {isDone && (
              <button type="button" className="ghost-btn text-xs py-1.5 px-3"
                onClick={() => onAction(`/v1/tasks/${task.id}/resume`, { resume_now: true })}>
                Resume
              </button>
            )}
            {actionMsg && <span className="text-[10px] text-slate-500">{actionMsg}</span>}
          </div>
        </div>

        {/* Agent pipeline strip */}
        {hasSteps && (
          <div className="mt-2.5">
            <AgentStatusStrip steps={detail.steps} />
          </div>
        )}
      </div>

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
