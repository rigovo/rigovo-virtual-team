/* ------------------------------------------------------------------ */
/*  TaskDetail — full-width agent conversation view                    */
/*  Unified Team Feed: timeline + collab events + governance inline    */
/* ------------------------------------------------------------------ */
import { useCallback, useEffect, useState } from "react";
import type { InboxTask, TaskDetail as TaskDetailType, TaskStep } from "../types";
import { tierClass, statusClass } from "../defaults";
import { API_BASE, readJson } from "../api";
import AgentTimeline from "./AgentTimeline";
import type { CollaborationData, GovernanceData, CostData } from "./AgentTimeline";
import FileViewer from "./FileViewer";

interface TaskDetailProps {
  task: InboxTask;
  detail: TaskDetailType | null;
  onAction: (path: string, body: Record<string, unknown>) => void;
  actionMsg: string;
  projectPath?: string;
  onOpenInEditor?: (path: string) => void;
}

/* ---- Inline types ---- */
interface AuditEntry { id: string; action: string; agent_role: string; summary: string; created_at: string | null }
interface FilesData { files: string[]; by_agent: Record<string, string[]> }
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
/*  ProcessingState                                                    */
/* ================================================================== */
function ProcessingState({ status }: { status: string }) {
  const st = status.toLowerCase();
  const isFailed    = st.includes("fail") || st.includes("reject");
  const isCompleted = st.includes("complete");
  const isTerminal  = isFailed || isCompleted;

  if (isTerminal) {
    return (
      <div className="animate-fadeup rounded-2xl border border-[var(--border)] bg-[rgba(0,0,0,0.02)] p-5">
        <div className="flex items-center gap-3">
          <div className={`flex h-10 w-10 items-center justify-center rounded-2xl text-lg ${isFailed ? "bg-rose-500/15" : "bg-emerald-500/15"}`}>
            {isFailed ? "✕" : "✓"}
          </div>
          <div>
            <p className="text-sm font-semibold" style={{ color: "var(--t1)" }}>Master Brain</p>
            <p className="text-[11px]" style={{ color: "var(--t3)" }}>{isFailed ? "Run ended with failures" : "Run finished successfully"}</p>
          </div>
        </div>
        <p className="mt-3 text-[13px]" style={{ color: "var(--t3)" }}>
          {isFailed ? "Review evidence and retry from the failed phase." : "All queued agents completed and governance checks passed."}
        </p>
      </div>
    );
  }

  const phase = getPhase(status);
  return (
    <div className="animate-fadeup rounded-2xl border border-[var(--border)] bg-[rgba(0,0,0,0.02)] p-5">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-[rgba(0,0,0,0.04)] text-lg">
          {phase.icon}
        </div>
        <div>
          <p className="text-sm font-semibold" style={{ color: "var(--t1)" }}>Master Brain</p>
          <p className="text-[11px]" style={{ color: "var(--t3)" }}>Coordinating virtual team</p>
        </div>
      </div>
      <div className="mt-4 rounded-xl border border-[var(--border)] bg-[rgba(0,0,0,0.03)] p-4">
        <h3 className="text-sm font-semibold" style={{ color: "var(--t1)" }}>{phase.title}</h3>
        <p className="mt-1 text-[13px] leading-relaxed" style={{ color: "var(--t3)" }}>{phase.desc}</p>
      </div>
      <div className="mt-3 flex items-center gap-2" style={{ color: "var(--t3)" }}>
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-1" />
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-2" />
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-3" />
        <span className="text-[11px] italic">Planning in progress…</span>
      </div>
    </div>
  );
}

/* ================================================================== */
/*  MissionControl — key metrics summary                              */
/* ================================================================== */
function MissionControl({ mission }: { mission: MissionData | null }) {
  if (!mission) return null;
  const riskColor =
    mission.risk.level === "high" ? "#b91c1c" :
    mission.risk.level === "medium" ? "#b45309" : "#15803d";
  const riskBg =
    mission.risk.level === "high" ? "rgba(220,38,38,0.08)" :
    mission.risk.level === "medium" ? "rgba(217,119,6,0.08)" : "rgba(22,163,74,0.08)";

  return (
    <div className="mb-4 animate-fadeup flex-shrink-0">
      <div className="flex flex-wrap gap-1.5 mb-3">
        <span className="mission-stat" style={{ color: riskColor, background: riskBg }}>
          Risk: {mission.risk.level}
        </span>
        <span className="mission-stat">
          {mission.team.size} agent{mission.team.size === 1 ? "" : "s"} · {mission.team.roles.slice(0, 4).join(", ")}
          {mission.team.roles.length > 4 ? ` +${mission.team.roles.length - 4}` : ""}
        </span>
        <span className="mission-stat" style={{ color: "#15803d", background: "rgba(22,163,74,0.07)" }}>
          ${mission.cost.total_cost_usd.toFixed(4)} · {mission.cost.total_tokens.toLocaleString()} tokens
        </span>
        {mission.workflow.approvals_requested > 0 && (
          <span className="mission-stat">
            {mission.workflow.approvals_granted}/{mission.workflow.approvals_requested} approved
          </span>
        )}
        {mission.workflow.replan_triggered > 0 && (
          <span className="mission-stat" style={{ color: "#b45309", background: "rgba(217,119,6,0.07)" }}>
            {mission.workflow.replan_triggered} replan{mission.workflow.replan_triggered === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {mission.decision_trace.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--t4)] mb-2">
            Recent decisions
          </p>
          {mission.decision_trace.slice(-4).map((evt, idx) => (
            <div key={`${evt.action}-${idx}`} className="flex items-start gap-2 py-1.5 text-[11px] border-b border-[var(--border)] last:border-0">
              <span className="text-[var(--t4)] w-10 flex-shrink-0 tabular-nums font-mono">
                {evt.ts ? new Date(evt.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "--:--"}
              </span>
              <span className="text-[10px] rounded bg-[rgba(0,0,0,0.04)] px-1.5 py-0.5 text-[var(--t3)] flex-shrink-0">
                {evt.actor || "system"}
              </span>
              <span className="text-[var(--t2)] leading-snug">{evt.summary || evt.action}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ================================================================== */
/*  AgentStatusStrip — visual pipeline track                          */
/* ================================================================== */
function AgentStatusStrip({ steps }: { steps: TaskStep[] }) {
  const runningIdx = steps.findIndex((s) => s.status === "running");
  return (
    <div className="pipeline-track">
      {steps.map((step, i) => {
        const isRunning = step.status === "running";
        const prevComplete = i > 0 && steps[i - 1].status === "complete";
        return (
          <div key={i} className="flex items-center gap-0">
            {i > 0 && (
              <span className={`pipeline-arrow ${prevComplete ? "complete" : ""}`} />
            )}
            <div
              className={`pipeline-node ${isRunning ? "running pipeline-running" : step.status}`}
              title={`${step.agent}: ${step.status}`}
            >
              <span className="pipeline-dot" />
              <span>{step.agent.charAt(0).toUpperCase() + step.agent.slice(1)}</span>
            </div>
          </div>
        );
      })}
      {runningIdx >= 0 && runningIdx < steps.length - 1 && (() => {
        const queuedCount = steps.slice(runningIdx + 1).filter((s) => s.status === "pending").length;
        return queuedCount > 0 ? (
          <div className="flex items-center gap-0">
            <span className="pipeline-arrow" />
            <span className="text-[10px] text-[var(--t4)] px-2">+{queuedCount} queued</span>
          </div>
        ) : null;
      })()}
    </div>
  );
}

/* ================================================================== */
/*  FilesDrawer — bottom drawer with Monaco file viewer               */
/* ================================================================== */
interface FilesDrawerProps {
  taskId: string;
  agent: string;
  files: string[];
  byAgent: Record<string, string[]>;
  onClose: () => void;
}

function FilesDrawer({ taskId, agent, files, byAgent, onClose }: FilesDrawerProps) {
  return (
    <>
      <div className="files-drawer-overlay" onClick={onClose} />
      <div className="files-drawer">
        <div className="files-drawer-header">
          <span className="text-base">📁</span>
          <span className="text-[11px] font-semibold" style={{ color: "var(--t1)" }}>
            Files changed by {agent.charAt(0).toUpperCase() + agent.slice(1)}
          </span>
          <span className="text-[10px] rounded-full px-2 py-0.5 bg-[rgba(0,0,0,0.05)] text-[var(--t3)]">
            {files.length} file{files.length !== 1 ? "s" : ""}
          </span>
          <button type="button" className="files-drawer-close" onClick={onClose} aria-label="Close files">
            ×
          </button>
        </div>
        <div className="files-drawer-body">
          <FileViewer taskId={taskId} filesByAgent={byAgent} allFiles={files} />
        </div>
      </div>
    </>
  );
}

/* ================================================================== */
/*  OpenInEditor — small dropdown for opening project in editor       */
/* ================================================================== */
const EDITORS = [
  { id: "vscode",  label: "VS Code",  icon: "⬡", scheme: (p: string) => `vscode://file/${encodeURIComponent(p)}` },
  { id: "cursor",  label: "Cursor",   icon: "◈", scheme: (p: string) => `cursor://file/${encodeURIComponent(p)}` },
  { id: "zed",     label: "Zed",      icon: "◆", scheme: (p: string) => `zed://file/${encodeURIComponent(p)}` },
];

function OpenInEditorBtn({ projectPath, onOpen }: { projectPath: string; onOpen: (url: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        className="ghost-btn text-xs py-1.5 px-3 flex items-center gap-1.5"
        onClick={() => setOpen((v) => !v)}
        title="Open project in editor"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <rect x="1" y="1.5" width="10" height="9" rx="1.5" />
          <path d="M4 4.5l2 1.5-2 1.5M7 7.5h2" />
        </svg>
        Open in editor
        <svg width="8" height="8" viewBox="0 0 8 8" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
          <path d="M2 3l2 2 2-2" />
        </svg>
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-40 bg-[var(--canvas)] border border-[var(--border)] rounded-xl shadow-lg overflow-hidden py-1 min-w-[130px]"
          onMouseLeave={() => setOpen(false)}
        >
          {EDITORS.map((e) => (
            <button
              key={e.id}
              type="button"
              className="flex items-center gap-2 w-full px-3 py-2 text-left text-[12px] text-[var(--t2)] hover:bg-[rgba(0,0,0,0.04)] transition-colors"
              onClick={() => { onOpen(e.scheme(projectPath)); setOpen(false); }}
            >
              <span className="text-base leading-none">{e.icon}</span>
              {e.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ================================================================== */
/*  TaskDetail — main export                                           */
/* ================================================================== */
export default function TaskDetail({ task, detail, onAction, actionMsg, projectPath, onOpenInEditor }: TaskDetailProps) {
  const [mission, setMission]   = useState<MissionData | null>(null);
  const [collab, setCollab]     = useState<CollaborationData | null>(null);
  const [gov, setGov]           = useState<GovernanceData | null>(null);
  const [costs, setCosts]       = useState<CostData | null>(null);
  const [files, setFiles]       = useState<FilesData | null>(null);

  const [drawer, setDrawer] = useState<{ agent: string; files: string[]; byAgent: Record<string, string[]> } | null>(null);

  const st          = task.status.toLowerCase();
  const isApproval  = st.includes("approval");
  const isCompleted = st.includes("complete");
  const isFailed    = st.includes("fail") || st.includes("reject");
  const isActive    = !isApproval && !isCompleted && !isFailed;
  const canResume   = isFailed;
  const hasSteps    = detail && detail.steps.length > 0;
  const isProcessing = !detail || !hasSteps;

  /* Fetch mission data */
  useEffect(() => {
    if (task.id.startsWith("demo-")) { setMission(null); return; }
    let alive = true;
    void (async () => {
      const data = await readJson<MissionData>(`${API_BASE}/v1/tasks/${task.id}/mission`);
      if (alive) setMission(data);
    })();
    return () => { alive = false; };
  }, [task.id, detail?.steps.length]);

  /* Fetch side data (collab, gov, costs, files) — lifted from SidePanel */
  const fetchSideData = useCallback(async () => {
    if (task.id.startsWith("demo-")) return;
    const [cb, gv, c, f] = await Promise.all([
      readJson<CollaborationData>(`${API_BASE}/v1/tasks/${task.id}/collaboration`),
      readJson<GovernanceData>(`${API_BASE}/v1/tasks/${task.id}/governance`),
      readJson<CostData>(`${API_BASE}/v1/tasks/${task.id}/costs`),
      readJson<FilesData>(`${API_BASE}/v1/tasks/${task.id}/files`),
    ]);
    if (cb) setCollab(cb);
    if (gv) setGov(gv);
    if (c)  setCosts(c);
    if (f)  setFiles(f);
  }, [task.id]);

  useEffect(() => { void fetchSideData(); }, [fetchSideData]);
  useEffect(() => { void fetchSideData(); }, [detail?.steps.length, fetchSideData]);

  /* Build file data for drawer */
  const allFilesData = files?.files.length
    ? files
    : {
        files: [...new Set((detail?.steps ?? []).flatMap((s) => s.files_changed))],
        by_agent: (detail?.steps ?? []).reduce<Record<string, string[]>>((acc, s) => {
          if (s.files_changed.length) acc[s.agent] = s.files_changed;
          return acc;
        }, {}),
      };

  function openFilesDrawer(agent: string, agentFiles: string[]) {
    setDrawer({
      agent,
      files: agentFiles,
      byAgent: allFilesData.by_agent,
    });
  }

  return (
    <div className="animate-fadeup h-full flex flex-col">
      {/* ── Header bar ── */}
      <div className="mb-4 pb-3 border-b border-[var(--ui-border)] flex-shrink-0">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-base font-bold text-[var(--ui-text)] leading-tight flex-1 min-w-0">{task.title}</h2>
          {/* Open in editor — top right of header */}
          {projectPath && onOpenInEditor && (
            <OpenInEditorBtn
              projectPath={projectPath}
              onOpen={onOpenInEditor}
            />
          )}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className={tierClass(task.tier)}>{task.tier}</span>
          <span className={statusClass(task.status)}>{task.status}</span>
          {detail?.task_type && (
            <span className="text-[10px] rounded-md px-2 py-0.5 bg-[rgba(0,0,0,0.04)] text-[var(--ui-text-secondary)] font-medium">
              {detail.task_type}
            </span>
          )}
          <span className="text-[10px] text-[var(--ui-text-subtle)]">{"\u00B7"} {task.updatedAt}</span>

          {/* Action buttons */}
          <div className="ml-auto flex items-center gap-2">
            {isApproval && (
              <span className="text-[11px] font-medium text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-2 py-1">
                Awaiting approval ↓
              </span>
            )}
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

      {/* ── Approval banner ── */}
      {isApproval && (
        <div className="approval-banner animate-fadeup animate-border-pulse">
          <div className="approval-banner-info">
            <span className="approval-banner-icon">✋</span>
            <div>
              <p className="approval-banner-title">Your approval is needed</p>
              <p className="approval-banner-desc">
                Review the agent work below, then approve to continue or reject to stop the run.
              </p>
            </div>
          </div>
          <div className="approval-banner-actions">
            <button type="button" className="primary-btn"
              onClick={() => onAction(`/v1/tasks/${task.id}/approve`, { action: "approve", resume_now: true })}>
              Approve &amp; Resume
            </button>
            <button type="button" className="warn-btn"
              onClick={() => onAction(`/v1/tasks/${task.id}/deny`, { reason: "Rejected by operator" })}>
              Reject
            </button>
          </div>
        </div>
      )}

      {/* ── Unified feed ── */}
      {isProcessing ? (
        <ProcessingState status={task.status} />
      ) : (
        <div className="task-layout flex-1 min-h-0">
          <div className="overflow-y-auto">
            <AgentTimeline
              steps={detail.steps}
              taskType={detail.task_type}
              collab={collab}
              gov={gov}
              costs={costs}
              onOpenFiles={openFilesDrawer}
            />
          </div>
        </div>
      )}

      {/* ── Files bottom drawer ── */}
      {drawer && (
        <FilesDrawer
          taskId={task.id}
          agent={drawer.agent}
          files={drawer.files}
          byAgent={drawer.byAgent}
          onClose={() => setDrawer(null)}
        />
      )}
    </div>
  );
}
