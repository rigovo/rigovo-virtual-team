/* ------------------------------------------------------------------ */
/*  NeuralCalibrationMap — React Flow live agent signal visualization  */
/*  Animated signal pulses · Matrix codenames · Click-to-inspect       */
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

/* ═══════════════════════════════════════════════════════════════════ */
/*  Static topology                                                     */
/* ═══════════════════════════════════════════════════════════════════ */

type NodeStatus = "idle" | "pending" | "running" | "complete" | "failed";
type EdgeKind   = "execution" | "adversarial" | "consultation" | "debate" | "memory";

interface AgentNodeData extends Record<string, unknown> {
  codename:    string;
  label:       string;
  color:       string;
  role:        string;
  status:      NodeStatus;
  isInPipe:    boolean;
  gatesFailed: number;
}

interface SignalEdgeData extends Record<string, unknown> {
  color:    string;
  isActive: boolean;
  dash?:    string;
  dur:      string;
}

/* Fixed canvas positions (React Flow x/y = top-left of 80×80 box) */
const NODE_POS: Record<string, { x: number; y: number }> = {
  master:   { x: 450, y:  10 },
  planner:  { x: 454, y: 160 },
  coder:    { x: 452, y: 330 },
  trinity:  { x:  64, y: 300 },
  reviewer: { x: 210, y: 470 },
  security: { x: 460, y: 490 },
  qa:       { x: 710, y: 470 },
  devops:   { x: 310, y: 620 },
  sre:      { x: 628, y: 620 },
  lead:     { x: 458, y: 730 },
  memory:   { x: 850, y: 180 },
};

const NODE_META: Record<string, { codename: string; label: string; color: string }> = {
  master:   { codename: "NEO",       label: "Master Agent",   color: "#4ade80" },
  planner:  { codename: "MORPHEUS",  label: "Planner",        color: "#4ade80" },
  coder:    { codename: "NEO",       label: "Coder",          color: "#4ade80" },
  trinity:  { codename: "TRINITY",   label: "Rigour Gates",   color: "#22d3ee" },
  reviewer: { codename: "ORACLE",    label: "Reviewer",       color: "#60a5fa" },
  security: { codename: "SMITH",     label: "Security",       color: "#f87171" },
  qa:       { codename: "TANK",      label: "QA",             color: "#fb923c" },
  devops:   { codename: "SMITH",     label: "DevOps",         color: "#f87171" },
  sre:      { codename: "TWINS",     label: "SRE",            color: "#2dd4bf" },
  lead:     { codename: "ARCHITECT", label: "Tech Lead",      color: "#a3a3a3" },
  memory:   { codename: "MEMORY",    label: "Semantic Store", color: "#c084fc" },
};

const EDGE_DEFS: Array<{ id: string; from: string; to: string; kind: EdgeKind; dur: string }> = [
  { id: "e-master-planner",   from: "master",   to: "planner",  kind: "execution",    dur: "2.0s" },
  { id: "e-planner-coder",    from: "planner",  to: "coder",    kind: "execution",    dur: "2.0s" },
  { id: "e-coder-reviewer",   from: "coder",    to: "reviewer", kind: "execution",    dur: "2.2s" },
  { id: "e-coder-security",   from: "coder",    to: "security", kind: "execution",    dur: "2.0s" },
  { id: "e-coder-qa",         from: "coder",    to: "qa",       kind: "execution",    dur: "2.2s" },
  { id: "e-reviewer-devops",  from: "reviewer", to: "devops",   kind: "execution",    dur: "2.4s" },
  { id: "e-security-devops",  from: "security", to: "devops",   kind: "execution",    dur: "2.4s" },
  { id: "e-qa-sre",           from: "qa",       to: "sre",      kind: "execution",    dur: "2.4s" },
  { id: "e-devops-lead",      from: "devops",   to: "lead",     kind: "execution",    dur: "2.6s" },
  { id: "e-sre-lead",         from: "sre",      to: "lead",     kind: "execution",    dur: "2.6s" },
  { id: "e-trinity-coder",    from: "trinity",  to: "coder",    kind: "adversarial",  dur: "1.6s" },
  { id: "e-trinity-reviewer", from: "trinity",  to: "reviewer", kind: "adversarial",  dur: "1.8s" },
  { id: "e-reviewer-coder",   from: "reviewer", to: "coder",    kind: "debate",       dur: "2.0s" },
  { id: "e-memory-master",    from: "memory",   to: "master",   kind: "memory",       dur: "3.2s" },
  { id: "e-memory-coder",     from: "memory",   to: "coder",    kind: "memory",       dur: "3.4s" },
];

/* ── Instance-agent → base-role resolution ──────────────────────────── */
/* Steps may have agent names like "backend-engineer-1" or "security-auditor-2"
   which need to be resolved to the base NODE_META keys for DAG rendering.     */
const BASE_ROLE_KW: Record<string, string> = {
  backend: "coder", frontend: "coder", engineer: "coder", developer: "coder",
  planner: "planner", architect: "planner",
  reviewer: "reviewer",
  qa: "qa", tester: "qa",
  security: "security", auditor: "security",
  devops: "devops",
  sre: "sre", reliability: "sre",
  lead: "lead",
  docs: "lead",      // docs agents route to lead node
  master: "master",
};

/** Resolve a step's agent name to the NODE_META key it maps to. */
function resolveBaseRole(agent: string): string {
  const lower = agent.toLowerCase();
  if (NODE_META[lower]) return lower;
  const parts = lower.split("-").filter(p => !/^\d+$/.test(p));
  for (const part of parts) {
    const mapped = BASE_ROLE_KW[part];
    if (mapped && NODE_META[mapped]) return mapped;
  }
  return lower; // fallback: keep as-is
}

/** Find the first step matching a given base role (NODE_META key). */
function findStepForNode(steps: TaskStep[], nodeId: string): TaskStep | undefined {
  return steps.find(s => resolveBaseRole(s.agent) === nodeId);
}

/** Check if any step matches a given base role. */
function hasStepForNode(steps: TaskStep[], nodeId: string): boolean {
  return steps.some(s => resolveBaseRole(s.agent) === nodeId);
}

const EDGE_COLOR: Record<EdgeKind, string> = {
  execution:    "#4ade80",
  adversarial:  "#f87171",
  consultation: "#60a5fa",
  debate:       "#fb923c",
  memory:       "#c084fc",
};

const EDGE_DASH: Partial<Record<EdgeKind, string>> = {
  memory:       "5 5",
  consultation: "4 4",
};

/* ═══════════════════════════════════════════════════════════════════ */
/*  Custom node                                                         */
/* ═══════════════════════════════════════════════════════════════════ */

function AgentNode({ data }: NodeProps) {
  const d = data as AgentNodeData;
  const isRunning  = d.status === "running";
  const isComplete = d.status === "complete";
  const isFailed   = d.status === "failed";
  const dimmed     = d.status === "idle" && !d.isInPipe;
  const isTrinityFail = d.role === "trinity" && d.gatesFailed > 0;

  const borderColor  = isFailed || isTrinityFail ? "#f87171" : d.color;
  const bgAlpha      = isRunning ? "30" : isComplete ? "22" : isFailed ? "1e" : "14";
  const bgColor      = isFailed ? `#f87171${bgAlpha}` : `${d.color}${bgAlpha}`;
  const nodeOpacity  = dimmed ? 0.2 : 1;
  const borderWidth  = isRunning ? 2 : 1.5;

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
      <span className="ncm-codename" style={{ color: isTrinityFail ? "#f87171" : d.color }}>
        {d.codename}
      </span>

      {/* Status icon */}
      <span className="ncm-status-icon">
        {isRunning  && <span className="ncm-dots"><span/><span/><span/></span>}
        {isComplete && <span style={{ color: d.color }}>✓</span>}
        {isFailed   && <span style={{ color: "#f87171" }}>✕</span>}
        {!isRunning && !isComplete && !isFailed && (
          <span style={{ color: d.color, opacity: dimmed ? 0.4 : 0.7 }}>◎</span>
        )}
      </span>

      {/* Label */}
      <span className="ncm-label">{d.label}</span>

      {/* Invisible handles at all 4 sides */}
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Top}    style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Left}   style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right}  style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Top}    style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Bottom} style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Left}   style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Right}  style={{ opacity: 0 }} />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════ */
/*  Custom animated edge                                                */
/* ═══════════════════════════════════════════════════════════════════ */

function SignalEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps) {
  const d = data as SignalEdgeData;
  const [edgePath] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
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
          <circle r="5" fill={d.color} style={{ filter: `drop-shadow(0 0 4px ${d.color})` }}>
            <animateMotion dur={d.dur} repeatCount="indefinite" path={edgePath} />
          </circle>
          {/* Trailing pulse */}
          <circle r="3" fill={d.color} opacity="0.5">
            <animateMotion dur={d.dur} repeatCount="indefinite" begin={`-${halfDur}s`} path={edgePath} />
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
  steps:         TaskStep[];
  taskStatus:    string;
  taskType?:     string;
  collab:        CollaborationData | null;
  totalFiles:    number;
  totalCost:     number;
  replanCount:   number;
  gatesTotal:    number;
  gatesFailed:   number;
  selectedAgent: string | null;
  onSelectAgent: (role: string) => void;
}

/* ═══════════════════════════════════════════════════════════════════ */
/*  Main component                                                      */
/* ═══════════════════════════════════════════════════════════════════ */

export default function NeuralCalibrationMap({
  steps, taskStatus, taskType = "engineering",
  totalFiles, totalCost, replanCount,
  gatesTotal, gatesFailed, selectedAgent, onSelectAgent,
}: NeuralCalibrationMapProps) {
  const st         = taskStatus.toLowerCase();
  const isComplete = st.includes("complete");
  const isFailed   = st.includes("fail") || st.includes("reject");
  const isActive   = !isComplete && !isFailed;

  /* ── Derive node statuses from steps ─────────────────────────────── */
  const nodeStatuses = useMemo((): Record<string, NodeStatus> => {
    const map: Record<string, NodeStatus> = {};
    for (const id of Object.keys(NODE_META)) {
      if (id === "memory") {
        map[id] = isActive ? "running" : isComplete ? "complete" : "idle";
      } else if (id === "master") {
        map[id] = isComplete ? "complete" : isFailed ? "failed" : "running";
      } else if (id === "trinity") {
        const triggered = steps.some(s => {
          const base = resolveBaseRole(s.agent);
          return ["coder","reviewer"].includes(base) && s.status !== "pending";
        });
        map[id] = triggered ? (gatesFailed > 0 ? "failed" : isActive ? "running" : "complete") : "idle";
      } else {
        const step = findStepForNode(steps, id);
        map[id] = (step?.status as NodeStatus) ?? "idle";
      }
    }
    return map;
  }, [steps, isActive, isComplete, isFailed, gatesFailed]);

  /* ── Nodes in pipeline ────────────────────────────────────────────── */
  const inPipeline = useMemo(() => {
    const s = new Set(["master", "memory"]);
    steps.forEach(step => {
      const base = resolveBaseRole(step.agent);
      if (NODE_META[base]) s.add(base);
    });
    if (steps.some(st => {
      const base = resolveBaseRole(st.agent);
      return ["coder","reviewer","security","qa"].includes(base);
    })) s.add("trinity");
    return s;
  }, [steps]);

  /* ── Build React Flow nodes — only pipeline agents ───────────────── */
  const rfNodes: Node[] = useMemo(() =>
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
          role:        id,
          status:      nodeStatuses[id] ?? "idle",
          isInPipe:    true,
          gatesFailed: id === "trinity" ? gatesFailed : 0,
        } satisfies AgentNodeData,
      })),
    [nodeStatuses, inPipeline, gatesFailed]
  );

  /* ── Build React Flow edges — only between pipeline agents ───────── */
  const rfEdges: Edge[] = useMemo(() => {
    return EDGE_DEFS
      .filter(e => inPipeline.has(e.from) && inPipeline.has(e.to))
      .map(e => {
        const fromStatus = nodeStatuses[e.from];
        const active     = fromStatus === "running" || fromStatus === "complete";
        return {
          id:     e.id,
          source: e.from,
          target: e.to,
          type:   "signal",
          data: {
            color:    EDGE_COLOR[e.kind],
            isActive: active,
            dash:     EDGE_DASH[e.kind],
            dur:      e.dur,
          } satisfies SignalEdgeData,
        };
      });
  }, [nodeStatuses, inPipeline]);

  /* ── Node click ───────────────────────────────────────────────────── */
  const onNodeClick: NodeMouseHandler = useCallback((_evt, node) => {
    const status = nodeStatuses[node.id];
    if (status === "idle") return;
    // Pass the actual instance agent name (e.g. "backend-engineer-1") so
    // AgentDetailPanel can match by step.agent, not base-role key.
    const step = findStepForNode(steps, node.id);
    onSelectAgent(step ? step.agent : node.id);
  }, [nodeStatuses, steps, onSelectAgent]);

  return (
    <div className="ncm-root">

      {/* ── Title bar ── */}
      <div className="ncm-title-bar">
        <span className="ncm-title-label">NEURAL CALIBRATION MAP</span>
        <span className="ncm-title-sub">
          {inPipeline.size} agent{inPipeline.size !== 1 ? "s" : ""} · {taskType} · click node to inspect
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
          <Background variant={BackgroundVariant.Dots} gap={28} size={1} color="#1a2e1a" />
        </ReactFlow>
      </div>

      {/* ── Stats bar ── */}
      <div className="ncm-stats-bar">
        <div className="ncm-stat-item">
          <span className="ncm-stat-num">{totalFiles}</span>
          <span className="ncm-stat-lbl">FILES</span>
        </div>
        <div className="ncm-stat-divider" />
        <div className="ncm-stat-item">
          <span className="ncm-stat-num">{steps.filter(s => s.status === "complete").length}/{steps.length || "—"}</span>
          <span className="ncm-stat-lbl">AGENTS DONE</span>
        </div>
        <div className="ncm-stat-divider" />
        <div className="ncm-stat-item">
          <span className="ncm-stat-num" style={{ color: gatesFailed > 0 ? "#f87171" : "#4ade80" }}>
            {gatesTotal > 0 ? `${gatesTotal - gatesFailed}/${gatesTotal}` : "24"}
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
              <span className="ncm-stat-num" style={{ color: "#fb923c" }}>{replanCount}</span>
              <span className="ncm-stat-lbl">REPLANS</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
