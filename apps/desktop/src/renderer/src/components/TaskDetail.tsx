/* ------------------------------------------------------------------ */
/*  TaskDetail — split control plane                                    */
/*  Left: Map (graph) or Timeline toggle | Right: agent detail panel   */
/* ------------------------------------------------------------------ */
import { useCallback, useEffect, useRef, useState } from "react";
import type { InboxTask, TaskDetail as TaskDetailType, TaskStep } from "../types";
import { tierClass, statusClass } from "../defaults";
import { API_BASE, readJson } from "../api";
import AgentTimeline from "./AgentTimeline";
import type { CollaborationData, GovernanceData, CostData } from "./AgentTimeline";
import NeuralCalibrationMap from "./NeuralCalibrationMap";
import FileViewer from "./FileViewer";
import AgentDetailPanel from "./AgentDetailPanel";

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

/* ---- Role label helper (keeps TaskDetail independent of AgentDetailPanel internals) ---- */
const AGENT_LABELS: Record<string, string> = {
  master: "Chief Architect", planner: "Project Manager", coder: "Software Engineer",
  reviewer: "Code Reviewer", security: "Security Engineer", qa: "QA Engineer",
  devops: "DevOps Engineer", sre: "SRE Engineer", lead: "Tech Lead",
  rigour: "Quality Gates", memory: "Knowledge Base",
};
function agentLabel(role: string): string {
  return AGENT_LABELS[role.toLowerCase()] ?? (role.charAt(0).toUpperCase() + role.slice(1));
}

/* ---- Elapsed time hook ---- */
function useElapsed(startedAt: string | null): string | null {
  const [secs, setSecs] = useState<number | null>(null);
  useEffect(() => {
    if (!startedAt) { setSecs(null); return; }
    const update = () => setSecs(Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000));
    update();
    const t = setInterval(update, 1000);
    return () => clearInterval(t);
  }, [startedAt]);
  if (secs === null || secs < 0) return null;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
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

  /* Live elapsed timer */
  const startRef = useRef(Date.now());
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (isTerminal) return;
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)), 1000);
    return () => clearInterval(id);
  }, [isTerminal]);
  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  const elapsedStr = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;

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
        <div className="flex-1">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold" style={{ color: "var(--t1)" }}>Master Brain</p>
            <span className="text-[11px] font-mono tabular-nums" style={{ color: "var(--t3)" }}>{elapsedStr}</span>
          </div>
          <p className="text-[11px]" style={{ color: "var(--t3)" }}>Coordinating virtual team</p>
        </div>
      </div>
      <div className="mt-4 rounded-xl border border-[var(--border)] bg-[rgba(0,0,0,0.03)] p-4">
        <h3 className="text-sm font-semibold" style={{ color: "var(--t1)" }}>{phase.title}</h3>
        <p className="mt-1 text-[13px] leading-relaxed" style={{ color: "var(--t3)" }}>{phase.desc}</p>
      </div>
      {/* Progress steps — show which phases are done */}
      <div className="mt-3 flex items-center gap-3">
        {["classifying", "routing", "assembling"].map((p) => {
          const done = st.includes(p) ? false : (
            p === "classifying" ? (st.includes("routing") || st.includes("assembl") || st.includes("running")) :
            p === "routing" ? (st.includes("assembl") || st.includes("running")) :
            st.includes("running")
          );
          const active = st.includes(p);
          return (
            <div key={p} className="flex items-center gap-1.5">
              <span className={`inline-block h-2 w-2 rounded-full ${done ? "bg-emerald-500" : active ? "bg-[var(--accent)] animate-pulse" : "bg-[rgba(0,0,0,0.1)]"}`} />
              <span className="text-[10px] capitalize" style={{ color: done ? "var(--s-complete)" : active ? "var(--accent)" : "var(--t4)" }}>{p === "assembling" ? "setup" : p === "classifying" ? "analyze" : "staff"}</span>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex items-center gap-2" style={{ color: "var(--t3)" }}>
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-1" />
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-2" />
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-3" />
        <span className="text-[11px] italic">{phase.desc.split("—")[0].trim()}…</span>
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
  const [error, setError] = useState<string>("");

  if (!projectPath || !projectPath.trim()) {
    return null;
  }

  const handleEditorClick = async (editorId: string) => {
    try {
      const editor = EDITORS.find(e => e.id === editorId);
      if (!editor) return;
      const url = editor.scheme(projectPath);
      onOpen(url);
      setOpen(false);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to open editor");
      window.setTimeout(() => setError(""), 3000);
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        className="ghost-btn text-xs py-1.5 px-3 flex items-center gap-1.5"
        onClick={() => setOpen((v) => !v)}
        title="Open project in editor"
        disabled={error !== ""}
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
      {open && !error && (
        <div
          className="absolute right-0 top-full mt-1 z-40 bg-[var(--canvas)] border border-[var(--border)] rounded-xl shadow-lg overflow-hidden py-1 min-w-[130px]"
          onMouseLeave={() => setOpen(false)}
        >
          {EDITORS.map((e) => (
            <button
              key={e.id}
              type="button"
              className="flex items-center gap-2 w-full px-3 py-2 text-left text-[12px] text-[var(--t2)] hover:bg-[rgba(0,0,0,0.04)] transition-colors"
              onClick={() => void handleEditorClick(e.id)}
            >
              <span className="text-base leading-none">{e.icon}</span>
              {e.label}
            </button>
          ))}
        </div>
      )}
      {error && (
        <div className="absolute right-0 top-full mt-1 z-40 bg-red-50 border border-red-200 rounded-xl shadow-lg overflow-hidden py-2 px-3 min-w-[200px] text-[11px] text-red-700">
          {error}
        </div>
      )}
    </div>
  );
}

/* ================================================================== */
/*  NowStrip — live "what is happening right now" bar                 */
/* ================================================================== */
function NowStrip({ steps }: { steps: TaskStep[] }) {
  const running = steps.find(s => s.status === "running") ?? null;
  const elapsed = useElapsed(running?.started_at ?? null);
  if (!running) return null;

  const done  = steps.filter(s => s.status === "complete").length;
  const total = steps.length;

  return (
    <div className="td-now-strip">
      <span className="td-now-pulse"><span /><span /><span /></span>
      <span className="td-now-agent">{agentLabel(running.agent).toUpperCase()}</span>
      <span className="td-now-sep">·</span>
      <span className="td-now-progress">{done} of {total} agents done</span>
      {elapsed && (
        <>
          <span className="td-now-sep">·</span>
          <span className="td-now-time">{elapsed}</span>
        </>
      )}
    </div>
  );
}

/* ================================================================== */
/*  FailureBar — prominent failure reason when task fails             */
/* ================================================================== */
function FailureBar({ steps, mission, onSelect, pipelineError }: {
  steps: TaskStep[];
  mission: MissionData | null;
  onSelect: (agent: string) => void;
  pipelineError?: string | null;
}) {
  const failedStep = steps.find(s => s.status === "failed");

  // Case 1: A specific agent step failed
  if (failedStep) {
    let reason = "";
    const failedGates = failedStep.gate_results.filter(g => !g.passed);
    if (failedGates.length > 0) {
      reason = failedGates.map(g => g.message || g.gate).join(" · ");
    } else if (failedStep.output.trim()) {
      const lines = failedStep.output.split("\n").filter(l => l.trim());
      reason = lines[lines.length - 1] ?? "";
    } else if (mission?.decision_trace.length) {
      reason = mission.decision_trace[mission.decision_trace.length - 1]?.summary ?? "";
    }

    return (
      <button type="button" className="td-failure-bar" onClick={() => onSelect(failedStep.agent)}>
        <span className="td-failure-icon">✕</span>
        <div className="td-failure-body">
          <span className="td-failure-who">{agentLabel(failedStep.agent)} failed</span>
          {reason && <span className="td-failure-reason">{reason.slice(0, 160)}</span>}
        </div>
        <span className="td-failure-cta">Inspect →</span>
      </button>
    );
  }

  // Case 2: Pipeline-level failure (no specific agent failed, e.g. DAG deadlock)
  if (pipelineError) {
    return (
      <div className="td-failure-bar" style={{ cursor: "default" }}>
        <span className="td-failure-icon">✕</span>
        <div className="td-failure-body">
          <span className="td-failure-who">Pipeline failed</span>
          <span className="td-failure-reason">{pipelineError.slice(0, 200)}</span>
        </div>
      </div>
    );
  }

  return null;
}

/* ================================================================== */
/*  QualitySummaryBar — compact quality metrics after NowStrip        */
/* ================================================================== */
function QualitySummaryBar({ steps, detail }: {
  steps: TaskStep[];
  detail: TaskDetailType | null;
}) {
  if (!detail) return null;

  const allGates = steps.flatMap(s => s.gate_results ?? []);
  const gatesPassed = allGates.filter(g => g.passed).length;
  const gatesTotal = allGates.length;
  const hasDeep = allGates.some(g => g.deep);

  return (
    <div className="td-quality-bar">
      <div className="quality-bar-item">
        <span className="quality-label">Gates:</span>
        <span className={`quality-value ${gatesPassed === gatesTotal && gatesTotal > 0 ? "pass" : "neutral"}`}>
          {gatesPassed}/{gatesTotal}
        </span>
      </div>
      {hasDeep && (
        <div className="quality-bar-item">
          <span className="quality-icon">🧠</span>
          <span className="quality-label">Deep analysis enabled</span>
        </div>
      )}
      {detail.confidence_score !== undefined && (
        <div className="quality-bar-item">
          <span className="quality-label">Confidence:</span>
          <span className={`quality-value ${
            detail.confidence_score >= 80 ? "high" :
            detail.confidence_score >= 60 ? "medium" :
            "low"
          }`}>
            {detail.confidence_score.toFixed(0)}%
          </span>
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
  const [viewMode, setViewMode]           = useState<"map" | "timeline">("map");
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [leftOpen, setLeftOpen]           = useState(true);

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
      try {
        const data = await readJson<MissionData>(`${API_BASE}/v1/tasks/${task.id}/mission`);
        if (alive) setMission(data);
      } catch { /* mission fetch failed */ }
    })();
    return () => { alive = false; };
  }, [task.id, detail?.steps.length]);

  /* Fetch side data (collab, gov, costs, files) */
  const fetchSideData = useCallback(async () => {
    if (task.id.startsWith("demo-")) return;
    const [cb, gv, c, f] = await Promise.all([
      readJson<CollaborationData>(`${API_BASE}/v1/tasks/${task.id}/collaboration`),
      readJson<GovernanceData>(`${API_BASE}/v1/tasks/${task.id}/governance`),
      readJson<CostData>(`${API_BASE}/v1/tasks/${task.id}/costs`),
      readJson<FilesData>(`${API_BASE}/v1/tasks/${task.id}/files`),
    ]);
    if (cb) setCollab(cb);
    if (gv) setGov(gv);  // retained for future governance panel
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

  /* ── Derived stats ── */
  const totalFiles  = allFilesData.files.length;
  const replanCount = mission?.workflow.replan_triggered ?? 0;
  const allGates    = detail?.steps.flatMap(s => s.gate_results) ?? [];
  const gatesFailed = allGates.filter(g => !g.passed).length;

  return (
    <div className="animate-fadeup h-full flex flex-col">

      {/* ── Compact header ── */}
      <div className="td-header flex-shrink-0">
        <div className="td-header-left">
          <h2 className="td-title">{task.title}</h2>
          <div className="td-badges">
            <span className={tierClass(task.tier)}>{task.tier}</span>
            <span className={statusClass(task.status)}>{task.status}</span>
            {detail?.task_type && (
              <span className="td-type-badge">{detail.task_type}</span>
            )}
            {detail?.complexity && (
              <span className={`td-type-badge ${
                detail.complexity === "critical" ? "td-complexity-critical" :
                detail.complexity === "high" ? "td-complexity-high" :
                detail.complexity === "medium" ? "td-complexity-medium" :
                "td-complexity-low"
              }`}>{detail.complexity}</span>
            )}
            {detail?.confidence_score !== undefined && detail.status !== "running" && detail.status !== "pending" && (
              <span className={`td-confidence-badge ${
                detail.confidence_score >= 80 ? "confidence-high" :
                detail.confidence_score >= 60 ? "confidence-medium" :
                "confidence-low"
              }`}>
                <span className="confidence-icon">
                  {detail.confidence_score >= 80 ? "🛡" : detail.confidence_score >= 60 ? "⚠" : "❌"}
                </span>
                {detail.confidence_score.toFixed(0)}% Confidence
              </span>
            )}
            <span className="td-updated">{task.updatedAt}</span>
            {isApproval && (
              <span className="td-approval-chip">✋ Awaiting approval</span>
            )}
            {replanCount > 0 && (
              <span className="td-replan-chip">↺ {replanCount} replan{replanCount !== 1 ? "s" : ""}</span>
            )}
            {gatesFailed > 0 && (
              <span className="td-gate-fail-chip">⚡ {gatesFailed} gate{gatesFailed !== 1 ? "s" : ""} failed</span>
            )}
          </div>
        </div>
        <div className="td-header-right">
          {/* View toggle: Map ↔ Timeline */}
          {hasSteps && (
            <div className="td-view-toggle">
              <button
                type="button"
                className={`td-view-btn ${viewMode === "map" ? "active" : ""}`}
                onClick={() => setViewMode("map")}
                title="Neural Calibration Map"
              >
                ◉ Map
              </button>
              <button
                type="button"
                className={`td-view-btn ${viewMode === "timeline" ? "active" : ""}`}
                onClick={() => setViewMode("timeline")}
                title="Agent Timeline"
              >
                ☰ Timeline
              </button>
            </div>
          )}
          {projectPath && onOpenInEditor && (
            <OpenInEditorBtn projectPath={projectPath} onOpen={onOpenInEditor} />
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

      {/* ── Live status strip (running) ── */}
      {isActive && hasSteps && <NowStrip steps={detail!.steps} />}

      {/* ── Failure reason bar ── */}
      {isFailed && (
        <FailureBar
          steps={detail?.steps ?? []}
          mission={mission}
          onSelect={setSelectedAgent}
          pipelineError={detail?.error}
        />
      )}

      {/* ── Quality summary bar ── */}
      {hasSteps && <QualitySummaryBar steps={detail!.steps} detail={detail} />}

      {/* ── Split layout: map or timeline (left) + agent detail (right) ── */}
      <div className={`td-map-layout flex-1 min-h-0 ${leftOpen ? "" : "td-map-layout--collapsed"}`}>

        {/* Panel collapse/expand toggle — sits on the divider */}
        {hasSteps && (
          <button
            type="button"
            className="td-panel-toggle"
            onClick={() => setLeftOpen(v => !v)}
            title={leftOpen ? "Collapse panel" : "Expand panel"}
            aria-label={leftOpen ? "Collapse left panel" : "Expand left panel"}
          >
            {leftOpen ? "‹" : "›"}
          </button>
        )}

        {/* Left: Neural Map or Timeline */}
        {viewMode === "map" ? (
          <div className={`td-map-left ${leftOpen ? "" : "td-panel-hidden"}`}>
            {isProcessing ? (
              <div className="td-map-processing">
                <ProcessingState status={task.status} />
              </div>
            ) : (
              <NeuralCalibrationMap
                steps={detail.steps}
                taskStatus={task.status}
                taskType={detail.task_type}
                collab={collab}
                totalFiles={totalFiles}
                totalCost={costs?.total_cost_usd ?? 0}
                replanCount={replanCount}
                gatesTotal={allGates.length}
                gatesFailed={gatesFailed}
                selectedAgent={selectedAgent}
                onSelectAgent={setSelectedAgent}
              />
            )}
          </div>
        ) : (
          <div className={`td-timeline-left ${leftOpen ? "" : "td-panel-hidden"}`}>
            {isProcessing ? (
              <div className="p-4"><ProcessingState status={task.status} /></div>
            ) : (
              <AgentTimeline
                steps={detail.steps}
                taskType={detail.task_type ?? "engineering"}
                collab={collab}
                gov={gov}
                costs={costs}
                onOpenFiles={openFilesDrawer}
              />
            )}
          </div>
        )}

        {/* Right: agent detail panel */}
        <div className="td-map-right">
          <AgentDetailPanel
            steps={detail?.steps ?? []}
            taskStatus={task.status}
            selectedRole={selectedAgent}
            collab={collab}
            costs={costs}
            totalFiles={totalFiles}
            replanCount={replanCount}
            onOpenFiles={openFilesDrawer}
            isApproval={isApproval}
            onApprove={() => onAction(`/v1/tasks/${task.id}/approve`, { action: "approve", resume_now: true })}
            onReject={()  => onAction(`/v1/tasks/${task.id}/deny`,    { reason: "Rejected by operator" })}
          />
        </div>
      </div>

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
