/* ------------------------------------------------------------------ */
/*  TaskDetail — split control plane                                    */
/*  Left: Map (graph) or Timeline toggle | Right: agent detail panel   */
/* ------------------------------------------------------------------ */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  InboxTask,
  TaskDetail as TaskDetailType,
  TaskStep,
} from "../types";
import { tierClass, statusClass } from "../defaults";
import { API_BASE, readJson } from "../api";
import AgentTimeline from "./AgentTimeline";
import type {
  CollaborationData,
  GovernanceData,
  CostData,
} from "./AgentTimeline";
import NeuralCalibrationMap from "./NeuralCalibrationMap";
import FileViewer from "./FileViewer";
import AgentDetailPanel from "./AgentDetailPanel";
import ResponseRenderer from "./ResponseRenderer";
import {
  canonicalAgentLabel,
  canonicalStepLabel,
  isWorkRole,
  resolveCanonicalRole,
} from "../lib/agentIdentity";

interface TaskDetailProps {
  task: InboxTask;
  detail: TaskDetailType | null;
  onAction: (path: string, body: Record<string, unknown>) => void;
  actionMsg: string;
  projectPath?: string;
  onOpenInEditor?: (path: string) => void;
}

/* ---- Inline types ---- */
interface AuditEntry {
  id: string;
  action: string;
  agent_role: string;
  summary: string;
  created_at: string | null;
}
interface FilesData {
  files: string[];
  by_agent: Record<string, string[]>;
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

function fmtDuration(ms: number | null | undefined): string {
  if (!ms || ms <= 0) return "--";
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  if (m <= 0) return `${s}s`;
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return `${h}h ${mm}m`;
}

function ValueStrip({
  totalTokens,
  totalCostUsd,
  elapsedMs,
  baselineTokens,
  consultCount,
  debateCount,
  cacheSavedTokens,
  cacheSavedCostUsd,
  cacheHitRate,
}: {
  totalTokens: number;
  totalCostUsd: number;
  elapsedMs: number | null;
  baselineTokens: number | null;
  consultCount: number;
  debateCount: number;
  cacheSavedTokens: number;
  cacheSavedCostUsd: number;
  cacheHitRate: number | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasBaseline = baselineTokens != null && baselineTokens > 0;
  const savedPct = hasBaseline
    ? Math.max(0, ((baselineTokens! - totalTokens) / baselineTokens!) * 100)
    : null;
  const hasDetails = true;
  return (
    <div className="td-value-strip">
      <span className="td-value-item">
        <b>{totalTokens.toLocaleString()}</b> tokens
      </span>
      <span className="td-value-sep">·</span>
      <span className="td-value-item">
        <b>${totalCostUsd.toFixed(4)}</b> cost
      </span>
      <span className="td-value-sep">·</span>
      <span className="td-value-item">
        <b>{fmtDuration(elapsedMs)}</b> time
      </span>
      {hasDetails && (
        <button
          type="button"
          className="td-value-toggle"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Less details" : "More details"}
        </button>
      )}
      {expanded && (
        <>
          <span className="td-value-sep">·</span>
          <span className="td-value-item">
            baseline:{" "}
            <b>{hasBaseline ? baselineTokens!.toLocaleString() : "pending"}</b>
          </span>
          <span className="td-value-sep">·</span>
          <span className={`td-value-item ${savedPct != null ? "save" : ""}`}>
            saved: <b>{savedPct != null ? `${savedPct.toFixed(1)}%` : "--"}</b>
          </span>
          {(consultCount > 0 || debateCount > 0) && (
            <>
              <span className="td-value-sep">·</span>
              <span className="td-value-item">
                consult {consultCount} · debate {debateCount}
              </span>
            </>
          )}
          {(cacheSavedTokens > 0 ||
            cacheSavedCostUsd > 0 ||
            (cacheHitRate != null && cacheHitRate > 0)) && (
            <>
              <span className="td-value-sep">·</span>
              <span className="td-value-item">
                cache: <b>{cacheSavedTokens.toLocaleString()}</b> tok
                {cacheSavedCostUsd > 0 ? (
                  <>
                    {" "}
                    · <b>${cacheSavedCostUsd.toFixed(4)}</b>
                  </>
                ) : null}
                {cacheHitRate != null ? (
                  <>
                    {" "}
                    · hit <b>{cacheHitRate.toFixed(1)}%</b>
                  </>
                ) : null}
              </span>
            </>
          )}
        </>
      )}
    </div>
  );
}

function progressFromSteps(steps: TaskStep[]): {
  completed: number;
  total: number;
} {
  const byRole = new Map<string, { completed: boolean }>();
  for (const s of steps) {
    const role = resolveCanonicalRole(s.agent_role || s.agent);
    if (!isWorkRole(role)) continue;
    const prev = byRole.get(role) ?? { completed: false };
    if (s.status === "complete") prev.completed = true;
    byRole.set(role, prev);
  }
  const completed = Array.from(byRole.values()).filter(
    (v) => v.completed,
  ).length;
  return { completed, total: byRole.size };
}

/* ---- Elapsed time hook ---- */
function useElapsed(startedAt: string | null): string | null {
  const [secs, setSecs] = useState<number | null>(null);
  useEffect(() => {
    if (!startedAt) {
      setSecs(null);
      return;
    }
    const update = () =>
      setSecs(Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000));
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
const PHASE_INFO: Record<
  string,
  { icon: string; title: string; desc: string }
> = {
  classifying: {
    icon: "\uD83E\uDDE0",
    title: "Analyzing your request",
    desc: "Reading your task and determining the type of work — feature, bugfix, refactor, infra...",
  },
  routing: {
    icon: "\uD83D\uDDFA\uFE0F",
    title: "Assembling the right team",
    desc: "Selecting which agents to involve based on task complexity and type.",
  },
  assembling: {
    icon: "\u2699\uFE0F",
    title: "Setting up the pipeline",
    desc: "Building the execution plan — which agents run in sequence, which in parallel.",
  },
  pending: {
    icon: "\u23F3",
    title: "Queued",
    desc: "Your task is in the queue and will start shortly.",
  },
};

function getPhase(status: string) {
  for (const [key, info] of Object.entries(PHASE_INFO)) {
    if (status.includes(key)) return info;
  }
  return {
    icon: "\uD83D\uDD04",
    title: "Processing",
    desc: "Your task is being processed...",
  };
}

/* ================================================================== */
/*  ProcessingState                                                    */
/* ================================================================== */
function ProcessingState({
  status,
  taskType,
  latestDecision,
  startedAt,
  masterThinkingMs,
  masterWaitingMs,
}: {
  status: string;
  taskType?: string;
  latestDecision?: string;
  startedAt?: string | null;
  masterThinkingMs?: number | null;
  masterWaitingMs?: number | null;
}) {
  const st = status.toLowerCase();
  const isFailed = st.includes("fail") || st.includes("reject");
  const isCompleted = st.includes("complete");
  const isTerminal = isFailed || isCompleted;

  /* Live elapsed timer (stable across remounts when startedAt is provided) */
  const startRef = useRef(Date.now());
  const [elapsed, setElapsed] = useState(0);
  const elapsedFromStart = useElapsed(startedAt ?? null);
  useEffect(() => {
    if (isTerminal) return;
    if (startedAt) return; // useElapsed handles the timer when backend timestamp exists
    const id = setInterval(
      () => setElapsed(Math.floor((Date.now() - startRef.current) / 1000)),
      1000,
    );
    return () => clearInterval(id);
  }, [isTerminal, startedAt]);
  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  const fallbackElapsed = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
  const elapsedStr = elapsedFromStart ?? fallbackElapsed;
  const hasSplitTiming =
    (masterThinkingMs ?? 0) > 0 || (masterWaitingMs ?? 0) > 0;

  if (isTerminal) {
    return (
      <div className="animate-fadeup rounded-2xl border border-[var(--border)] bg-[rgba(0,0,0,0.02)] p-5">
        <div className="flex items-center gap-3">
          <div
            className={`flex h-10 w-10 items-center justify-center rounded-2xl text-lg ${isFailed ? "bg-rose-500/15" : "bg-emerald-500/15"}`}
          >
            {isFailed ? "✕" : "✓"}
          </div>
          <div>
            <p className="text-sm font-semibold" style={{ color: "var(--t1)" }}>
              Master Brain
            </p>
            <p className="text-[11px]" style={{ color: "var(--t3)" }}>
              {isFailed
                ? "Run ended with failures"
                : "Run finished successfully"}
            </p>
          </div>
        </div>
        <p className="mt-3 text-[13px]" style={{ color: "var(--t3)" }}>
          {isFailed
            ? "Review evidence and retry from the failed phase."
            : "All queued agents completed and governance checks passed."}
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
            <p className="text-sm font-semibold" style={{ color: "var(--t1)" }}>
              Master Brain
            </p>
            <span
              className="text-[11px] font-mono tabular-nums"
              style={{ color: "var(--t3)" }}
            >
              {elapsedStr}
            </span>
          </div>
          <p className="text-[11px]" style={{ color: "var(--t3)" }}>
            Coordinating virtual team
          </p>
          {hasSplitTiming && (
            <p className="text-[11px]" style={{ color: "var(--t3)" }}>
              thinking {fmtDuration(masterThinkingMs)} • waiting{" "}
              {fmtDuration(masterWaitingMs)}
            </p>
          )}
        </div>
      </div>
      <div className="mt-4 rounded-xl border border-[var(--border)] bg-[rgba(0,0,0,0.03)] p-4">
        <h3 className="text-sm font-semibold" style={{ color: "var(--t1)" }}>
          {phase.title}
        </h3>
        <p
          className="mt-1 text-[13px] leading-relaxed"
          style={{ color: "var(--t3)" }}
        >
          {phase.desc}
        </p>
        {taskType && taskType !== "unclassified" && (
          <p className="mt-2 text-[11px]" style={{ color: "var(--t3)" }}>
            Intent detected:{" "}
            <span
              className="font-semibold capitalize"
              style={{ color: "var(--t2)" }}
            >
              {taskType}
            </span>
          </p>
        )}
        {latestDecision && (
          <p className="mt-1 text-[11px]" style={{ color: "var(--t3)" }}>
            Latest decision: {latestDecision}
          </p>
        )}
      </div>
      {/* Progress steps — show which phases are done */}
      <div className="mt-3 flex items-center gap-3">
        {["classifying", "routing", "assembling"].map((p) => {
          const done = st.includes(p)
            ? false
            : p === "classifying"
              ? st.includes("routing") ||
                st.includes("assembl") ||
                st.includes("running")
              : p === "routing"
                ? st.includes("assembl") || st.includes("running")
                : st.includes("running");
          const active = st.includes(p);
          return (
            <div key={p} className="flex items-center gap-1.5">
              <span
                className={`inline-block h-2 w-2 rounded-full ${done ? "bg-emerald-500" : active ? "bg-[var(--accent)] animate-pulse" : "bg-[rgba(0,0,0,0.1)]"}`}
              />
              <span
                className="text-[10px] capitalize"
                style={{
                  color: done
                    ? "var(--s-complete)"
                    : active
                      ? "var(--accent)"
                      : "var(--t4)",
                }}
              >
                {p === "assembling"
                  ? "setup"
                  : p === "classifying"
                    ? "analyze"
                    : "staff"}
              </span>
            </div>
          );
        })}
      </div>
      <div
        className="mt-2 flex items-center gap-2"
        style={{ color: "var(--t3)" }}
      >
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-1" />
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-2" />
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-3" />
        <span className="text-[11px] italic">
          {phase.desc.split("—")[0].trim()}…
        </span>
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
    mission.risk.level === "high"
      ? "#b91c1c"
      : mission.risk.level === "medium"
        ? "#b45309"
        : "#15803d";
  const riskBg =
    mission.risk.level === "high"
      ? "rgba(220,38,38,0.08)"
      : mission.risk.level === "medium"
        ? "rgba(217,119,6,0.08)"
        : "rgba(22,163,74,0.08)";

  return (
    <div className="mb-4 animate-fadeup flex-shrink-0">
      <div className="flex flex-wrap gap-1.5 mb-3">
        <span
          className="mission-stat"
          style={{ color: riskColor, background: riskBg }}
        >
          Risk: {mission.risk.level}
        </span>
        <span className="mission-stat">
          {mission.team.size} agent{mission.team.size === 1 ? "" : "s"} ·{" "}
          {mission.team.roles.slice(0, 4).join(", ")}
          {mission.team.roles.length > 4
            ? ` +${mission.team.roles.length - 4}`
            : ""}
        </span>
        <span
          className="mission-stat"
          style={{ color: "#15803d", background: "rgba(22,163,74,0.07)" }}
        >
          ${mission.cost.total_cost_usd.toFixed(4)} ·{" "}
          {mission.cost.total_tokens.toLocaleString()} tokens
        </span>
        {mission.workflow.approvals_requested > 0 && (
          <span className="mission-stat">
            {mission.workflow.approvals_granted}/
            {mission.workflow.approvals_requested} approved
          </span>
        )}
        {mission.workflow.replan_triggered > 0 && (
          <span
            className="mission-stat"
            style={{ color: "#b45309", background: "rgba(217,119,6,0.07)" }}
          >
            {mission.workflow.replan_triggered} replan
            {mission.workflow.replan_triggered === 1 ? "" : "s"}
          </span>
        )}
      </div>

      {mission.decision_trace.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--t4)] mb-2">
            Recent decisions
          </p>
          {mission.decision_trace.slice(-4).map((evt, idx) => (
            <div
              key={`${evt.action}-${idx}`}
              className="flex items-start gap-2 py-1.5 text-[11px] border-b border-[var(--border)] last:border-0"
            >
              <span className="text-[var(--t4)] w-10 flex-shrink-0 tabular-nums font-mono">
                {evt.ts
                  ? new Date(evt.ts).toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })
                  : "--:--"}
              </span>
              <span className="text-[10px] rounded bg-[rgba(0,0,0,0.04)] px-1.5 py-0.5 text-[var(--t3)] flex-shrink-0">
                {evt.actor || "system"}
              </span>
              <span className="text-[var(--t2)] leading-snug">
                {evt.summary || evt.action}
              </span>
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
              <span
                className={`pipeline-arrow ${prevComplete ? "complete" : ""}`}
              />
            )}
            <div
              className={`pipeline-node ${isRunning ? "running pipeline-running" : step.status}`}
              title={`${step.agent_name || step.agent}: ${step.status}`}
            >
              <span className="pipeline-dot" />
              <span>
                {step.agent_name ||
                  canonicalAgentLabel(step.agent_role || step.agent)}
              </span>
            </div>
          </div>
        );
      })}
      {runningIdx >= 0 &&
        runningIdx < steps.length - 1 &&
        (() => {
          const queuedCount = steps
            .slice(runningIdx + 1)
            .filter((s) => s.status === "pending").length;
          return queuedCount > 0 ? (
            <div className="flex items-center gap-0">
              <span className="pipeline-arrow" />
              <span className="text-[10px] text-[var(--t4)] px-2">
                +{queuedCount} queued
              </span>
            </div>
          ) : null;
        })()}
    </div>
  );
}

/* ================================================================== */
/*  InlineLogViewer — terminal-style per-agent output panel           */
/* ================================================================== */
interface InlineLogViewerProps {
  steps: TaskStep[];
  taskStatus: string;
}

function InlineLogViewer({ steps, taskStatus }: InlineLogViewerProps) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const bottomRef = useRef<HTMLDivElement>(null);
  const isRunning = taskStatus === "running" || taskStatus === "queued";

  // Auto-expand the currently running step; auto-scroll to bottom while running
  useEffect(() => {
    const runningStep = steps.find((s) => s.status === "running");
    if (runningStep) {
      setExpanded((prev) => ({ ...prev, [runningStep.agent]: true }));
    }
  }, [steps]);

  useEffect(() => {
    if (isRunning && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [steps, isRunning]);

  const allExpanded = steps.every((s) => expanded[s.agent]);

  return (
    <div className="inline-log-viewer">
      {/* toolbar */}
      <div className="ilv-toolbar">
        <span className="ilv-toolbar-title">
          <span className="ilv-dot" />
          Agent Logs
        </span>
        <div className="ilv-toolbar-actions">
          {isRunning && <span className="ilv-live-badge">● LIVE</span>}
          <button
            type="button"
            className="ilv-toggle-all"
            onClick={() => {
              const next = !allExpanded;
              setExpanded(
                steps.reduce<Record<string, boolean>>((a, s) => {
                  a[s.agent] = next;
                  return a;
                }, {}),
              );
            }}
          >
            {allExpanded ? "Collapse all" : "Expand all"}
          </button>
        </div>
      </div>

      {/* log entries */}
      <div className="ilv-body">
        {steps.length === 0 && (
          <div className="ilv-empty">No agent output yet.</div>
        )}
        {steps.map((step, i) => {
          const isOpen =
            expanded[step.agent] !== false &&
            (step.status === "running" ||
              step.status === "complete" ||
              step.status === "failed" ||
              expanded[step.agent] === true);
          const statusIcon =
            step.status === "complete"
              ? "✓"
              : step.status === "failed"
                ? "✗"
                : step.status === "running"
                  ? "▶"
                  : step.status === "skipped"
                    ? "○"
                    : "·";
          const statusColor =
            step.status === "complete"
              ? "var(--color-success, #22c55e)"
              : step.status === "failed"
                ? "var(--color-error, #ef4444)"
                : step.status === "running"
                  ? "var(--accent, #6366f1)"
                  : "var(--t4)";
          const gatesFailed = step.gate_results.filter((g) => !g.passed).length;
          const durationSec =
            step.duration_ms != null
              ? (step.duration_ms / 1000).toFixed(1)
              : null;

          return (
            <div
              key={`${step.agent}-${i}`}
              className={`ilv-block ${step.status}`}
            >
              {/* block header (clickable) */}
              <button
                type="button"
                className="ilv-block-header"
                onClick={() =>
                  setExpanded((prev) => ({ ...prev, [step.agent]: !isOpen }))
                }
                aria-expanded={isOpen}
              >
                <span className="ilv-chevron">{isOpen ? "▾" : "▸"}</span>
                <span
                  className="ilv-status-icon"
                  style={{ color: statusColor }}
                >
                  {statusIcon}
                </span>
                <span className="ilv-agent-name">
                  {canonicalStepLabel(step)}
                </span>
                <div className="ilv-block-meta">
                  {gatesFailed > 0 && (
                    <span className="ilv-gate-badge">
                      ⚡ {gatesFailed} gate{gatesFailed > 1 ? "s" : ""}
                    </span>
                  )}
                  {step.tokens != null && (
                    <span className="ilv-tokens">
                      {step.tokens.toLocaleString()} tok
                    </span>
                  )}
                  {durationSec && (
                    <span className="ilv-duration">{durationSec}s</span>
                  )}
                  <span
                    className="ilv-step-status"
                    style={{ color: statusColor }}
                  >
                    {step.status}
                  </span>
                </div>
              </button>

              {/* output body */}
              {isOpen && (
                <div className="ilv-output">
                  {/* gate results */}
                  {step.gate_results.length > 0 && (
                    <div className="ilv-gates">
                      {step.gate_results.map((g, gi) => (
                        <div
                          key={gi}
                          className={`ilv-gate-row ${g.passed ? "passed" : "failed"}`}
                        >
                          <span className="ilv-gate-icon">
                            {g.passed ? "✓" : "✗"}
                          </span>
                          <span className="ilv-gate-name">{g.gate}</span>
                          {!g.passed && (
                            <span className="ilv-gate-msg">{g.message}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                  {/* execution log (commands run) */}
                  {step.execution_log && step.execution_log.length > 0 && (
                    <div className="ilv-exec-log">
                      {step.execution_log.map((entry, ei) => (
                        <div
                          key={ei}
                          className={`ilv-exec-entry ${entry.exit_code === 0 ? "ok" : "err"}`}
                        >
                          <span className="ilv-exec-prompt">$</span>
                          <span className="ilv-exec-cmd">{entry.command}</span>
                          <span
                            className={`ilv-exec-code ${entry.exit_code === 0 ? "ok" : "err"}`}
                          >
                            [{entry.exit_code}]
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                  {/* main agent output text */}
                  {step.output ? (
                    <ResponseRenderer
                      output={step.output}
                      maxHeightClass="max-h-[420px]"
                    />
                  ) : step.status === "running" ? (
                    <div className="ilv-running-pulse">
                      Running
                      <span className="ilv-dots" />
                    </div>
                  ) : (
                    <div className="ilv-no-output">No output recorded.</div>
                  )}
                </div>
              )}
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
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

function FilesDrawer({
  taskId,
  agent,
  files,
  byAgent,
  onClose,
}: FilesDrawerProps) {
  return (
    <>
      <div className="files-drawer-overlay" onClick={onClose} />
      <div className="files-drawer">
        <div className="files-drawer-header">
          <span className="text-base">📁</span>
          <span
            className="text-[11px] font-semibold"
            style={{ color: "var(--t1)" }}
          >
            Files changed by {agent.charAt(0).toUpperCase() + agent.slice(1)}
          </span>
          <span className="text-[10px] rounded-full px-2 py-0.5 bg-[rgba(0,0,0,0.05)] text-[var(--t3)]">
            {files.length} file{files.length !== 1 ? "s" : ""}
          </span>
          <button
            type="button"
            className="files-drawer-close"
            onClick={onClose}
            aria-label="Close files"
          >
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
  {
    id: "vscode",
    label: "VS Code",
    icon: "⬡",
    scheme: (p: string) => `vscode://file/${encodeURIComponent(p)}`,
  },
  {
    id: "cursor",
    label: "Cursor",
    icon: "◈",
    scheme: (p: string) => `cursor://file/${encodeURIComponent(p)}`,
  },
  {
    id: "zed",
    label: "Zed",
    icon: "◆",
    scheme: (p: string) => `zed://file/${encodeURIComponent(p)}`,
  },
];

function OpenInEditorBtn({
  projectPath,
  onOpen,
}: {
  projectPath: string;
  onOpen: (url: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string>("");

  if (!projectPath || !projectPath.trim()) {
    return null;
  }

  const handleEditorClick = async (editorId: string) => {
    try {
      const editor = EDITORS.find((e) => e.id === editorId);
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
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <rect x="1" y="1.5" width="10" height="9" rx="1.5" />
          <path d="M4 4.5l2 1.5-2 1.5M7 7.5h2" />
        </svg>
        Open in editor
        <svg
          width="8"
          height="8"
          viewBox="0 0 8 8"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeLinecap="round"
        >
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
  const running = steps.find((s) => s.status === "running") ?? null;
  const elapsed = useElapsed(running?.started_at ?? null);
  if (!running) return null;

  const { completed: done, total } = progressFromSteps(steps);

  return (
    <div className="td-now-strip">
      <span className="td-now-pulse">
        <span />
        <span />
        <span />
      </span>
      <span className="td-now-agent">
        {canonicalAgentLabel(running.agent_role || running.agent).toUpperCase()}
      </span>
      <span className="td-now-sep">·</span>
      <span className="td-now-progress">
        {done} of {total} agents done
      </span>
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
function FailureBar({
  steps,
  mission,
  onSelect,
  pipelineError,
}: {
  steps: TaskStep[];
  mission: MissionData | null;
  onSelect: (agent: string) => void;
  pipelineError?: string | null;
}) {
  const normalizeFailureText = (raw: string): string =>
    raw
      .replace(/Quality gate failed/gi, "Rigour gate failed")
      .replace(/\bQuality Gates\b/g, "Rigour Gates");
  const failedStep = steps.find((s) => s.status === "failed");

  // Case 1: A specific agent step failed
  if (failedStep) {
    let reason = "";
    const failedGates = failedStep.gate_results.filter((g) => !g.passed);
    if (failedGates.length > 0) {
      reason = failedGates.map((g) => g.message || g.gate).join(" · ");
    } else if (failedStep.output.trim()) {
      const lines = failedStep.output.split("\n").filter((l) => l.trim());
      reason = lines[lines.length - 1] ?? "";
    } else if (mission?.decision_trace.length) {
      reason =
        mission.decision_trace[mission.decision_trace.length - 1]?.summary ??
        "";
    }

    return (
      <button
        type="button"
        className="td-failure-bar"
        onClick={() => onSelect(failedStep.agent)}
      >
        <span className="td-failure-icon">✕</span>
        <div className="td-failure-body">
          <span className="td-failure-who">
            {canonicalAgentLabel(failedStep.agent_role || failedStep.agent)}{" "}
            failed
          </span>
          {reason && (
          <span className="td-failure-reason">{reason.slice(0, 160)}</span>
          )}
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
          <span className="td-failure-reason">
            {normalizeFailureText(pipelineError).slice(0, 200)}
          </span>
        </div>
      </div>
    );
  }

  return null;
}

/* ================================================================== */
/*  QualitySummaryBar — compact quality metrics after NowStrip        */
/* ================================================================== */
function QualitySummaryBar({
  steps,
  detail,
}: {
  steps: TaskStep[];
  detail: TaskDetailType | null;
}) {
  if (!detail) return null;

  const allGates = steps.flatMap((s) => s.gate_results ?? []);
  const gatesPassed = allGates.filter((g) => g.passed).length;
  const gatesTotal = allGates.length;
  const hasDeep = allGates.some((g) => g.deep);

  return (
    <div className="td-quality-bar">
      <div className="quality-bar-item">
        <span className="quality-label">Gates:</span>
        <span
          className={`quality-value ${gatesPassed === gatesTotal && gatesTotal > 0 ? "pass" : "neutral"}`}
        >
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
          <span
            className={`quality-value ${
              detail.confidence_score >= 80
                ? "high"
                : detail.confidence_score >= 60
                  ? "medium"
                  : "low"
            }`}
          >
            {detail.confidence_score.toFixed(0)}%
          </span>
        </div>
      )}
    </div>
  );
}

/* ================================================================== */
/*  ControlSummaryBar — first-glance control-plane summary            */
/* ================================================================== */
function ControlSummaryBar({
  nowLabel,
  healthLabel,
  healthTone,
  actionLabel,
}: {
  nowLabel: string;
  healthLabel: string;
  healthTone: "neutral" | "good" | "risk";
  actionLabel: string;
}) {
  return (
    <div className="td-control-summary">
      <div className="td-control-item">
        <span className="td-control-label">Now</span>
        <span className="td-control-value">{nowLabel}</span>
      </div>
      <div className="td-control-divider" />
      <div className="td-control-item">
        <span className="td-control-label">Health</span>
        <span className={`td-control-value ${healthTone}`}>{healthLabel}</span>
      </div>
      <div className="td-control-divider" />
      <div className="td-control-item">
        <span className="td-control-label">Action</span>
        <span className="td-control-value">{actionLabel}</span>
      </div>
    </div>
  );
}

/* ================================================================== */
/*  TaskDetail — main export                                           */
/* ================================================================== */
export default function TaskDetail({
  task,
  detail,
  onAction,
  actionMsg,
  projectPath,
  onOpenInEditor,
}: TaskDetailProps) {
  const [mission, setMission] = useState<MissionData | null>(null);
  const [collab, setCollab] = useState<CollaborationData | null>(null);
  const [gov, setGov] = useState<GovernanceData | null>(null);
  const [costs, setCosts] = useState<CostData | null>(null);
  const [files, setFiles] = useState<FilesData | null>(null);
  const [uiMode, setUiMode] = useState<"focus" | "full">("focus");
  const [viewMode, setViewMode] = useState<"map" | "timeline" | "logs">("map");
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [leftOpen, setLeftOpen] = useState(true);
  const [showAdvancedMeta, setShowAdvancedMeta] = useState(false);
  const [showInsights, setShowInsights] = useState(false);

  const [drawer, setDrawer] = useState<{
    agent: string;
    files: string[];
    byAgent: Record<string, string[]>;
  } | null>(null);

  const st = task.status.toLowerCase();
  const isApproval = st.includes("approval");
  const isCompleted = st.includes("complete");
  const isFailed = st.includes("fail") || st.includes("reject");
  const isActive = !isApproval && !isCompleted && !isFailed;
  const canResume = isFailed;
  const hasSteps = detail && detail.steps.length > 0;
  const hasPlan = detail && (detail.planned_roles?.length ?? 0) > 0;
  // During approval, show the plan (MAP/DAG) even without executed steps
  const isProcessing = !detail || (!hasSteps && !isApproval && !hasPlan);

  /* Fetch mission data */
  useEffect(() => {
    if (task.id.startsWith("demo-")) {
      setMission(null);
      return;
    }
    let alive = true;
    void (async () => {
      try {
        const data = await readJson<MissionData>(
          `${API_BASE}/v1/tasks/${task.id}/mission`,
        );
        if (alive) setMission(data);
      } catch {
        /* mission fetch failed */
      }
    })();
    return () => {
      alive = false;
    };
  }, [task.id, detail?.steps.length]);

  /* Fetch side data (collab, gov, costs, files) */
  const fetchSideData = useCallback(async () => {
    if (task.id.startsWith("demo-")) return;
    const [cb, gv, c, f] = await Promise.all([
      readJson<CollaborationData>(
        `${API_BASE}/v1/tasks/${task.id}/collaboration`,
      ),
      readJson<GovernanceData>(`${API_BASE}/v1/tasks/${task.id}/governance`),
      readJson<CostData>(`${API_BASE}/v1/tasks/${task.id}/costs`),
      readJson<FilesData>(`${API_BASE}/v1/tasks/${task.id}/files`),
    ]);
    if (cb) setCollab(cb);
    if (gv) setGov(gv); // retained for future governance panel
    if (c) setCosts(c);
    if (f) setFiles(f);
  }, [task.id]);

  useEffect(() => {
    void fetchSideData();
  }, [fetchSideData]);
  useEffect(() => {
    void fetchSideData();
  }, [detail?.steps.length, fetchSideData]);

  /* Build file data for drawer */
  const allFilesData = files?.files.length
    ? files
    : {
        files: [
          ...new Set((detail?.steps ?? []).flatMap((s) => s.files_changed)),
        ],
        by_agent: (detail?.steps ?? []).reduce<Record<string, string[]>>(
          (acc, s) => {
            if (s.files_changed.length) acc[s.agent] = s.files_changed;
            return acc;
          },
          {},
        ),
      };

  function openFilesDrawer(agent: string, agentFiles: string[]) {
    setDrawer({
      agent,
      files: agentFiles,
      byAgent: allFilesData.by_agent,
    });
  }

  /* ── Derived stats ── */
  const totalFiles = allFilesData.files.length;
  const replanCount = mission?.workflow.replan_triggered ?? 0;
  const allGates = detail?.steps.flatMap((s) => s.gate_results) ?? [];
  const gatesFailed = allGates.filter((g) => !g.passed).length;
  const expectedAgents =
    mission?.team.size && mission.team.size > 0
      ? mission.team.size
      : detail?.planned_roles?.length && detail.planned_roles.length > 0
        ? detail.planned_roles.length
        : (detail?.steps.length ?? 0);
  const liveStepsCost = (detail?.steps ?? []).reduce(
    (sum, s) => sum + (s.cost_usd ?? 0),
    0,
  );
  const mapTotalCost =
    costs?.total_cost_usd && costs.total_cost_usd > 0
      ? costs.total_cost_usd
      : liveStepsCost;
  const summary = detail?.ui_summary ?? null;
  const summaryMissing = hasSteps && !summary;
  // Derive nextRole from live step data when possible, falling back to ui_summary.
  // This prevents stale "next X" display between polling intervals.
  const nextRole = useMemo(() => {
    const steps = detail?.steps ?? [];
    const runningStep = steps.find((s: any) => s.status === "running");
    if (runningStep) return null; // Already running, no "next"
    const pendingSteps = steps.filter((s: any) => s.status === "pending");
    if (pendingSteps.length > 0) return pendingSteps[0].agent_role || pendingSteps[0].agent;
    return summary?.next_expected_role ?? null;
  }, [detail?.steps, summary]);
  const effectiveTier = summary?.tier_effective ?? "auto";
  const requestedTier = summary?.tier_requested ?? "auto";
  const tierMismatch = effectiveTier !== requestedTier;
  const missionTokens = summary?.tokens_total ?? 0;
  const missionCost = summary?.cost_total_usd ?? 0;
  const runElapsedMs = summary?.elapsed_ms ?? null;
  const masterThinkingMs = summary?.master_thinking_ms ?? null;
  const masterWaitingMs = summary?.master_waiting_ms ?? null;
  const baselineTokens = summary?.baseline_tokens ?? null;
  const consultCount = summary?.consult_count ?? 0;
  const debateCount = summary?.debate_count ?? 0;
  const cacheSavedTokens = summary?.cache_saved_tokens ?? 0;
  const cacheSavedCostUsd = summary?.cache_saved_cost_usd ?? 0;
  const cacheHitRate = summary?.cache_hit_rate ?? null;
  const budgetSoftExtensionsUsed = summary?.budget_soft_extensions_used ?? 0;
  const budgetAutoCompactions = summary?.budget_auto_compactions ?? 0;
  const budgetApprovalPending = summary?.budget_token_approval_pending ?? false;
  const budgetApprovalRequested = summary?.budget_token_approval_requested ?? 0;
  const budgetApprovalGranted = summary?.budget_token_approval_granted ?? 0;
  const budgetAutoApprovedExtensions =
    summary?.budget_auto_approved_extensions ?? 0;
  const remediationRoleName = summary?.remediation_role_name ?? null;
  const remediationFailedGates = summary?.remediation_failed_gates ?? 0;
  const nextExpectedReason = summary?.next_expected_reason ?? null;
  const gatesFailedSummary = summary?.gates_failed ?? gatesFailed;
  const gatesTotalSummary = summary?.gates_total ?? allGates.length;
  const debateHistory = detail?.debate_history ?? [];
  const latestDebate =
    debateHistory.length > 0
      ? debateHistory[debateHistory.length - 1]
      : null;
  const latestDebateRecord = latestDebate as Record<string, unknown> | null;
  const roleLearningMetrics = detail?.role_learning_metrics ?? {};
  const tunedRoleCount = Object.keys(roleLearningMetrics).length;
  const promotedRoleCount = Object.values(roleLearningMetrics).filter((metric) => {
    const promotions = Number((metric as Record<string, unknown>).promotions ?? 0);
    return promotions > 0;
  }).length;
  const gateRemediationPending =
    (summary?.remediation_pending ?? false) ||
    (isActive &&
    (gatesFailedSummary > 0 ||
      String(nextExpectedReason || "")
        .toLowerCase()
        .includes("gate remediation")));
  const workspaceRoot =
    detail?.workspace_root ?? summary?.workspace_root ?? task.workspacePath ?? null;
  const targetRoot = detail?.target_root ?? summary?.target_root ?? workspaceRoot;
  const targetMode = detail?.target_mode ?? summary?.target_mode ?? null;
  const hasAdvancedMeta =
    tierMismatch ||
    replanCount > 0 ||
    consultCount > 0 ||
    debateCount > 0 ||
    budgetSoftExtensionsUsed > 0 ||
    budgetAutoCompactions > 0 ||
    budgetApprovalPending ||
    budgetAutoApprovedExtensions > 0 ||
    cacheSavedTokens > 0 ||
    cacheSavedCostUsd > 0 ||
    (isActive && Boolean(nextRole)) ||
    summaryMissing;
  const progress = progressFromSteps(detail?.steps ?? []);
  const nowLabel = isApproval
    ? "Awaiting approval"
    : budgetApprovalPending
      ? "Awaiting token extension approval"
    : isFailed
      ? "Execution failed"
    : isCompleted
      ? "Run completed"
    : gateRemediationPending
      ? "Running · remediating gate failure"
    : nextRole
      ? `Running · next ${canonicalAgentLabel(nextRole)}`
      : `Running · ${progress.completed}/${progress.total || expectedAgents || 0} done`;
  const healthTone: "neutral" | "good" | "risk" =
    isFailed || gatesFailedSummary > 0
      ? "risk"
      : isCompleted && gatesFailedSummary === 0
        ? "good"
        : "neutral";
  const healthLabel =
    isFailed || gatesFailedSummary > 0
      ? "At risk"
      : isCompleted
        ? "Healthy"
        : detail?.confidence_score != null
          ? `Confidence ${detail.confidence_score.toFixed(0)}%`
          : "Monitoring";
  const actionLabel = isApproval
    ? "Approve or reject"
    : budgetApprovalPending
      ? "Approve extension"
    : isFailed
      ? "Inspect and resume"
    : isCompleted
      ? "Review outputs"
      : "Monitor execution";

  useEffect(() => {
    setShowAdvancedMeta(false);
    setShowInsights(false);
    setUiMode("focus");
  }, [task.id]);

  useEffect(() => {
    if (uiMode === "focus") {
      setViewMode("map");
      setShowInsights(false);
      setShowAdvancedMeta(false);
    }
  }, [uiMode]);

  return (
    <div className="animate-fadeup h-full flex flex-col">
      {/* ── Compact header ── */}
      <div className="td-header flex-shrink-0">
        <div className="td-header-left">
          <h2 className="td-title">{task.title}</h2>
          <div className="td-badges">
            <span className={tierClass(effectiveTier)}>{effectiveTier}</span>
            <span className={statusClass(task.status)}>{task.status}</span>
            {uiMode === "full" && detail?.task_type && (
              <span className="td-type-badge">{detail.task_type}</span>
            )}
            {uiMode === "full" && detail?.complexity && (
              <span
                className={`td-type-badge ${
                  detail.complexity === "critical"
                    ? "td-complexity-critical"
                    : detail.complexity === "high"
                      ? "td-complexity-high"
                      : detail.complexity === "medium"
                        ? "td-complexity-medium"
                        : "td-complexity-low"
                }`}
              >
                {detail.complexity}
              </span>
            )}
            {detail?.confidence_score !== undefined &&
              uiMode === "full" &&
              detail.status !== "running" &&
              detail.status !== "pending" && (
                <span
                  className={`td-confidence-badge ${
                    detail.confidence_score >= 80
                      ? "confidence-high"
                      : detail.confidence_score >= 60
                        ? "confidence-medium"
                        : "confidence-low"
                  }`}
                >
                  <span className="confidence-icon">
                    {detail.confidence_score >= 80
                      ? "🛡"
                      : detail.confidence_score >= 60
                        ? "⚠"
                        : "❌"}
                  </span>
                  {detail.confidence_score.toFixed(0)}% Confidence
                </span>
              )}
            {uiMode === "full" && (
              <span className="td-updated">{task.updatedAt}</span>
            )}
            {isApproval && (
              <span className="td-approval-chip">✋ Awaiting approval</span>
            )}
            {gatesFailedSummary > 0 && (
              <span className="td-gate-fail-chip">
                ⚡ {gatesFailedSummary} gate
                {gatesFailedSummary !== 1 ? "s" : ""} failed
              </span>
            )}
            {budgetApprovalPending && (
              <span className="td-approval-chip">✋ Token extension pending</span>
            )}
            {hasAdvancedMeta && (
              <button
                type="button"
                className="td-meta-toggle"
                onClick={() => setShowAdvancedMeta((v) => !v)}
              >
                {showAdvancedMeta ? "Less details" : "More details"}
              </button>
            )}
            {showAdvancedMeta && (
              <>
                {tierMismatch && (
                  <span className="td-type-badge">
                    requested: {requestedTier}
                  </span>
                )}
                {replanCount > 0 && (
                  <span className="td-replan-chip">
                    ↺ {replanCount} replan{replanCount !== 1 ? "s" : ""}
                  </span>
                )}
                {(consultCount > 0 || debateCount > 0) && (
                  <span className="td-type-badge">
                    consult {consultCount} · debate {debateCount}
                  </span>
                )}
                {(cacheSavedTokens > 0 || cacheSavedCostUsd > 0) && (
                  <span className="td-type-badge">
                    cache saved {cacheSavedTokens.toLocaleString()} tok
                    {cacheSavedCostUsd > 0
                      ? ` · $${cacheSavedCostUsd.toFixed(4)}`
                      : ""}
                  </span>
                )}
                {(budgetAutoCompactions > 0 || budgetSoftExtensionsUsed > 0) && (
                  <span className="td-type-badge">
                    budget runtime: compaction {budgetAutoCompactions} · soft extension{" "}
                    {budgetSoftExtensionsUsed}
                  </span>
                )}
                {budgetApprovalRequested > 0 && (
                  <span className="td-type-badge">
                    token approvals: {budgetApprovalGranted}/{budgetApprovalRequested} granted
                  </span>
                )}
                {budgetAutoApprovedExtensions > 0 && (
                  <span className="td-type-badge">
                    auto-approved extensions: {budgetAutoApprovedExtensions}
                  </span>
                )}
                {gateRemediationPending && remediationRoleName && (
                  <span className="td-gate-fail-chip">
                    remediating: {remediationRoleName}
                    {remediationFailedGates > 0 ? ` (${remediationFailedGates} failed gate${remediationFailedGates !== 1 ? "s" : ""})` : ""}
                  </span>
                )}
                {isActive && nextRole && (
                  <span className="td-type-badge">
                    next: {canonicalAgentLabel(nextRole)}
                  </span>
                )}
                {targetMode && (
                  <span className="td-type-badge">target: {targetMode}</span>
                )}
                {summaryMissing && (
                  <span className="td-gate-fail-chip">
                    bridge summary missing
                  </span>
                )}
              </>
            )}
          </div>
        </div>
        <div className="td-header-right">
          <div className="td-view-toggle">
            <button
              type="button"
              className={`td-view-btn ${uiMode === "focus" ? "active" : ""}`}
              onClick={() => setUiMode("focus")}
              title="Focus mode"
            >
              Focus
            </button>
            <button
              type="button"
              className={`td-view-btn ${uiMode === "full" ? "active" : ""}`}
              onClick={() => setUiMode("full")}
              title="Full mode"
            >
              Full
            </button>
          </div>
          {/* View toggle: Map ↔ Timeline ↔ Logs */}
          {hasSteps && uiMode === "full" && (
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
              <button
                type="button"
                className={`td-view-btn ${viewMode === "logs" ? "active" : ""}`}
                onClick={() => setViewMode("logs")}
                title="Agent Logs"
              >
                ▤ Logs
              </button>
            </div>
          )}
          {projectPath && onOpenInEditor && (
            <OpenInEditorBtn
              projectPath={projectPath}
              onOpen={onOpenInEditor}
            />
          )}
          {uiMode === "full" && (
            <button
              type="button"
              className="ghost-btn text-xs py-1.5 px-3"
              onClick={() => setShowInsights((v) => !v)}
            >
              {showInsights ? "Hide insights" : "Show insights"}
            </button>
          )}
          {isActive && (
            <button
              type="button"
              className="warn-btn text-xs py-1.5 px-3"
              onClick={() =>
                onAction(`/v1/tasks/${task.id}/abort`, {
                  reason: "Aborted by user",
                })
              }
            >
              Abort
            </button>
          )}
          {canResume && (
            <button
              type="button"
              className="ghost-btn text-xs py-1.5 px-3"
              onClick={() =>
                onAction(`/v1/tasks/${task.id}/resume`, { resume_now: true })
              }
            >
              Resume
            </button>
          )}
          {actionMsg && (
            <span className="text-[10px] text-[var(--ui-text-muted)]">
              {actionMsg}
            </span>
          )}
        </div>
      </div>
      {hasSteps && (
        <ValueStrip
          totalTokens={missionTokens}
          totalCostUsd={missionCost}
          elapsedMs={runElapsedMs}
          baselineTokens={baselineTokens}
          consultCount={consultCount}
          debateCount={debateCount}
          cacheSavedTokens={cacheSavedTokens}
          cacheSavedCostUsd={cacheSavedCostUsd}
          cacheHitRate={cacheHitRate}
        />
      )}

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

      {/* ── First-glance control summary ── */}
      {hasSteps && (
        <ControlSummaryBar
          nowLabel={nowLabel}
          healthLabel={healthLabel}
          healthTone={healthTone}
          actionLabel={actionLabel}
        />
      )}
      {(detail?.required_approval_actions?.length ?? 0) > 0 && (
        <div
          className="mt-3 rounded-2xl border px-4 py-3"
          style={{
            borderColor: "rgba(248,113,113,0.25)",
            background: "rgba(127,29,29,0.14)",
          }}
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[var(--ui-text-muted)]">
                Approval Required
              </div>
              <div className="mt-1 text-sm font-medium text-[var(--ui-text-primary)]">
                {String(
                  detail?.required_approval_actions?.[0]?.summary ||
                  detail?.required_approval_actions?.[0]?.reason ||
                  "A risky runtime action requires operator approval.",
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="ghost-btn text-xs py-1.5 px-3"
                onClick={() =>
                  onAction(`/v1/tasks/${task.id}/deny`, {
                    reason: "Rejected by operator",
                  })
                }
              >
                Reject
              </button>
              <button
                type="button"
                className="ghost-btn text-xs py-1.5 px-3"
                onClick={() =>
                  onAction(`/v1/tasks/${task.id}/approve`, {
                    action: "approve",
                    resume_now: true,
                  })
                }
              >
                Approve
              </button>
            </div>
          </div>
        </div>
      )}
      {/* ── Secondary analytics (collapsed by default via "Show insights") ── */}
      {showInsights && (
        <>
          {latestDebate && (
            <div
              className="mt-3 rounded-2xl border px-4 py-3"
              style={{
                borderColor: "rgba(96,165,250,0.22)",
                background: "rgba(15,23,42,0.34)",
              }}
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[var(--ui-text-muted)]">
                    Debate Decision
                  </div>
                  <div className="mt-1 text-sm font-medium text-[var(--ui-text-primary)]">
                    {String(
                      latestDebateRecord?.selected_next_owner
                        ? `Next owner: ${canonicalAgentLabel(
                            String(latestDebateRecord.selected_next_owner),
                          )}`
                        : latestDebateRecord?.summary ||
                          latestDebateRecord?.action_delta ||
                          "Adjudication recorded.",
                    )}
                  </div>
                </div>
                <div className="text-xs text-[var(--ui-text-secondary)]">
                  {Array.isArray(latestDebateRecord?.feedback_sources)
                    ? `${latestDebateRecord.feedback_sources.length} feedback source${latestDebateRecord.feedback_sources.length !== 1 ? "s" : ""}`
                    : "debate resolved"}
                </div>
              </div>
            </div>
          )}
          {tunedRoleCount > 0 && (
            <div
              className="mt-3 rounded-2xl border px-4 py-3"
              style={{
                borderColor: "rgba(74,222,128,0.18)",
                background: "rgba(3,20,12,0.32)",
              }}
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[var(--ui-text-muted)]">
                    Role Learning
                  </div>
                  <div className="mt-1 text-sm font-medium text-[var(--ui-text-primary)]">
                    {tunedRoleCount} role{tunedRoleCount !== 1 ? "s" : ""} tuned in this run
                    {promotedRoleCount > 0 ? ` · ${promotedRoleCount} with promoted memory` : ""}
                  </div>
                </div>
                <div className="text-xs text-[var(--ui-text-secondary)]">
                  policy tuning is active
                </div>
              </div>
            </div>
          )}
          {hasSteps && (
            <QualitySummaryBar steps={detail!.steps} detail={detail} />
          )}
        </>
      )}
      {showInsights && mission && <MissionControl mission={mission} />}
      {uiMode === "full" && (workspaceRoot || targetRoot || targetMode) && (
        <div
          className="mt-3 rounded-2xl border px-4 py-3"
          style={{
            borderColor: "rgba(96,165,250,0.16)",
            background: "rgba(15,23,42,0.28)",
          }}
        >
          <div className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[var(--ui-text-muted)]">
            Execution Target
          </div>
          <div className="mt-2 grid gap-2 text-sm text-[var(--ui-text-primary)] md:grid-cols-3">
            <div>
              <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--ui-text-muted)]">
                Workspace Root
              </div>
              <div className="mt-1 break-all">{workspaceRoot ?? "—"}</div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--ui-text-muted)]">
                Target Root
              </div>
              <div className="mt-1 break-all">{targetRoot ?? "—"}</div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--ui-text-muted)]">
                Target Mode
              </div>
              <div className="mt-1">{targetMode ?? "—"}</div>
            </div>
          </div>
        </div>
      )}

      {/* ── Split layout: map or timeline (left) + agent detail (right) ── */}
      <div
        className={`td-map-layout flex-1 min-h-0 ${leftOpen ? "" : "td-map-layout--collapsed"}`}
      >
        {/* Panel collapse/expand toggle — sits on the divider */}
        {hasSteps && (
          <button
            type="button"
            className="td-panel-toggle"
            onClick={() => setLeftOpen((v) => !v)}
            title={leftOpen ? "Collapse panel" : "Expand panel"}
            aria-label={leftOpen ? "Collapse left panel" : "Expand left panel"}
          >
            {leftOpen ? "‹" : "›"}
          </button>
        )}

        {/* Left: Neural Map | Timeline | Logs */}
        {viewMode === "map" ? (
          <div className={`td-map-left ${leftOpen ? "" : "td-panel-hidden"}`}>
            {isProcessing ? (
              <div className="td-map-processing">
                <ProcessingState
                  status={task.status}
                  taskType={detail?.task_type || mission?.task_type}
                  latestDecision={
                    mission?.decision_trace?.slice(-1)[0]?.summary
                  }
                  startedAt={detail?.started_at ?? detail?.created_at ?? null}
                  masterThinkingMs={masterThinkingMs}
                  masterWaitingMs={masterWaitingMs}
                />
              </div>
            ) : (
              <NeuralCalibrationMap
                steps={detail?.steps ?? []}
                taskStatus={task.status}
                taskType={detail?.task_type}
                collab={collab}
                plannedRoles={detail?.planned_roles ?? []}
                executionDag={detail?.execution_dag}
                totalFiles={totalFiles}
                totalCost={mapTotalCost}
                expectedAgents={expectedAgents}
                nextExpectedRole={nextRole ? canonicalAgentLabel(nextRole) : null}
                replanCount={replanCount}
                gatesTotal={gatesTotalSummary}
                gatesFailed={gatesFailedSummary}
                selectedAgent={selectedAgent}
                onSelectAgent={setSelectedAgent}
              />
            )}
          </div>
        ) : viewMode === "timeline" ? (
          <div
            className={`td-timeline-left ${leftOpen ? "" : "td-panel-hidden"}`}
          >
            {isProcessing ? (
              <div className="p-4">
                <ProcessingState
                  status={task.status}
                  taskType={detail?.task_type || mission?.task_type}
                  latestDecision={
                    mission?.decision_trace?.slice(-1)[0]?.summary
                  }
                  startedAt={detail?.started_at ?? detail?.created_at ?? null}
                  masterThinkingMs={masterThinkingMs}
                  masterWaitingMs={masterWaitingMs}
                />
              </div>
            ) : (
              <AgentTimeline
                steps={detail.steps}
                taskType={detail.task_type ?? "engineering"}
                plannedCount={expectedAgents}
                collab={collab}
                gov={gov}
                costs={costs}
                onOpenFiles={openFilesDrawer}
              />
            )}
          </div>
        ) : (
          /* Logs view */
          <div className={`td-logs-left ${leftOpen ? "" : "td-panel-hidden"}`}>
            <InlineLogViewer
              steps={detail?.steps ?? []}
              taskStatus={task.status}
            />
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
            activeFixPacket={detail?.active_fix_packet ?? null}
            downstreamLockReason={detail?.downstream_lock_reason ?? null}
            supervisoryDecisions={detail?.supervisory_decisions ?? []}
            spawnHistory={detail?.spawn_history ?? []}
            debateHistory={detail?.debate_history ?? []}
            riskActionQueue={detail?.risk_action_queue ?? []}
            requiredApprovalActions={detail?.required_approval_actions ?? []}
            agentLearningUpdates={detail?.agent_learning_updates ?? {}}
            behaviorChangeAudit={detail?.behavior_change_audit ?? []}
            roleLearningMetrics={detail?.role_learning_metrics ?? {}}
            totalFiles={totalFiles}
            expectedAgents={expectedAgents}
            nextExpectedRole={nextRole ? canonicalAgentLabel(nextRole) : null}
            nextExpectedReason={
              gateRemediationPending
                ? "awaiting gate remediation"
                : nextExpectedReason
            }
            replanCount={replanCount}
            onOpenFiles={openFilesDrawer}
            isApproval={isApproval}
            onApprove={() =>
              onAction(`/v1/tasks/${task.id}/approve`, {
                action: "approve",
                resume_now: true,
              })
            }
            onReject={() =>
              onAction(`/v1/tasks/${task.id}/deny`, {
                reason: "Rejected by operator",
              })
            }
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
