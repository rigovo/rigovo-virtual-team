/* ------------------------------------------------------------------ */
/*  NeuralCalibrationMap — React Flow live agent pipeline visualization */
/*  Animated signal pulses · Professional titles · Click-to-inspect    */
/* ------------------------------------------------------------------ */
import { useMemo, useCallback } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  BaseEdge,
  getBezierPath,
  Handle,
  Position,
  type Node,
  type Edge,
  type NodeProps,
  type EdgeProps,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { TaskStep } from "../types";
import type { CollaborationData } from "./AgentTimeline";
import { resolveCanonicalRole } from "../lib/agentIdentity";

/* ═══════════════════════════════════════════════════════════════════ */
/*  Static topology                                                     */
/* ═══════════════════════════════════════════════════════════════════ */

type NodeStatus = "idle" | "pending" | "running" | "complete" | "failed";
type EdgeKind =
  | "execution"
  | "adversarial"
  | "consultation"
  | "debate"
  | "memory";

interface AgentNodeData extends Record<string, unknown> {
  codename: string;
  label: string;
  color: string;
  role: string;
  status: NodeStatus;
  isInPipe: boolean;
  gatesFailed: number;
}

interface SignalEdgeData extends Record<string, unknown> {
  color: string;
  isActive: boolean;
  dash?: string;
  dur: string;
}

/* Fixed canvas positions (React Flow x/y = top-left of 80×80 box) */
const NODE_POS: Record<string, { x: number; y: number }> = {
  master: { x: 450, y: 10 },
  planner: { x: 454, y: 160 },
  coder: { x: 452, y: 330 },
  trinity: { x: 64, y: 300 },
  reviewer: { x: 210, y: 470 },
  security: { x: 460, y: 490 },
  qa: { x: 710, y: 470 },
  devops: { x: 310, y: 620 },
  sre: { x: 628, y: 620 },
  lead: { x: 458, y: 730 },
  memory: { x: 850, y: 180 },
};

const NODE_META: Record<
  string,
  { codename: string; label: string; color: string }
> = {
  master: { codename: "◎", label: "Chief Architect", color: "#a5b4fc" },
  planner: { codename: "PM", label: "Project Manager", color: "#a5b4fc" },
  coder: { codename: "SE", label: "Software Engineer", color: "#a5b4fc" },
  trinity: { codename: "QG", label: "Quality Gates", color: "#94a3b8" },
  reviewer: { codename: "CR", label: "Code Reviewer", color: "#a5b4fc" },
  security: { codename: "SC", label: "Security Engineer", color: "#a5b4fc" },
  qa: { codename: "QA", label: "QA Engineer", color: "#a5b4fc" },
  devops: { codename: "DO", label: "DevOps Engineer", color: "#a5b4fc" },
  sre: { codename: "SR", label: "SRE Engineer", color: "#94a3b8" },
  lead: { codename: "TL", label: "Tech Lead", color: "#a5b4fc" },
  memory: { codename: "KB", label: "Knowledge Base", color: "#94a3b8" },
};

const STATIC_EDGE_DEFS: Array<{
  id: string;
  from: string;
  to: string;
  kind: EdgeKind;
  dur: string;
}> = [
  {
    id: "e-master-planner",
    from: "master",
    to: "planner",
    kind: "execution",
    dur: "2.0s",
  },
  {
    id: "e-planner-coder",
    from: "planner",
    to: "coder",
    kind: "execution",
    dur: "2.0s",
  },
  {
    id: "e-coder-reviewer",
    from: "coder",
    to: "reviewer",
    kind: "execution",
    dur: "2.2s",
  },
  {
    id: "e-coder-security",
    from: "coder",
    to: "security",
    kind: "execution",
    dur: "2.0s",
  },
  { id: "e-coder-qa", from: "coder", to: "qa", kind: "execution", dur: "2.2s" },
  {
    id: "e-reviewer-devops",
    from: "reviewer",
    to: "devops",
    kind: "execution",
    dur: "2.4s",
  },
  {
    id: "e-security-devops",
    from: "security",
    to: "devops",
    kind: "execution",
    dur: "2.4s",
  },
  { id: "e-qa-sre", from: "qa", to: "sre", kind: "execution", dur: "2.4s" },
  {
    id: "e-devops-lead",
    from: "devops",
    to: "lead",
    kind: "execution",
    dur: "2.6s",
  },
  { id: "e-sre-lead", from: "sre", to: "lead", kind: "execution", dur: "2.6s" },
  {
    id: "e-trinity-coder",
    from: "trinity",
    to: "coder",
    kind: "adversarial",
    dur: "1.6s",
  },
  {
    id: "e-trinity-reviewer",
    from: "trinity",
    to: "reviewer",
    kind: "adversarial",
    dur: "1.8s",
  },
  {
    id: "e-reviewer-coder",
    from: "reviewer",
    to: "coder",
    kind: "debate",
    dur: "2.0s",
  },
  {
    id: "e-memory-master",
    from: "memory",
    to: "master",
    kind: "memory",
    dur: "3.2s",
  },
  {
    id: "e-memory-coder",
    from: "memory",
    to: "coder",
    kind: "memory",
    dur: "3.4s",
  },
];

/* Fallback edges — injected when certain nodes are absent so Lead/other terminal
   nodes don't become disconnected in small pipelines. Each fallback has a
   `requireAbsent` list: it's only added if ALL those nodes are outside the pipeline. */
const FALLBACK_EDGES: Array<{
  id: string;
  from: string;
  to: string;
  kind: EdgeKind;
  dur: string;
  requireAbsent: string[];
}> = [
  // Lead: connect directly from coder when devops+sre are absent
  {
    id: "e-coder-lead-fb",
    from: "coder",
    to: "lead",
    kind: "execution",
    dur: "2.4s",
    requireAbsent: ["devops", "sre"],
  },
  // Lead: connect directly from reviewer when devops is absent
  {
    id: "e-reviewer-lead-fb",
    from: "reviewer",
    to: "lead",
    kind: "execution",
    dur: "2.4s",
    requireAbsent: ["devops"],
  },
  // Lead: connect directly from security when devops is absent
  {
    id: "e-security-lead-fb",
    from: "security",
    to: "lead",
    kind: "execution",
    dur: "2.4s",
    requireAbsent: ["devops"],
  },
  // QA: connect directly to lead when sre is absent
  {
    id: "e-qa-lead-fb",
    from: "qa",
    to: "lead",
    kind: "execution",
    dur: "2.4s",
    requireAbsent: ["sre"],
  },
];

/** Resolve a step's agent name to the NODE_META key it maps to. */
function resolveBaseRole(agent: string): string {
  const canonical = resolveCanonicalRole(agent);
  if (canonical === "rigour") return "trinity";
  if (canonical === "docs") return "lead";
  return canonical;
}

/** Find the first step matching a given base role (NODE_META key). */
function findStepForNode(
  steps: TaskStep[],
  nodeId: string,
): TaskStep | undefined {
  return steps.find((s) => resolveBaseRole(s.agent_role || s.agent) === nodeId);
}

/** Check if any step matches a given base role. */
function hasStepForNode(steps: TaskStep[], nodeId: string): boolean {
  return steps.some((s) => resolveBaseRole(s.agent_role || s.agent) === nodeId);
}

function isWorkRole(role: string): boolean {
  return !["master", "memory", "trinity"].includes(role);
}

const EDGE_COLOR: Record<EdgeKind, string> = {
  execution: "#818cf8",
  adversarial: "#f87171",
  consultation: "#818cf8",
  debate: "#818cf8",
  memory: "#64748b",
};

const EDGE_DASH: Partial<Record<EdgeKind, string>> = {
  memory: "5 5",
  consultation: "4 4",
};

/* ═══════════════════════════════════════════════════════════════════ */
/*  Custom node                                                         */
/* ═══════════════════════════════════════════════════════════════════ */

function AgentNode({ data }: NodeProps) {
  const d = data as AgentNodeData;
  const isRunning = d.status === "running";
  const isComplete = d.status === "complete";
  const isFailed = d.status === "failed";
  const dimmed = d.status === "idle" && !d.isInPipe;
  const isTrinityFail = d.role === "trinity" && d.gatesFailed > 0;

  const borderColor = isFailed || isTrinityFail ? "#f87171" : d.color;
  const bgAlpha = isRunning ? "30" : isComplete ? "22" : isFailed ? "1e" : "14";
  const bgColor = isFailed ? `#f87171${bgAlpha}` : `${d.color}${bgAlpha}`;
  const nodeOpacity = dimmed ? 0.2 : 1;
  const borderWidth = isRunning ? 2 : 1.5;

  return (
    <div
      className="ncm-node"
      style={{
        opacity: nodeOpacity,
        borderColor,
        borderWidth,
        background: bgColor,
        boxShadow: isRunning
          ? `0 0 16px ${d.color}55, 0 0 32px ${d.color}22`
          : isComplete
            ? `0 0 8px ${d.color}33`
            : undefined,
      }}
    >
      {/* Pulse ring when running */}
      {isRunning && <span className="ncm-pulse-ring" style={{ borderColor }} />}

      {/* Codename */}
      <span
        className="ncm-codename"
        style={{ color: isTrinityFail ? "#f87171" : d.color }}
      >
        {d.codename}
      </span>

      {/* Status icon */}
      <span className="ncm-status-icon">
        {isRunning && (
          <span className="ncm-dots">
            <span />
            <span />
            <span />
          </span>
        )}
        {isComplete && <span style={{ color: d.color }}>✓</span>}
        {isFailed && <span style={{ color: "#f87171" }}>✕</span>}
        {!isRunning && !isComplete && !isFailed && (
          <span style={{ color: d.color, opacity: dimmed ? 0.4 : 0.7 }}>◎</span>
        )}
      </span>

      {/* Label */}
      <span className="ncm-label">{d.label}</span>

      {/* Invisible handles at all 4 sides */}
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Top} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Bottom} style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════ */
/*  Custom animated edge                                                */
/* ═══════════════════════════════════════════════════════════════════ */

function SignalEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps) {
  const d = data as SignalEdgeData;
  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });
  const halfDur = parseFloat(d.dur) / 2;

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: d.color,
          strokeOpacity: d.isActive ? 0.45 : 0.18,
          strokeWidth: d.isActive ? 1.5 : 1,
          strokeDasharray: d.dash,
        }}
      />
      {d.isActive && (
        <>
          {/* Primary pulse */}
          <circle
            r="5"
            fill={d.color}
            style={{ filter: `drop-shadow(0 0 4px ${d.color})` }}
          >
            <animateMotion
              dur={d.dur}
              repeatCount="indefinite"
              path={edgePath}
            />
          </circle>
          {/* Trailing pulse */}
          <circle r="3" fill={d.color} opacity="0.5">
            <animateMotion
              dur={d.dur}
              repeatCount="indefinite"
              begin={`-${halfDur}s`}
              path={edgePath}
            />
          </circle>
        </>
      )}
    </>
  );
}

const NODE_TYPES = { agent: AgentNode };
const EDGE_TYPES = { signal: SignalEdge };

/* ═══════════════════════════════════════════════════════════════════ */
/*  Props                                                               */
/* ═══════════════════════════════════════════════════════════════════ */

export interface NeuralCalibrationMapProps {
  steps: TaskStep[];
  taskStatus: string;
  taskType?: string;
  collab: CollaborationData | null;
  plannedRoles?: string[];
  totalFiles: number;
  totalCost: number;
  expectedAgents?: number;
  nextExpectedRole?: string | null;
  replanCount: number;
  gatesTotal: number;
  gatesFailed: number;
  selectedAgent: string | null;
  onSelectAgent: (role: string) => void;
}

/* ═══════════════════════════════════════════════════════════════════ */
/*  Main component                                                      */
/* ═══════════════════════════════════════════════════════════════════ */

export default function NeuralCalibrationMap({
  steps,
  taskStatus,
  taskType = "engineering",
  collab,
  plannedRoles = [],
  totalFiles,
  totalCost,
  expectedAgents,
  nextExpectedRole,
  replanCount,
  gatesTotal,
  gatesFailed,
  selectedAgent,
  onSelectAgent,
}: NeuralCalibrationMapProps) {
  const st = taskStatus.toLowerCase();
  const isComplete = st.includes("complete");
  const isFailed = st.includes("fail") || st.includes("reject");
  const isActive = !isComplete && !isFailed;

  /* ── Derive node statuses from steps ─────────────────────────────── */
  const nodeStatuses = useMemo((): Record<string, NodeStatus> => {
    const map: Record<string, NodeStatus> = {};
    for (const id of Object.keys(NODE_META)) {
      if (id === "memory") {
        map[id] = isActive
          ? "running"
          : isComplete
            ? "complete"
            : isFailed
              ? "failed"
              : "idle";
      } else if (id === "master") {
        map[id] = isComplete ? "complete" : isFailed ? "failed" : "running";
      } else if (id === "trinity") {
        const triggered = steps.some((s) => {
          const base = resolveBaseRole(s.agent_role || s.agent);
          return ["coder", "reviewer"].includes(base) && s.status !== "pending";
        });
        map[id] = triggered
          ? gatesFailed > 0
            ? "failed"
            : isActive
              ? "running"
              : "complete"
          : "idle";
      } else {
        const step = findStepForNode(steps, id);
        map[id] = (step?.status as NodeStatus) ?? "idle";
      }
    }
    return map;
  }, [steps, isActive, isComplete, isFailed, gatesFailed]);

  /* ── Nodes in pipeline ────────────────────────────────────────────── */
  const inPipeline = useMemo(() => {
    const hasMemorySignal = (collab?.events ?? []).some(
      (event) => event.type === "memory_injection",
    );
    const s = new Set(["master"]);
    if (hasMemorySignal) s.add("memory");
    steps.forEach((step) => {
      const base = resolveBaseRole(step.agent_role || step.agent);
      if (NODE_META[base]) s.add(base);
    });
    plannedRoles.forEach((role) => {
      const base = resolveBaseRole(role);
      if (NODE_META[base]) s.add(base);
    });
    if (
      steps.some((st) => {
        const base = resolveBaseRole(st.agent_role || st.agent);
        return ["coder", "reviewer", "security", "qa"].includes(base);
      })
    )
      s.add("trinity");
    return s;
  }, [steps, plannedRoles, collab]);

  /* ── Build React Flow nodes — only pipeline agents ───────────────── */
  const rfNodes: Node[] = useMemo(
    () =>
      Object.entries(NODE_META)
        .filter(([id]) => inPipeline.has(id))
        .map(([id, meta]) => ({
          id,
          type: "agent",
          position: NODE_POS[id],
          draggable: false,
          selectable: true,
          data: {
            ...meta,
            role: id,
            status: nodeStatuses[id] ?? "idle",
            isInPipe: true,
            gatesFailed: id === "trinity" ? gatesFailed : 0,
          } satisfies AgentNodeData,
        })),
    [nodeStatuses, inPipeline, gatesFailed],
  );

  /* ── Build React Flow edges — only between pipeline agents ───────── */
  const rfEdges: Edge[] = useMemo(() => {
    // Start with static edges that connect nodes present in the pipeline
    const staticFiltered = STATIC_EDGE_DEFS.filter(
      (e) => inPipeline.has(e.from) && inPipeline.has(e.to),
    );

    // Add fallback edges for small pipelines where some nodes are absent.
    // A fallback edge activates only when ALL its requireAbsent nodes are
    // missing from the pipeline, ensuring the graph stays connected.
    const fallbackFiltered = FALLBACK_EDGES.filter(
      (e) =>
        inPipeline.has(e.from) &&
        inPipeline.has(e.to) &&
        e.requireAbsent.every((n) => !inPipeline.has(n)),
    );

    const allEdges = [...staticFiltered, ...fallbackFiltered];

    return allEdges.map((e) => {
      const fromStatus = nodeStatuses[e.from];
      // Only animate edges while pipeline is actively running.
      // Once complete or failed, all edges go static (no more pulses).
      const active =
        isActive && (fromStatus === "running" || fromStatus === "complete");
      return {
        id: e.id,
        source: e.from,
        target: e.to,
        type: "signal",
        data: {
          color: EDGE_COLOR[e.kind],
          isActive: active,
          dash: EDGE_DASH[e.kind],
          dur: e.dur,
        } satisfies SignalEdgeData,
      };
    });
  }, [nodeStatuses, inPipeline, isActive]);

  /* ── Node click ───────────────────────────────────────────────────── */
  const onNodeClick: NodeMouseHandler = useCallback(
    (_evt, node) => {
      const status = nodeStatuses[node.id];
      if (status === "idle") return;
      // Pass the actual instance agent name (e.g. "backend-engineer-1") so
      // AgentDetailPanel can match by step.agent, not base-role key.
      const step = findStepForNode(steps, node.id);
      onSelectAgent(step ? step.agent : node.id);
    },
    [nodeStatuses, steps, onSelectAgent],
  );

  const progress = useMemo(() => {
    const byRole = new Map<string, { completed: boolean; running: boolean }>();
    steps.forEach((s) => {
      const role = resolveBaseRole(s.agent_role || s.agent);
      if (!isWorkRole(role)) return;
      const prev = byRole.get(role) ?? { completed: false, running: false };
      if (s.status === "complete") prev.completed = true;
      if (s.status === "running") prev.running = true;
      byRole.set(role, prev);
    });
    const completed = Array.from(byRole.values()).filter(
      (v) => v.completed,
    ).length;
    const running = Array.from(byRole.values()).some((v) => v.running);
    const derivedTotal = new Set([
      ...Array.from(byRole.keys()),
      ...plannedRoles
        .map((r) => resolveBaseRole(r))
        .filter((r) => isWorkRole(r)),
    ]).size;
    return { completed, running, derivedTotal };
  }, [steps, plannedRoles]);

  const completedCount = progress.completed;
  const totalAgentCount =
    expectedAgents && expectedAgents > 0
      ? expectedAgents
      : progress.derivedTotal;
  const hasRunning = progress.running;
  const debateRounds = collab?.summary?.debate_rounds ?? 0;

  return (
    <div className="ncm-root">
      {/* ── Title bar ── */}
      <div className="ncm-title-bar">
        <span className="ncm-title-label">AGENT PIPELINE</span>
        <span className="ncm-title-sub">
          {inPipeline.size} agent{inPipeline.size !== 1 ? "s" : ""} · {taskType}{" "}
          · click node to inspect
        </span>
      </div>

      {/* ── React Flow canvas ── */}
      <div className="ncm-canvas">
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={NODE_TYPES}
          edgeTypes={EDGE_TYPES}
          onNodeClick={onNodeClick}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={true}
          colorMode="dark"
          proOptions={{ hideAttribution: true }}
        >
          <Background
            variant={BackgroundVariant.Dots}
            gap={28}
            size={1}
            color="#1a2e1a"
          />
        </ReactFlow>
      </div>

      {/* ── Pipeline status overlay when finished ── */}
      {(isComplete || isFailed) && (
        <div
          className={`ncm-pipeline-status ${isFailed ? "failed" : "complete"}`}
        >
          <span>{isFailed ? "✕ Pipeline Failed" : "✓ Pipeline Complete"}</span>
        </div>
      )}
      {isActive &&
        !hasRunning &&
        completedCount > 0 &&
        totalAgentCount > completedCount && (
          <div
            className="ncm-pipeline-status"
            style={{ top: 12, right: 12, left: "auto" }}
          >
            <span>
              Waiting for next agent
              {nextExpectedRole ? `: ${nextExpectedRole}` : ""} (
              {completedCount}/{totalAgentCount})
            </span>
          </div>
        )}

      {/* ── Stats bar ── */}
      <div className="ncm-stats-bar">
        <div className="ncm-stat-item">
          <span className="ncm-stat-num">{totalFiles}</span>
          <span className="ncm-stat-lbl">FILES</span>
        </div>
        <div className="ncm-stat-divider" />
        <div className="ncm-stat-item">
          <span className="ncm-stat-num">
            {completedCount}/{totalAgentCount || "—"}
          </span>
          <span className="ncm-stat-lbl">AGENTS DONE</span>
        </div>
        <div className="ncm-stat-divider" />
        <div className="ncm-stat-item">
          <span
            className="ncm-stat-num"
            style={{ color: gatesFailed > 0 ? "#f87171" : "#a5b4fc" }}
          >
            {gatesTotal > 0 ? `${gatesTotal - gatesFailed}/${gatesTotal}` : "—"}
          </span>
          <span className="ncm-stat-lbl">GATES PASS</span>
        </div>
        <div className="ncm-stat-divider" />
        <div className="ncm-stat-item">
          <span className="ncm-stat-num">${totalCost.toFixed(4)}</span>
          <span className="ncm-stat-lbl">COST</span>
        </div>
        {replanCount > 0 && (
          <>
            <div className="ncm-stat-divider" />
            <div className="ncm-stat-item">
              <span className="ncm-stat-num" style={{ color: "#a5b4fc" }}>
                {replanCount}
              </span>
              <span className="ncm-stat-lbl">REPLANS</span>
            </div>
          </>
        )}
        {debateRounds > 0 && (
          <>
            <div className="ncm-stat-divider" />
            <div className="ncm-stat-item">
              <span className="ncm-stat-num" style={{ color: "#a5b4fc" }}>
                {debateRounds}
              </span>
              <span className="ncm-stat-lbl">DEBATES</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
