'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { TeamChat } from '../../../components/team/team-chat';
import type { ChatMessage } from '../../../components/team/team-chat';
import { LiveCode } from '../../../components/team/live-code';
import type { CodeFile, RigourStatus } from '../../../components/team/live-code';
import { OrchestrationFlow } from '../../../components/team/orchestration-flow';
import type { AgentNode, AgentNodeStatus } from '../../../components/team/orchestration-flow';

function safeJSON(text: string): Record<string, unknown> | null {
  try {
    return JSON.parse(text) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function uid(): string {
  return crypto.randomUUID();
}

function now(): string {
  return new Date().toISOString();
}

export default function TaskPage() {
  const { id: taskId } = useParams() as { id: string };

  // Chat state
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [typingAgent, setTypingAgent] = useState<string | null>(null);

  // Code editor state
  const [files, setFiles] = useState<CodeFile[]>([]);
  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [rigour, setRigour] = useState<RigourStatus>({ score: null, passed: false, violations: [] });

  // Orchestration state
  const [phase, setPhase] = useState('connecting');
  const [taskType, setTaskType] = useState<string | undefined>();
  const [complexity, setComplexity] = useState<string | undefined>();
  const [agentNodes, setAgentNodes] = useState<AgentNode[]>([]);
  const [pipelineOrder, setPipelineOrder] = useState<string[]>([]);
  const [activeAgent, setActiveAgent] = useState<string | null>(null);

  const esRef = useRef<EventSource | null>(null);

  const addMsg = useCallback((from: string, content: string, type: ChatMessage['type'], to?: string) => {
    setMessages((prev) => [...prev, { id: uid(), from, to, content, timestamp: now(), type }]);
  }, []);

  /** Update an agent node's status in the orchestration flow. */
  const updateAgentNode = useCallback((role: string, updates: Partial<AgentNode>) => {
    setAgentNodes((prev) =>
      prev.map((n) => n.role === role ? { ...n, ...updates } : n)
    );
  }, []);

  useEffect(() => {
    const es = new EventSource(`/api/tasks/${taskId}/stream`);
    esRef.current = es;

    /* ── SSE: connected ─────────────────────────────────────────── */
    es.addEventListener('connected', () => {
      setPhase('connected');
    });

    /* ── SSE: status_update ─────────────────────────────────────── */
    // MasterAgent emits: { from, phase, message, timestamp }
    es.addEventListener('status_update', (e) => {
      const d = safeJSON((e as MessageEvent).data);
      if (!d) return;
      const newPhase = d.phase as string;
      setPhase(newPhase);
      addMsg('master', d.message as string, 'system');
    });

    /* ── SSE: classification ────────────────────────────────────── */
    // MasterAgent emits: { taskType, complexity, suggestedAgents, timestamp }
    es.addEventListener('classification', (e) => {
      const d = safeJSON((e as MessageEvent).data);
      if (!d) return;
      const type = d.taskType as string;
      const cmplx = d.complexity as string;
      const suggested = d.suggestedAgents as string[] | undefined;

      setPhase('classified');
      setTaskType(type);
      setComplexity(cmplx);

      const agentList = suggested?.join(', ') ?? 'analyzing';
      addMsg(
        'master',
        `Classified as **${type}** task (${cmplx}). Considering agents: ${agentList}`,
        'agent',
      );
    });

    /* ── SSE: team_assembled ────────────────────────────────────── */
    // MasterAgent emits: { agents: [{role, priority}], pipelineOrder, timestamp }
    es.addEventListener('team_assembled', (e) => {
      const d = safeJSON((e as MessageEvent).data);
      if (!d || !Array.isArray(d.agents)) return;

      const agents = d.agents as Array<{ role: string; priority: number }>;
      const order = d.pipelineOrder as string[];

      setPhase('assembled');
      setPipelineOrder(order);

      // Create agent nodes — initially all in 'assembling' state, then transition
      const nodes: AgentNode[] = agents.map((a) => ({
        role: a.role,
        status: 'assembling' as AgentNodeStatus,
        order: a.priority,
      }));
      setAgentNodes(nodes);

      // After a short delay, move to 'waiting' to show the assemble animation
      setTimeout(() => {
        setAgentNodes((prev) =>
          prev.map((n) => ({ ...n, status: 'waiting' as AgentNodeStatus }))
        );
      }, 800);

      const roleNames = agents.map((a) => a.role).join(', ');
      addMsg(
        'master',
        `Team assembled! Bringing in: ${roleNames}. Pipeline: ${order.join(' → ')}`,
        'system',
      );
    });

    /* ── SSE: agent_start ───────────────────────────────────────── */
    // MasterAgent emits: { role, order, message, timestamp }
    es.addEventListener('agent_start', (e) => {
      const d = safeJSON((e as MessageEvent).data);
      if (!d) return;
      const role = d.role as string;

      setActiveAgent(role);
      setTypingAgent(role);
      updateAgentNode(role, { status: 'active' });
      addMsg(role, d.message as string, 'agent');
    });

    /* ── SSE: agent_complete ────────────────────────────────────── */
    // MasterAgent emits: { role, status, summary, durationMs, tokens, timestamp }
    es.addEventListener('agent_complete', (e) => {
      const d = safeJSON((e as MessageEvent).data);
      if (!d) return;
      const role = d.role as string;
      const status = d.status as string;
      const summary = d.summary as string;
      const durationMs = d.durationMs as number;
      const tokens = d.tokens as number;

      setTypingAgent(null);

      const nodeStatus: AgentNodeStatus = status === 'success' ? 'complete'
        : status === 'failed' ? 'failed'
        : 'complete'; // needs_fix still counts as done for this agent

      updateAgentNode(role, {
        status: nodeStatus,
        summary,
        durationMs,
        tokens,
      });

      // Add the agent's summary as a message
      if (summary) {
        addMsg(role, summary, 'agent');
      }

      // Add completion badge
      const timeStr = (durationMs / 1000).toFixed(1);
      addMsg(
        role,
        `Finished in ${timeStr}s (${tokens} tokens) — ${status}`,
        status === 'success' ? 'complete' : 'system',
      );

      // Handle code extraction from coder output
      if (role === 'coder' && summary) {
        handleCodeFromSummary(summary);
      }

      // Handle reviewer status for code files
      updateFileStatuses(role, status);
    });

    /* ── SSE: gate_results ──────────────────────────────────────── */
    // MasterAgent emits: { agent, score, passed, violationCount, violations, ... }
    es.addEventListener('gate_results', (e) => {
      const d = safeJSON((e as MessageEvent).data);
      if (!d) return;
      const score = d.score as number | undefined;
      const passed = d.passed as boolean | undefined;
      const agent = d.agent as string;
      const violationCount = d.violationCount as number | undefined;

      if (typeof score === 'number') {
        setRigour({
          score,
          passed: passed ?? score === 100,
          violations: Array.isArray(d.violations)
            ? (d.violations as Array<{ message?: string }>).map((v) => v.message ?? '').filter(Boolean)
            : [],
        });
      }

      // Show gate results in chat
      if (typeof score === 'number') {
        const icon = passed ? '✓' : '✕';
        addMsg(
          'rigour',
          `Quality gates: ${score}/100 ${icon} (${violationCount ?? 0} violations) — checked by ${agent}`,
          'score',
        );
      }
    });

    /* ── SSE: agent_retry ───────────────────────────────────────── */
    // MasterAgent emits: { role, attempt, maxRetries, timestamp }
    es.addEventListener('agent_retry', (e) => {
      const d = safeJSON((e as MessageEvent).data);
      if (!d) return;
      const role = d.role as string;
      const attempt = d.attempt as number;
      const max = d.maxRetries as number;

      updateAgentNode(role, { status: 'retrying' });
      addMsg(role, `Retrying (attempt ${attempt}/${max})...`, 'system');
    });

    /* ── SSE: task_complete ─────────────────────────────────────── */
    // Route emits: { success, steps, totalTokens, duration, retries }
    es.addEventListener('task_complete', (e) => {
      const d = safeJSON((e as MessageEvent).data);
      if (!d) return;
      const success = d.success as boolean;
      const dur = d.duration as number;
      const tokens = d.totalTokens as number;
      const retries = d.retries as number;

      setPhase('completed');
      setTypingAgent(null);
      setActiveAgent(null);

      const durStr = (dur / 1000).toFixed(1);
      addMsg(
        'master',
        success
          ? `Pipeline complete! ${durStr}s total, ${tokens} tokens, ${retries} retries`
          : `Pipeline finished with failures. ${durStr}s, ${retries} retries`,
        'complete',
      );
      es.close();
    });

    /* ── SSE: task_error ────────────────────────────────────────── */
    es.addEventListener('task_error', (e) => {
      const d = safeJSON((e as MessageEvent).data);
      if (!d) return;
      setPhase('error');
      setTypingAgent(null);
      setActiveAgent(null);
      addMsg('master', `Error: ${d.error}`, 'complete');
      es.close();
    });

    return () => es.close();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  /** Extract code blocks from agent summary for the code panel. */
  function handleCodeFromSummary(summary: string) {
    // Try to extract code blocks from markdown
    const codeBlockRegex = /```[\w]*\n([\s\S]*?)```/g;
    let match = codeBlockRegex.exec(summary);
    const codeContent = match ? match[1] : summary;

    const demoPath = 'src/index.ts';
    const lines = codeContent.split('\n').slice(0, 40).map((line: string, i: number) => ({
      number: i + 1,
      content: line,
      isNew: true,
    }));

    setFiles((prev) => {
      const existing = prev.find((f) => f.path === demoPath);
      if (existing) {
        return prev.map((f) =>
          f.path === demoPath ? { ...f, lines, status: 'writing' as const } : f
        );
      }
      return [...prev, { path: demoPath, lines, status: 'writing' as const }];
    });
    setActiveFile(demoPath);
  }

  function updateFileStatuses(agentRole: string, status: string) {
    if (agentRole === 'reviewer') {
      setFiles((prev) =>
        prev.map((f) => ({
          ...f,
          status: status === 'success' ? ('passed' as const) : ('needs_fix' as const),
        }))
      );
    }
    if (agentRole === 'coder') {
      setFiles((prev) =>
        prev.map((f) => ({ ...f, status: 'reviewing' as const }))
      );
    }
  }

  const isComplete = phase === 'completed' || phase === 'error';
  const hasCodePanel = files.length > 0 && !isComplete;

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <header className="flex items-center justify-between px-5 py-3 border-b border-white/[0.04]">
        <div className="flex items-center gap-3">
          <a href="/" className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-md bg-indigo-600 flex items-center justify-center text-white text-[11px] font-bold">
              R
            </div>
          </a>
          <div className="w-px h-5 bg-white/[0.06]" />
          <span className="text-[13px] text-zinc-400 font-mono">{taskId.slice(0, 8)}</span>
          <PhaseIndicator phase={phase} />
        </div>
        <div className="flex items-center gap-3">
          {activeAgent && (
            <span className="text-[11px] text-zinc-500">
              Active: <span className="text-indigo-400">{activeAgent}</span>
            </span>
          )}
          <RigourBadge rigour={rigour} />
        </div>
      </header>

      {/* Orchestration Flow — shows agent pipeline visualization */}
      <OrchestrationFlow
        phase={phase}
        taskType={taskType}
        complexity={complexity}
        agents={agentNodes}
        pipelineOrder={pipelineOrder}
      />

      {/* Main workspace: Chat + Code */}
      <div className="flex-1 flex min-h-0">
        <div className={`${hasCodePanel ? 'w-[45%]' : 'w-full'} border-r border-white/[0.04] p-4 overflow-hidden`}>
          <TeamChat messages={messages} typingAgent={typingAgent} />
        </div>
        {hasCodePanel && (
          <div className="flex-1 p-4 overflow-hidden">
            <LiveCode
              files={files}
              activeFile={activeFile}
              rigour={rigour}
              activeAgent={activeAgent}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function PhaseIndicator({ phase }: { phase: string }) {
  const phaseLabels: Record<string, string> = {
    connecting: 'Connecting...',
    connected: 'Connected',
    classifying: 'Classifying task',
    classified: 'Task classified',
    assembling: 'Assembling team',
    assembled: 'Team assembled',
    running: 'Agents working',
    fixing: 'Applying fixes',
    completed: 'Done',
    error: 'Error',
  };

  const isActive = phase !== 'completed' && phase !== 'error';
  return (
    <span className={`text-[11px] px-2 py-0.5 rounded-full inline-flex items-center gap-1.5 ${
      phase === 'completed'
        ? 'bg-emerald-500/10 text-emerald-400'
        : phase === 'error'
          ? 'bg-red-500/10 text-red-400'
          : 'bg-indigo-500/10 text-indigo-400'
    }`}>
      {isActive && <span className="w-1 h-1 rounded-full bg-current animate-pulse" />}
      {phaseLabels[phase] ?? phase}
    </span>
  );
}

function RigourBadge({ rigour }: { rigour: RigourStatus }) {
  if (rigour.score === null) return null;
  const color = rigour.score === 100
    ? 'text-emerald-400'
    : rigour.score >= 80
      ? 'text-amber-400'
      : 'text-red-400';
  return (
    <span className={`text-[12px] font-mono font-semibold ${color}`}>
      {rigour.score}/100
    </span>
  );
}
