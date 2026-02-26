/* ------------------------------------------------------------------ */
/*  ActivityLog — system / think log panel                             */
/*  Shows timestamped pipeline events like a live system console       */
/* ------------------------------------------------------------------ */
import type { TaskStep, TaskDetail } from "../types";

/* ---- Role colors ---- */
const ROLE_COLORS: Record<string, string> = {
  planner: "text-violet-400", lead: "text-purple-400", coder: "text-sky-400",
  reviewer: "text-emerald-400", qa: "text-amber-400", security: "text-rose-400",
  devops: "text-indigo-400", sre: "text-cyan-400", docs: "text-stone-400",
};
const roleColor = (agent: string) => ROLE_COLORS[agent.toLowerCase()] ?? "text-slate-400";

/* Build log entries from task detail */
interface LogEntry {
  time: string;
  agent: string;
  event: string;
  type: "start" | "complete" | "fail" | "gate" | "system";
}

function buildLog(detail: TaskDetail): LogEntry[] {
  const entries: LogEntry[] = [];

  // Task created
  if (detail.created_at) {
    entries.push({ time: detail.created_at, agent: "system", event: `Task created — ${detail.task_type || "classifying"}`, type: "system" });
  }
  if (detail.started_at) {
    entries.push({ time: detail.started_at, agent: "orchestrator", event: `Pipeline started with ${detail.steps.length} agents`, type: "system" });
  }

  // Agent events
  for (const step of detail.steps) {
    if (step.started_at) {
      entries.push({ time: step.started_at, agent: step.agent, event: `Started working`, type: "start" });
    }
    if (step.gate_results.length > 0 && step.completed_at) {
      const passed = step.gate_results.every((g) => g.passed);
      entries.push({
        time: step.completed_at,
        agent: "rigour",
        event: `Quality gate ${passed ? "PASSED" : "FAILED"} for ${step.agent}`,
        type: passed ? "gate" : "fail"
      });
    }
    if (step.completed_at && step.status === "complete") {
      entries.push({ time: step.completed_at, agent: step.agent, event: `Completed${step.files_changed.length ? ` — ${step.files_changed.length} files` : ""}`, type: "complete" });
    }
    if (step.completed_at && step.status === "failed") {
      entries.push({ time: step.completed_at, agent: step.agent, event: "Failed", type: "fail" });
    }
  }

  // Sort by time
  entries.sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime());
  return entries;
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "--:--:--";
  }
}

/* ================================================================== */
/*  ActivityLog — main export                                          */
/* ================================================================== */
interface ActivityLogProps {
  detail: TaskDetail;
}

export default function ActivityLog({ detail }: ActivityLogProps) {
  const entries = buildLog(detail);

  if (entries.length === 0) return null;

  return (
    <div className="rounded-2xl border border-white/5 bg-surface/50 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-2.5 border-b border-white/5 flex items-center gap-2">
        <span className="text-xs">{"\uD83D\uDCCB"}</span>
        <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Activity Log</span>
        <span className="ml-auto text-[10px] text-slate-600">{entries.length} events</span>
      </div>

      {/* Log entries */}
      <div className="max-h-64 overflow-y-auto">
        {entries.map((entry, i) => (
          <div
            key={i}
            className="flex items-start gap-3 px-4 py-2 border-b border-white/[0.02] hover:bg-white/[0.02] transition-colors animate-fadeup"
            style={{ animationDelay: `${i * 40}ms` }}
          >
            {/* Time */}
            <span className="text-[10px] font-mono text-slate-600 tabular-nums w-16 flex-shrink-0 pt-0.5">
              {formatTime(entry.time)}
            </span>

            {/* Status dot */}
            <span className={`mt-1.5 h-1.5 w-1.5 rounded-full flex-shrink-0 ${
              entry.type === "complete" ? "bg-emerald-500" :
              entry.type === "start" ? "bg-sky-500" :
              entry.type === "fail" ? "bg-rose-500" :
              entry.type === "gate" ? "bg-brand-light" :
              "bg-slate-600"
            }`} />

            {/* Agent + event */}
            <div className="flex-1 min-w-0">
              <span className={`text-[11px] font-semibold ${
                entry.agent === "system" ? "text-slate-500" :
                entry.agent === "orchestrator" ? "text-brand-light" :
                entry.agent === "rigour" ? "text-emerald-400" :
                roleColor(entry.agent)
              }`}>
                {entry.agent === "system" ? "System" :
                 entry.agent === "orchestrator" ? "Orchestrator" :
                 entry.agent === "rigour" ? "Rigour" :
                 entry.agent.charAt(0).toUpperCase() + entry.agent.slice(1)}
              </span>
              <span className="text-[11px] text-slate-500 ml-1.5">{entry.event}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---- Agent status strip (compact view of all agents) ---- */
export function AgentStatusStrip({ steps }: { steps: TaskStep[] }) {
  if (steps.length === 0) return null;

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {steps.map((step, i) => {
        const color = roleColor(step.agent);
        return (
          <div
            key={i}
            className={`flex items-center gap-1 rounded-lg border border-white/5 bg-surface/60 px-2 py-1 ${
              step.status === "running" ? "animate-border-pulse" : ""
            }`}
            title={`${step.agent}: ${step.status}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${
              step.status === "complete" ? "bg-emerald-500" :
              step.status === "running" ? "bg-sky-500 animate-pulse" :
              step.status === "failed" ? "bg-rose-500" :
              "bg-slate-600"
            }`} />
            <span className={`text-[10px] font-medium ${color}`}>
              {step.agent.charAt(0).toUpperCase() + step.agent.slice(1)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
