'use client';

import { useEffect, useState } from 'react';

export type AgentNodeStatus = 'waiting' | 'assembling' | 'active' | 'complete' | 'failed' | 'retrying';

export interface AgentNode {
  role: string;
  status: AgentNodeStatus;
  order: number;
  summary?: string;
  durationMs?: number;
  tokens?: number;
}

interface OrchestrationFlowProps {
  phase: string;
  taskType?: string;
  complexity?: string;
  agents: AgentNode[];
  pipelineOrder: string[];
}

const AGENT_COLORS: Record<string, string> = {
  master: '#a78bfa',
  planner: '#60a5fa',
  coder: '#34d399',
  reviewer: '#fb923c',
  qa: '#f472b6',
  sre: '#facc15',
  devops: '#2dd4bf',
};

const AGENT_LABELS: Record<string, string> = {
  master: 'Master',
  planner: 'Planner',
  coder: 'Coder',
  reviewer: 'Reviewer',
  qa: 'QA',
  sre: 'SRE',
  devops: 'DevOps',
};

function getColor(role: string): string {
  return AGENT_COLORS[role] ?? '#71717a';
}

function getLabel(role: string): string {
  return AGENT_LABELS[role] ?? role;
}

function getStatusIcon(status: AgentNodeStatus): string {
  switch (status) {
    case 'waiting': return '○';
    case 'assembling': return '◎';
    case 'active': return '●';
    case 'complete': return '✓';
    case 'failed': return '✕';
    case 'retrying': return '↻';
  }
}

function getStatusLabel(status: AgentNodeStatus): string {
  switch (status) {
    case 'waiting': return 'Standby';
    case 'assembling': return 'Joining...';
    case 'active': return 'Working...';
    case 'complete': return 'Done';
    case 'failed': return 'Failed';
    case 'retrying': return 'Retrying...';
  }
}

/** Master Agent brain node — the orchestrator at the top. */
function MasterBrain({ phase, taskType, complexity }: {
  phase: string;
  taskType?: string;
  complexity?: string;
}) {
  const isThinking = phase === 'classifying' || phase === 'assembling';
  const isDone = phase === 'completed' || phase === 'error';

  return (
    <div className="flex flex-col items-center mb-4">
      <div className={`relative w-14 h-14 rounded-2xl flex items-center justify-center text-lg font-bold
        ${isThinking ? 'master-thinking' : ''}
        ${isDone ? 'opacity-60' : ''}
      `} style={{
        background: `${getColor('master')}15`,
        border: `2px solid ${getColor('master')}40`,
        color: getColor('master'),
      }}>
        R
        {isThinking && (
          <span className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-indigo-500 animate-ping" />
        )}
      </div>

      <span className="text-[11px] font-medium text-zinc-400 mt-1.5">Master Agent</span>

      {phase === 'classifying' && (
        <span className="text-[10px] text-indigo-400 mt-0.5 animate-pulse">
          Analyzing requirements...
        </span>
      )}

      {phase === 'assembling' && (
        <span className="text-[10px] text-indigo-400 mt-0.5 animate-pulse">
          Assembling team...
        </span>
      )}

      {taskType && (
        <div className="flex items-center gap-2 mt-1.5">
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            {taskType}
          </span>
          {complexity && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400 border border-white/[0.06]">
              {complexity}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/** A single agent node in the pipeline. */
function AgentCard({ agent }: { agent: AgentNode }) {
  const color = getColor(agent.role);
  const isActive = agent.status === 'active' || agent.status === 'retrying';
  const isDone = agent.status === 'complete';
  const isFailed = agent.status === 'failed';

  return (
    <div className={`
      flex flex-col items-center px-3 py-2 rounded-xl transition-all duration-500
      ${agent.status === 'waiting' ? 'opacity-30' : 'opacity-100'}
      ${agent.status === 'assembling' ? 'agent-assemble opacity-100' : ''}
      ${isActive ? 'agent-node-active' : ''}
    `} style={{
      background: isActive ? `${color}08` : 'transparent',
      border: isActive ? `1px solid ${color}30` : '1px solid transparent',
    }}>
      {/* Avatar */}
      <div className={`
        w-10 h-10 rounded-xl flex items-center justify-center text-[13px] font-bold transition-all duration-500
        ${isActive ? 'agent-working scale-110' : ''}
      `} style={{
        background: `${color}${agent.status === 'waiting' ? '08' : '18'}`,
        color: color,
        boxShadow: isActive ? `0 0 20px ${color}30` : 'none',
      }}>
        {getLabel(agent.role)[0]}
      </div>

      {/* Label */}
      <span className="text-[11px] font-medium mt-1.5" style={{
        color: agent.status === 'waiting' ? '#52525b' : color,
      }}>
        {getLabel(agent.role)}
      </span>

      {/* Status */}
      <span className={`text-[9px] mt-0.5 ${
        isDone ? 'text-emerald-400' :
        isFailed ? 'text-red-400' :
        isActive ? 'text-indigo-400' :
        'text-zinc-600'
      }`}>
        {getStatusIcon(agent.status)} {getStatusLabel(agent.status)}
      </span>

      {/* Duration badge */}
      {isDone && agent.durationMs && (
        <span className="text-[9px] text-zinc-600 mt-0.5">
          {(agent.durationMs / 1000).toFixed(1)}s
        </span>
      )}
    </div>
  );
}

/** Connection line between agent nodes. */
function ConnectionLine({ fromStatus, toStatus }: {
  fromStatus: AgentNodeStatus;
  toStatus: AgentNodeStatus;
}) {
  const isFlowing = fromStatus === 'complete' && (toStatus === 'active' || toStatus === 'retrying');
  const isDone = fromStatus === 'complete' && toStatus === 'complete';
  const isActive = fromStatus === 'active' || fromStatus === 'complete';

  return (
    <div className="flex items-center mx-1 self-center mt-[-8px]">
      <div className={`
        h-[2px] w-8 rounded-full transition-all duration-700 relative overflow-hidden
        ${isDone ? 'bg-emerald-500/40' :
          isFlowing ? 'bg-indigo-500/40' :
          isActive ? 'bg-zinc-700' :
          'bg-zinc-800/50'}
      `}>
        {isFlowing && (
          <div className="absolute inset-0 flow-dot" style={{
            background: `linear-gradient(90deg, transparent, #6366f1, transparent)`,
          }} />
        )}
      </div>
      <svg width="6" height="10" viewBox="0 0 6 10" className={`
        transition-all duration-500
        ${isDone ? 'text-emerald-500/40' :
          isFlowing ? 'text-indigo-500/40' :
          isActive ? 'text-zinc-700' :
          'text-zinc-800/50'}
      `}>
        <path d="M0 0 L6 5 L0 10" fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    </div>
  );
}

/** The full orchestration flow visualization. */
export function OrchestrationFlow({
  phase,
  taskType,
  complexity,
  agents,
  pipelineOrder,
}: OrchestrationFlowProps) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    requestAnimationFrame(() => setVisible(true));
  }, []);

  // Sort agents by pipeline order
  const sortedAgents = pipelineOrder
    .map((role) => agents.find((a) => a.role === role))
    .filter(Boolean) as AgentNode[];

  // Show fallback if no agents yet
  const hasAgents = sortedAgents.length > 0;
  const showPipeline = phase !== 'connecting' && phase !== 'connected';

  return (
    <div className={`
      px-5 py-4 border-b border-white/[0.04] transition-all duration-500
      ${visible ? 'opacity-100' : 'opacity-0'}
    `} style={{ background: 'rgba(9, 9, 11, 0.6)' }}>
      {/* Master Brain */}
      {showPipeline && (
        <MasterBrain phase={phase} taskType={taskType} complexity={complexity} />
      )}

      {/* Pipeline flow */}
      {hasAgents && (
        <>
          {/* Connection from master to pipeline */}
          <div className="flex justify-center mb-3">
            <div className={`w-[2px] h-4 transition-all duration-500 ${
              phase === 'running' || phase === 'completed' ? 'bg-indigo-500/30' : 'bg-zinc-800'
            }`} />
          </div>

          {/* Agent pipeline */}
          <div className="flex items-start justify-center overflow-x-auto pb-1">
            {sortedAgents.map((agent, i) => (
              <div key={agent.role} className="flex items-start">
                <AgentCard agent={agent} />
                {i < sortedAgents.length - 1 && (
                  <ConnectionLine
                    fromStatus={agent.status}
                    toStatus={sortedAgents[i + 1].status}
                  />
                )}
              </div>
            ))}
          </div>
        </>
      )}

      {/* Minimal connecting state */}
      {!showPipeline && (
        <div className="flex items-center justify-center py-3">
          <span className="text-[11px] text-zinc-600 animate-pulse">
            Connecting to orchestration stream...
          </span>
        </div>
      )}
    </div>
  );
}
