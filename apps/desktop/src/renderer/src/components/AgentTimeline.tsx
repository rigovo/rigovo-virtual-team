/* ------------------------------------------------------------------ */
/*  AgentTimeline — multi-agent debate / conversation UI               */
/*  Shows agents talking, debating, handing off like a real team       */
/* ------------------------------------------------------------------ */
import { useEffect, useRef } from "react";
import type { TaskStep } from "../types";
import ResponseRenderer from "./ResponseRenderer";

/* ---- Role definitions ---- */
const ROLES: Record<string, { icon: string; label: string; color: string; bg: string; ring: string; accent: string }> = {
  planner:  { icon: "\uD83E\uDDE0", label: "Planner",  color: "text-violet-400",  bg: "bg-violet-500/15", ring: "ring-violet-500/30",  accent: "#8b5cf6" },
  lead:     { icon: "\uD83C\uDFAF", label: "Lead",     color: "text-purple-400",  bg: "bg-purple-500/15", ring: "ring-purple-500/30",  accent: "#a855f7" },
  coder:    { icon: "\uD83D\uDCBB", label: "Coder",    color: "text-sky-400",     bg: "bg-sky-500/15",    ring: "ring-sky-500/30",     accent: "#0ea5e9" },
  reviewer: { icon: "\uD83D\uDD0D", label: "Reviewer", color: "text-emerald-400", bg: "bg-emerald-500/15",ring: "ring-emerald-500/30", accent: "#10b981" },
  qa:       { icon: "\uD83E\uDDEA", label: "QA",       color: "text-amber-400",   bg: "bg-amber-500/15",  ring: "ring-amber-500/30",   accent: "#f59e0b" },
  security: { icon: "\uD83D\uDD12", label: "Security", color: "text-rose-400",    bg: "bg-rose-500/15",   ring: "ring-rose-500/30",    accent: "#f43f5e" },
  devops:   { icon: "\u2699\uFE0F", label: "DevOps",   color: "text-indigo-400",  bg: "bg-indigo-500/15", ring: "ring-indigo-500/30",  accent: "#6366f1" },
  sre:      { icon: "\uD83D\uDCCA", label: "SRE",      color: "text-cyan-400",    bg: "bg-cyan-500/15",   ring: "ring-cyan-500/30",    accent: "#06b6d4" },
  docs:     { icon: "\uD83D\uDCDD", label: "Docs",     color: "text-stone-400",   bg: "bg-stone-500/15",  ring: "ring-stone-500/30",   accent: "#a8a29e" },
};

const getRole = (agent: string) =>
  ROLES[agent.toLowerCase()] ?? { icon: "\uD83E\uDD16", label: agent, color: "text-slate-400", bg: "bg-slate-500/15", ring: "ring-slate-500/30", accent: "#94a3b8" };

/* Parallel agent roles */
const PARALLEL_ROLES = new Set(["reviewer", "qa", "security", "docs"]);

/* ================================================================== */
/*  Sub-components                                                     */
/* ================================================================== */

/* Typing indicator — 3 bouncing dots */
function TypingDots() {
  return (
    <div className="flex items-center gap-1">
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-1" />
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-2" />
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-current animate-typing-3" />
    </div>
  );
}

/* Agent identity card — shows who this agent is */
function AgentAvatar({ agent, status }: { agent: string; status: string }) {
  const role = getRole(agent);
  const isRunning = status === "running";
  return (
    <div className="flex items-center gap-2.5">
      <div className={`relative flex h-10 w-10 items-center justify-center rounded-2xl ${role.bg} ring-1 ${role.ring} text-lg transition-all ${isRunning ? "animate-pulse-glow" : ""}`}>
        {role.icon}
        {/* Status dot */}
        <span className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-base ${
          status === "complete" ? "bg-emerald-500" :
          status === "running" ? "bg-sky-500 animate-pulse" :
          status === "failed" ? "bg-rose-500" :
          "bg-slate-600"
        }`} />
      </div>
      <div>
        <span className={`text-sm font-semibold ${role.color}`}>{role.label}</span>
        <span className={`ml-2 text-[10px] font-medium capitalize ${
          status === "complete" ? "text-emerald-400" :
          status === "running" ? "text-sky-400" :
          status === "failed" ? "text-rose-400" :
          "text-slate-600"
        }`}>{status}</span>
      </div>
    </div>
  );
}

/* Chat-style message bubble with speech tail */
function ChatBubble({ step, index }: { step: TaskStep; index: number }) {
  const role = getRole(step.agent);
  const isRunning = step.status === "running";
  const isFailed = step.status === "failed";
  const isDone = step.status === "complete";

  return (
    <div className="animate-fadeup" style={{ animationDelay: `${index * 100}ms` }}>
      {/* Agent identity */}
      <div className="flex items-center justify-between mb-2">
        <AgentAvatar agent={step.agent} status={step.status} />
        {step.started_at && (
          <span className="text-[10px] text-slate-600 tabular-nums">
            {new Date(step.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          </span>
        )}
      </div>

      {/* Speech bubble */}
      <div className="ml-[52px] relative">
        {/* Bubble tail */}
        <div className="absolute -left-2 top-3 w-0 h-0 border-t-[6px] border-t-transparent border-b-[6px] border-b-transparent border-r-[8px]"
          style={{ borderRightColor: isRunning ? `${role.accent}15` : "rgba(30,41,59,0.6)" }} />

        {/* Main bubble */}
        <div
          className={`rounded-2xl border p-4 transition-all ${
            isRunning ? "animate-border-pulse" : ""
          } ${isDone ? "border-emerald-500/10" : isFailed ? "border-rose-500/15 bg-rose-500/5" : ""}`}
          style={{
            background: isRunning ? `${role.accent}08` : "rgba(30,41,59,0.6)",
            borderColor: isRunning ? `${role.accent}20` : "rgba(255,255,255,0.05)",
          }}
        >
          {/* Running — thinking animation */}
          {isRunning && !step.output && (
            <div className="flex items-center gap-3">
              <div className={role.color}>
                <TypingDots />
              </div>
              <span className="text-xs text-slate-500 italic">Thinking...</span>
            </div>
          )}

          {/* Running with partial output */}
          {isRunning && step.output && (
            <div>
              <ResponseRenderer output={step.output} maxHeightClass="max-h-64" />
              <div className={`mt-2 flex items-center gap-2 ${role.color}`}>
                <TypingDots />
                <span className="text-[10px] italic opacity-60">Still working...</span>
              </div>
            </div>
          )}

          {/* Complete / failed output */}
          {!isRunning && step.output && (
            <ResponseRenderer output={step.output} maxHeightClass="max-h-72" />
          )}

          {/* Completed/failed with no textual output */}
          {!isRunning && !step.output && (
            <p className="text-[12px] text-slate-500 italic">
              {isFailed ? "Execution failed before producing output." : "Step finished. No textual output."}
            </p>
          )}

          {/* Files changed — code-card style */}
          {step.files_changed.length > 0 && (
            <div className="mt-3 rounded-xl border border-white/5 bg-base/40 overflow-hidden">
              <div className="px-3 py-1.5 border-b border-white/5 flex items-center gap-1.5">
                <span className="text-[10px] text-sky-400">{"\uD83D\uDCC1"}</span>
                <span className="meta-label">Files changed ({step.files_changed.length})</span>
              </div>
              <div className="px-3 py-2 space-y-0.5">
                {step.files_changed.map((f) => (
                  <p key={f} className="text-xs font-mono text-slate-400 flex items-center gap-1.5 hover:text-slate-300 transition-colors">
                    <span className="text-emerald-500/60 text-[10px]">+</span>
                    {f}
                  </p>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Rigour gate checkpoint — inline after bubble */}
        {step.gate_results.length > 0 && (
          <GateCheckpoint gates={step.gate_results} />
        )}
      </div>
    </div>
  );
}

/* Rigour Quality Gate bar */
function GateCheckpoint({ gates }: { gates: TaskStep["gate_results"] }) {
  const allPassed = gates.every((g) => g.passed);
  return (
    <div className={`mt-2 rounded-xl border px-4 py-2.5 animate-fadeup flex items-center gap-3 ${
      allPassed
        ? "border-emerald-500/20 bg-emerald-500/5"
        : "border-rose-500/20 bg-rose-500/5"
    }`}>
      <div className="flex items-center gap-2">
        <div className={`flex h-6 w-6 items-center justify-center rounded-lg text-xs ${
          allPassed ? "bg-emerald-500/20 text-emerald-400" : "bg-rose-500/20 text-rose-400"
        }`}>
          {allPassed ? "\u2713" : "\u2717"}
        </div>
        <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Rigour</span>
      </div>
      <div className="h-3 w-px bg-white/10" />
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {gates.map((g, i) => (
          <span key={i} className={`flex items-center gap-1 text-[11px] ${
            g.passed ? "text-emerald-400" : g.severity === "error" ? "text-rose-400" : "text-amber-400"
          }`}>
            <span className="text-[9px]">{g.passed ? "\u25CF" : "\u25CF"}</span>
            <span className="font-medium">{g.gate}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

/* Handoff / consultation connector between agents */
function HandoffConnector({ from, to, type }: { from: string; to: string; type: "handoff" | "consult" }) {
  const fromRole = getRole(from);
  const toRole = getRole(to);
  return (
    <div className="ml-[52px] flex items-center gap-3 py-2 animate-slide-in">
      <div className="h-px flex-1 bg-gradient-to-r from-transparent via-white/8 to-transparent" />
      <div className="flex items-center gap-1.5 rounded-full border border-white/5 bg-surface/80 px-3 py-1">
        <span className={`text-[10px] font-medium ${fromRole.color}`}>{fromRole.label}</span>
        <span className="text-slate-600 text-[10px]">{type === "consult" ? "\u21C4" : "\u2192"}</span>
        <span className={`text-[10px] font-medium ${toRole.color}`}>{toRole.label}</span>
      </div>
      <div className="h-px flex-1 bg-gradient-to-r from-transparent via-white/8 to-transparent" />
    </div>
  );
}

/* Parallel agents — side by side grid */
function ParallelGroup({ steps, startIndex }: { steps: TaskStep[]; startIndex: number }) {
  return (
    <div className="animate-fadeup" style={{ animationDelay: `${startIndex * 100}ms` }}>
      {/* Parallel label */}
      <div className="ml-[52px] flex items-center gap-2 mb-3">
        <div className="h-px flex-1 bg-gradient-to-r from-brand/20 via-brand/10 to-transparent" />
        <span className="text-[10px] font-semibold text-brand-light/60 uppercase tracking-wider flex items-center gap-1.5">
          <span className="inline-block h-1 w-1 rounded-full bg-brand-light/40" />
          Running in parallel
          <span className="inline-block h-1 w-1 rounded-full bg-brand-light/40" />
        </span>
        <div className="h-px flex-1 bg-gradient-to-r from-transparent via-brand/10 to-brand/20" />
      </div>

      {/* Grid of parallel agents */}
      <div className="grid grid-cols-2 gap-3">
        {steps.map((step, i) => (
          <ChatBubble key={startIndex + i} step={step} index={startIndex + i} />
        ))}
      </div>
    </div>
  );
}

/* ================================================================== */
/*  Orchestrator kickoff message                                       */
/* ================================================================== */
function OrchestratorMessage({ taskType, stepCount }: { taskType: string; stepCount: number }) {
  return (
    <div className="animate-fadeup mb-4">
      <div className="flex items-center gap-2.5 mb-2">
        <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-brand/15 ring-1 ring-brand/30 text-lg">
          {"\uD83C\uDFAF"}
        </div>
        <div>
          <span className="text-sm font-semibold text-brand-light">Orchestrator</span>
          <span className="ml-2 text-[10px] text-slate-600">Master Brain</span>
        </div>
      </div>
      <div className="ml-[52px] rounded-2xl border border-brand/10 bg-brand/5 p-4">
        <p className="text-[13px] text-slate-300 leading-relaxed">
          Task classified as <span className="font-semibold text-brand-light">{taskType || "engineering task"}</span>.
          Assembling a pipeline of <span className="font-semibold text-slate-200">{stepCount} agent{stepCount !== 1 ? "s" : ""}</span> to handle this.
          Each agent will contribute their expertise and pass results to the next.
        </p>
      </div>
    </div>
  );
}

/* ================================================================== */
/*  AgentTimeline — main export                                        */
/* ================================================================== */
interface AgentTimelineProps {
  steps: TaskStep[];
  taskType: string;
}

export default function AgentTimeline({ steps, taskType }: AgentTimelineProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const visibleSteps = steps.filter((s) => s.status !== "pending" || Boolean(s.output) || Boolean(s.started_at) || Boolean(s.completed_at));
  const queuedAgents = steps.filter((s) => !visibleSteps.includes(s));

  /* Auto-scroll to bottom when new steps arrive or status changes */
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [visibleSteps.length, visibleSteps[visibleSteps.length - 1]?.status]);

  if (steps.length === 0) return null;

  /* Group parallel steps together */
  const groups: Array<{ type: "single" | "parallel"; steps: TaskStep[]; startIndex: number }> = [];
  let i = 0;
  while (i < visibleSteps.length) {
    if (PARALLEL_ROLES.has(visibleSteps[i].agent.toLowerCase())) {
      // Collect consecutive parallel-eligible agents
      const parallelSteps: TaskStep[] = [];
      const start = i;
      while (i < visibleSteps.length && PARALLEL_ROLES.has(visibleSteps[i].agent.toLowerCase())) {
        parallelSteps.push(visibleSteps[i]);
        i++;
      }
      if (parallelSteps.length > 1) {
        groups.push({ type: "parallel", steps: parallelSteps, startIndex: start });
      } else {
        groups.push({ type: "single", steps: parallelSteps, startIndex: start });
      }
    } else {
      groups.push({ type: "single", steps: [visibleSteps[i]], startIndex: i });
      i++;
    }
  }

  return (
    <div className="space-y-4">
      {/* Orchestrator */}
      <OrchestratorMessage taskType={taskType} stepCount={steps.length} />

      {/* Agent conversation */}
      {groups.map((group, gi) => (
        <div key={gi}>
          {/* Handoff connector */}
          {gi > 0 && (
            <HandoffConnector
              from={groups[gi - 1].steps[groups[gi - 1].steps.length - 1].agent}
              to={group.steps[0].agent}
              type="handoff"
            />
          )}

          {group.type === "parallel" ? (
            <ParallelGroup steps={group.steps} startIndex={group.startIndex} />
          ) : (
            <ChatBubble step={group.steps[0]} index={group.startIndex} />
          )}
        </div>
      ))}

      {queuedAgents.length > 0 && (
        <div className="ml-[52px] rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Queued agents</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {queuedAgents.map((s, idx) => (
              <span key={`${s.agent}-${idx}`} className={`rounded-md bg-white/5 px-2 py-0.5 text-[10px] ${getRole(s.agent).color}`}>
                {getRole(s.agent).label}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Scroll anchor */}
      <div ref={bottomRef} />
    </div>
  );
}
