/* ------------------------------------------------------------------ */
/*  ActivityLog — system / think log panel                             */
/*  Shows timestamped pipeline events like a live system console       */
/* ------------------------------------------------------------------ */
import type { TaskStep, TaskDetail } from "../types";

/* ---- Role colors ---- */
const ROLE_COLORS: Record<string, string> = {
  planner: "text-violet-600", lead: "text-purple-600", coder: "text-sky-600",
  reviewer: "text-emerald-600", qa: "text-amber-600", security: "text-rose-600",
  devops: "text-indigo-600", sre: "text-cyan-600", docs: "text-stone-500",
};
const roleColor = (agent: string) => ROLE_COLORS[agent.toLowerCase()] ?? "text-[var(--ui-text-muted)]";

/* Build log entries from task detail */
interface LogEntry {
  time: string;
  agent: string;
  event: string;
  type: "start" | "complete" | "fail" | "gate" | "system";
}

function buildLog(detail: TaskDetail): LogEntry[] {
  const entries: LogEntry[] = [];

  if (detail.created_at) {
    entries.push({ time: detail.created_at, agent: "system", event: `Task created — ${detail.task_type || "classifying"}`, type: "system" });
  }
  if (detail.started_at) {
    entries.push({ time: detail.started_at, agent: "orchestrator", event: `Pipeline started with ${detail.steps.length} agents`, type: "system" });
  }

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
    <div className="rounded-2xl border border-[var(--ui-border)] bg-white overflow-hidden">
      <div className="px-4 py-2.5 border-b border-[var(--ui-border)] flex items-center gap-2">
        <span className="text-xs">{"\uD83D\uDCCB"}</span>
        <span className="text-[11px] font-semibold text-[var(--ui-text-muted)] uppercase tracking-wider">Activity Log</span>
        <span className="ml-auto text-[10px] text-[var(--ui-text-subtle)]">{entries.length} events</span>
      </div>

      <div className="max-h-64 overflow-y-auto">
        {entries.map((entry, i) => (
          <div
            key={i}
            className="flex items-start gap-3 px-4 py-2 border-b border-[var(--ui-border)] hover:bg-[rgba(0,0,0,0.02)] transition-colors animate-fadeup"
            style={{ animationDelay: `${i * 40}ms` }}
          >
            <span className="text-[10px] font-mono text-[var(--ui-text-subtle)] tabular-nums w-16 flex-shrink-0 pt-0.5">
              {formatTime(entry.time)}
            </span>

            <span className={`mt-1.5 h-1.5 w-1.5 rounded-full flex-shrink-0 ${
              entry.type === "complete" ? "bg-emerald-500" :
              entry.type === "start" ? "bg-sky-500" :
              entry.type === "fail" ? "bg-rose-500" :
              entry.type === "gate" ? "bg-emerald-400" :
              "bg-[var(--ui-text-subtle)]"
            }`} />

            <div className="flex-1 min-w-0">
              <span className={`text-[11px] font-semibold ${
                entry.agent === "system" ? "text-[var(--ui-text-muted)]" :
                entry.agent === "orchestrator" ? "text-indigo-600" :
                entry.agent === "rigour" ? "text-emerald-600" :
                roleColor(entry.agent)
              }`}>
                {entry.agent === "system" ? "System" :
                 entry.agent === "orchestrator" ? "Orchestrator" :
                 entry.agent === "rigour" ? "Rigour" :
                 entry.agent.charAt(0).toUpperCase() + entry.agent.slice(1)}
              </span>
              <span className="text-[11px] text-[var(--ui-text-muted)] ml-1.5">{entry.event}</span>
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
            className={`flex items-center gap-1 rounded-lg border border-[var(--ui-border)] bg-[rgba(0,0,0,0.02)] px-2 py-1 ${
              step.status === "running" ? "animate-border-pulse" : ""
            }`}
            title={`${step.agent}: ${step.status}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${
              step.status === "complete" ? "bg-emerald-500" :
              step.status === "running" ? "bg-sky-500 animate-pulse" :
              step.status === "failed" ? "bg-rose-500" :
              "bg-[var(--ui-text-subtle)]"
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
