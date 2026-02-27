import { useEffect, useMemo, useRef } from "react";
import type { TaskStep } from "../types";
import ResponseRenderer from "./ResponseRenderer";

type NarrativeKind = "action" | "challenge";

type RoleMeta = {
  icon: string;
  label: string;
  color: string;
  surface: string;
  border: string;
};

const ROLES: Record<string, RoleMeta> = {
  planner:  { icon: "\uD83E\uDDE0", label: "Planner",  color: "text-violet-600", surface: "bg-violet-50",  border: "border-violet-200"  },
  lead:     { icon: "\uD83C\uDFAF", label: "Lead",     color: "text-purple-600", surface: "bg-purple-50",  border: "border-purple-200"  },
  coder:    { icon: "\uD83D\uDCBB", label: "Coder",    color: "text-sky-600",    surface: "bg-sky-50",     border: "border-sky-200"     },
  reviewer: { icon: "\uD83D\uDD0E", label: "Reviewer", color: "text-emerald-600",surface: "bg-emerald-50", border: "border-emerald-200"  },
  qa:       { icon: "\uD83E\uDDEA", label: "QA",       color: "text-amber-600",  surface: "bg-amber-50",   border: "border-amber-200"   },
  security: { icon: "\uD83D\uDD10", label: "Security", color: "text-rose-600",   surface: "bg-rose-50",    border: "border-rose-200"    },
  devops:   { icon: "\u2699\uFE0F", label: "DevOps",   color: "text-indigo-600", surface: "bg-indigo-50",  border: "border-indigo-200"  },
  sre:      { icon: "\uD83D\uDCC8", label: "SRE",      color: "text-cyan-600",   surface: "bg-cyan-50",    border: "border-cyan-200"    },
  docs:     { icon: "\uD83D\uDCDD", label: "Docs",     color: "text-stone-600",  surface: "bg-stone-50",   border: "border-stone-200"   },
};

const REVIEW_ROLES = new Set(["reviewer", "qa", "security"]);

function roleMeta(role: string): RoleMeta {
  return ROLES[role.toLowerCase()] ?? {
    icon: "\uD83E\uDD16",
    label: role || "Agent",
    color: "text-[var(--ui-text-secondary)]",
    surface: "bg-[rgba(0,0,0,0.02)]",
    border: "border-[var(--ui-border)]",
  };
}

function statusTone(status: TaskStep["status"]): string {
  if (status === "complete") return "text-emerald-600";
  if (status === "running")  return "text-sky-600";
  if (status === "failed")   return "text-rose-600";
  return "text-[var(--ui-text-muted)]";
}

function eventKind(step: TaskStep): NarrativeKind {
  if (step.status === "failed") return "challenge";
  if (step.gate_results.some((g) => !g.passed)) return "challenge";
  if (REVIEW_ROLES.has(step.agent.toLowerCase())) return "challenge";
  return "action";
}

function formatTs(value: string | number | null | undefined): string {
  if (!value) return "--:--";
  try {
    const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch { return "--:--"; }
}

/** Normalize any timestamp to unix-ms (0 if missing/invalid) */
function toMs(ts: string | number | null | undefined): number {
  if (!ts) return 0;
  if (typeof ts === "number") return ts < 1e10 ? ts * 1000 : ts; // seconds vs ms
  try { return new Date(ts).getTime(); } catch { return 0; }
}

/* ── Collab / Gov data types (mirror TaskDetail inline types) ── */
export interface CollabEvent {
  type: string;
  role?: string;
  from_role?: string;
  to_role?: string;
  message_id?: string;
  round?: number;
  reviewer_feedback?: string;
  kind?: string;
  operation?: string;
  blocked_reason?: string;
  created_at?: number | string;
}

export interface CollabMessage {
  id: string;
  type: string;
  from_role: string;
  to_role: string;
  content: string;
  status: string;
  created_at?: number;
}

export interface CollaborationData {
  events: CollabEvent[];
  messages: CollabMessage[];
  summary: {
    consult_requests: number;
    consult_completions: number;
    debate_rounds: number;
    integration_invoked: number;
    integration_blocked: number;
  };
}

export interface GovTimelineEvent {
  ts: string | null;
  category: string;
  decision: "allow" | "deny" | "pending" | "info";
  action: string;
  actor: string;
  summary: string;
  metadata: Record<string, unknown>;
  source: string;
}

export interface GovernanceData {
  timeline: GovTimelineEvent[];
  summary: { allow: number; deny: number; pending: number };
}

export interface CostData {
  total_tokens: number;
  total_cost_usd: number;
  per_agent: Record<string, { input_tokens: number; output_tokens: number; cost_usd: number; model: string }>;
}

/* ── Sub-components ── */

function KindBadge({ kind }: { kind: NarrativeKind }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${
      kind === "challenge"
        ? "bg-amber-50 text-amber-700 border border-amber-200"
        : "bg-sky-50 text-sky-700 border border-sky-200"
    }`}>
      {kind}
    </span>
  );
}

function DecisionCard({ from, to, first, index }: { from: string | null; to: string; first: boolean; index: number }) {
  const target = roleMeta(to);
  const source = from ? roleMeta(from) : null;
  return (
    <div className="narrative-decision animate-fadeup" style={{ animationDelay: `${index * 80}ms` }}>
      <span className="narrative-meta-label">Master Brain decision</span>
      <p className="mt-1 text-[12px] text-[var(--ui-text-secondary)]">
        {first ? (
          <>Routed objective to <span className={target.color}>{target.label}</span> as starting owner.</>
        ) : (
          <>Handoff from <span className={source?.color}>{source?.label}</span> to{" "}<span className={target.color}>{target.label}</span> with context and evidence.</>
        )}
      </p>
    </div>
  );
}

function CollabRow({ event, messages, index }: {
  event: CollabEvent;
  messages: CollabMessage[];
  index: number;
}) {
  const msgContent = event.message_id
    ? messages.find((m) => m.id === event.message_id)?.content
    : undefined;
  const ts = formatTs(event.created_at);

  let icon = "💬";
  let routeText = "";
  let bodyText = "";

  switch (event.type) {
    case "agent_consult_requested":
      icon = "💬";
      routeText = `${event.from_role || "agent"} → ${event.to_role || "agent"}`;
      bodyText = msgContent ? String(msgContent).slice(0, 200) : "Consultation requested";
      break;
    case "agent_consult_completed":
      icon = "↩️";
      routeText = `${event.to_role || "agent"} replied → ${event.from_role || "agent"}`;
      bodyText = msgContent ? String(msgContent).slice(0, 200) : "Reply sent";
      break;
    case "debate_round":
      icon = "🔄";
      routeText = `Debate round ${event.round ?? ""}`;
      bodyText = event.reviewer_feedback ? String(event.reviewer_feedback).slice(0, 220) : "";
      break;
    case "integration_invoked":
      icon = "🔗";
      routeText = `${event.role || "agent"} used ${event.kind || "integration"}:${event.operation || "op"}`;
      bodyText = "";
      break;
    case "integration_blocked":
      icon = "🚫";
      routeText = `${event.role || "agent"} blocked by policy`;
      bodyText = event.blocked_reason || "";
      break;
    default:
      icon = "↔️";
      routeText = event.type.replace(/_/g, " ");
  }

  return (
    <div className="feed-collab animate-fadeup" style={{ animationDelay: `${index * 40}ms` }}>
      <span className="text-[12px] flex-shrink-0 leading-none mt-0.5">{icon}</span>
      <div className="min-w-0 flex-1">
        <span className="feed-collab-route">{routeText}</span>
        {bodyText && <p className="feed-collab-content">{bodyText}</p>}
      </div>
      <span className="feed-collab-time">{ts}</span>
    </div>
  );
}

function GovRow({ event, index }: { event: GovTimelineEvent; index: number }) {
  const cls = event.decision === "allow" ? "allow"
    : event.decision === "deny" ? "deny"
    : event.decision === "pending" ? "pending"
    : "info";
  return (
    <div className="feed-gov-row animate-fadeup" style={{ animationDelay: `${index * 30}ms` }}>
      <span className={`feed-gov-badge ${cls}`}>{event.decision}</span>
      <span className="feed-gov-category">{event.category}</span>
      <span className="feed-gov-text">{event.summary || event.action}</span>
      <span className="feed-gov-time">{formatTs(event.ts)}</span>
    </div>
  );
}

function EventCard({ step, index, costUsd, onOpenFiles }: {
  step: TaskStep;
  index: number;
  costUsd?: number;
  onOpenFiles?: () => void;
}) {
  const role = roleMeta(step.agent);
  const kind = eventKind(step);
  const running = step.status === "running";
  const failed  = step.status === "failed";

  const hasFiles    = step.files_changed.length > 0;
  const gatesPassed = step.gate_results.length > 0 && step.gate_results.every((g) => g.passed);
  const gatesFailed = step.gate_results.some((g) => !g.passed);
  const showPills   = hasFiles || step.gate_results.length > 0 || (costUsd !== undefined && costUsd > 0);

  return (
    <article
      className={`narrative-event-card animate-fadeup ${role.surface} ${role.border}`}
      style={{ animationDelay: `${index * 80 + 20}ms` }}
    >
      <header className="narrative-event-head">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-base">{role.icon}</span>
          <span className={`text-sm font-semibold ${role.color}`}>{role.label}</span>
          <span className={`text-[10px] font-medium uppercase ${statusTone(step.status)}`}>{step.status}</span>
        </div>
        <div className="flex items-center gap-2">
          <KindBadge kind={kind} />
          <span className="text-[10px] text-[var(--ui-text-muted)] font-mono tabular-nums">
            {formatTs(step.started_at || step.completed_at)}
          </span>
        </div>
      </header>

      <div className="mt-3">
        {running && !step.output ? (
          <p className="text-[12px] text-[var(--ui-text-muted)] italic">Working on this step…</p>
        ) : step.output ? (
          <ResponseRenderer output={step.output} maxHeightClass="max-h-72" />
        ) : (
          <p className="text-[12px] text-[var(--ui-text-muted)] italic">
            {failed ? "Execution stopped before output was produced." : "Step completed without textual output."}
          </p>
        )}
      </div>

      {/* Evidence: files */}
      {hasFiles && (
        <section className="narrative-files">
          <p className="narrative-meta-label">Evidence: files changed ({step.files_changed.length})</p>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {step.files_changed.slice(0, 6).map((f) => (
              <span key={f} className="narrative-file-pill">{f}</span>
            ))}
            {step.files_changed.length > 6 && (
              <span className="narrative-file-pill">+{step.files_changed.length - 6} more</span>
            )}
          </div>
        </section>
      )}

      {/* Inline pills row */}
      {showPills && (
        <div className="feed-pills">
          {hasFiles && (
            <button type="button" className="feed-pill files" onClick={onOpenFiles}>
              📁 {step.files_changed.length} file{step.files_changed.length !== 1 ? "s" : ""}
            </button>
          )}
          {step.gate_results.length > 0 && (
            <span className={`feed-pill ${gatesFailed ? "fail" : gatesPassed ? "pass" : ""}`}>
              {gatesFailed ? "⚠️ gate failed" : "✓ gates passed"}
            </span>
          )}
          {costUsd !== undefined && costUsd > 0 && (
            <span className="feed-pill cost">${costUsd.toFixed(4)}</span>
          )}
        </div>
      )}
    </article>
  );
}

function ResolutionCard({ step, index }: { step: TaskStep; index: number }) {
  if (step.gate_results.length === 0) return null;
  const failures = step.gate_results.filter((g) => !g.passed);
  const passed = failures.length === 0;
  return (
    <div
      className={`narrative-resolution animate-fadeup ${passed ? "pass" : "fail"}`}
      style={{ animationDelay: `${index * 80 + 30}ms` }}
    >
      <span className="narrative-meta-label">Resolution</span>
      <p className="mt-1 text-[12px] text-[var(--ui-text-secondary)]">
        {passed
          ? "Rigour gates passed. Master Brain can continue safely."
          : `Rigour raised ${failures.length} issue${failures.length === 1 ? "" : "s"}. Next step should address these findings.`}
      </p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {step.gate_results.map((g, idx) => (
          <span key={`${g.gate}-${idx}`} className={`rounded-md px-2 py-0.5 text-[10px] ${g.passed ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"}`}>
            {g.gate}
          </span>
        ))}
      </div>
    </div>
  );
}

function OrchestratorKickoff({ taskType, count }: { taskType: string; count: number }) {
  return (
    <section className="narrative-kickoff animate-fadeup">
      <div className="flex items-center gap-2">
        <span className="text-base">{"\uD83C\uDFAF"}</span>
        <span className="text-sm font-semibold text-indigo-600">Master Brain</span>
        <span className="text-[10px] text-[var(--ui-text-muted)] uppercase">Orchestrator</span>
      </div>
      <p className="mt-2 text-[13px] text-[var(--ui-text-secondary)] leading-relaxed">
        Task classified as <span className="text-indigo-600 font-semibold">{taskType || "engineering"}</span>. Building and
        supervising a {count}-agent virtual team for this run.
      </p>
    </section>
  );
}

/* ── Main component ── */

interface AgentTimelineProps {
  steps: TaskStep[];
  taskType: string;
  collab?: CollaborationData | null;
  gov?: GovernanceData | null;
  costs?: CostData | null;
  onOpenFiles?: (agent: string, files: string[]) => void;
}

export default function AgentTimeline({ steps, taskType, collab, gov, costs, onOpenFiles }: AgentTimelineProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  const visibleSteps = useMemo(
    () => steps.filter((s) => s.status !== "pending" || Boolean(s.output) || Boolean(s.started_at) || Boolean(s.completed_at)),
    [steps],
  );
  const queued = useMemo(() => steps.filter((s) => !visibleSteps.includes(s)), [steps, visibleSteps]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [visibleSteps.length, visibleSteps[visibleSteps.length - 1]?.status]);

  if (steps.length === 0) return null;

  /** Get collab + governance events whose timestamps fall within a step's window */
  function eventsForStep(step: TaskStep) {
    const start = toMs(step.started_at);
    const end   = toMs(step.completed_at);
    if (start === 0 && end === 0) return { collabEvents: [] as CollabEvent[], govEvents: [] as GovTimelineEvent[] };

    const collabEvents = (collab?.events ?? []).filter((e) => {
      const ts = toMs(e.created_at);
      return ts > 0 && ts >= start && (end === 0 || ts <= end + 5000); // 5s grace
    });
    const govEvents = (gov?.timeline ?? []).filter((e) => {
      const ts = toMs(e.ts);
      return ts > 0 && ts >= start && (end === 0 || ts <= end + 5000);
    });

    return { collabEvents, govEvents };
  }

  return (
    <div className="space-y-3 pb-4">
      <OrchestratorKickoff taskType={taskType} count={steps.length} />

      {visibleSteps.map((step, idx) => {
        const prev = idx > 0 ? visibleSteps[idx - 1] : null;
        const showDecision = idx === 0 || prev?.agent !== step.agent;
        const { collabEvents, govEvents } = eventsForStep(step);
        const agentCost = costs?.per_agent?.[step.agent.toLowerCase()]?.cost_usd;

        return (
          <div key={`${step.agent}-${idx}`} className="narrative-block">
            {showDecision && (
              <DecisionCard from={prev?.agent ?? null} to={step.agent} first={idx === 0} index={idx} />
            )}

            <EventCard
              step={step}
              index={idx}
              costUsd={agentCost}
              onOpenFiles={step.files_changed.length > 0 ? () => onOpenFiles?.(step.agent, step.files_changed) : undefined}
            />

            {/* Inline collab events for this step — agent-to-agent conversation */}
            {collabEvents.map((e, ci) => (
              <CollabRow key={`collab-${idx}-${ci}`} event={e} messages={collab?.messages ?? []} index={ci} />
            ))}

            {/* Inline governance checkpoints — Rigour policy decisions */}
            {govEvents.map((e, gi) => (
              <GovRow key={`gov-${idx}-${gi}`} event={e} index={gi} />
            ))}

            <ResolutionCard step={step} index={idx} />
          </div>
        );
      })}

      {queued.length > 0 && (
        <section className="narrative-queued">
          <p className="narrative-meta-label">Queued agents</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {queued.map((q, idx) => {
              const role = roleMeta(q.agent);
              return (
                <span key={`${q.agent}-${idx}`} className={`rounded-md px-2 py-0.5 text-[10px] ${role.color} bg-[rgba(0,0,0,0.03)]`}>
                  {role.label}
                </span>
              );
            })}
          </div>
        </section>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
