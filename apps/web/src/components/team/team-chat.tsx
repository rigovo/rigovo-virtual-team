'use client';

import { useEffect, useRef } from 'react';

export interface ChatMessage {
  id: string;
  from: string;
  to?: string;
  content: string;
  timestamp: string;
  type: 'system' | 'agent' | 'handoff' | 'score' | 'complete';
  codeSnippet?: string;
}

interface TeamChatProps {
  messages: ChatMessage[];
  typingAgent: string | null;
}

const AGENT_CONFIG: Record<string, { color: string; label: string }> = {
  master: { color: '#a78bfa', label: 'Master' },
  planner: { color: '#60a5fa', label: 'Planner' },
  coder: { color: '#34d399', label: 'Coder' },
  reviewer: { color: '#fb923c', label: 'Reviewer' },
  qa: { color: '#f472b6', label: 'QA' },
  sre: { color: '#facc15', label: 'SRE' },
  devops: { color: '#2dd4bf', label: 'DevOps' },
  rigour: { color: '#818cf8', label: 'Rigour' },
};

function getAgent(role: string) {
  return AGENT_CONFIG[role] ?? { color: '#71717a', label: role };
}

function AgentBubble({ msg }: { msg: ChatMessage }) {
  const agent = getAgent(msg.from);
  const isSystem = msg.type === 'system';
  const isComplete = msg.type === 'complete';

  if (isSystem) {
    return (
      <div className="flex justify-center my-3">
        <span className="text-[11px] text-zinc-600 bg-zinc-800/40 px-3 py-1 rounded-full">
          {msg.content}
        </span>
      </div>
    );
  }

  return (
    <div className={`flex gap-2.5 mb-4 ${isComplete ? 'mb-6' : ''}`}>
      <div
        className={`w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 mt-0.5 ${msg.from === 'coder' || msg.from === 'reviewer' ? 'agent-working' : ''}`}
        style={{ background: `${agent.color}20`, color: agent.color }}
      >
        {agent.label[0]}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 mb-1">
          <span className="text-[13px] font-medium" style={{ color: agent.color }}>
            {agent.label}
          </span>
          {msg.to && (
            <span className="text-[11px] text-zinc-600">
              → {getAgent(msg.to).label}
            </span>
          )}
          <span className="text-[10px] text-zinc-700 ml-auto shrink-0">
            {formatTime(msg.timestamp)}
          </span>
        </div>
        <p className="text-[13px] text-zinc-300 leading-relaxed">{msg.content}</p>
        {msg.codeSnippet && <CodeBlock code={msg.codeSnippet} />}
        {isComplete && <CompleteBadge success={msg.content.includes('success')} />}
      </div>
    </div>
  );
}

function CodeBlock({ code }: { code: string }) {
  return (
    <pre className="mt-2 p-3 rounded-lg bg-black/30 border border-white/[0.04] text-[12px] text-emerald-300/80 font-mono overflow-x-auto leading-5">
      {code}
    </pre>
  );
}

function CompleteBadge({ success }: { success: boolean }) {
  return (
    <div className={`inline-flex items-center gap-1.5 mt-2 px-2.5 py-1 rounded-md text-[11px] font-medium ${
      success
        ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
        : 'bg-red-500/10 text-red-400 border border-red-500/20'
    }`}>
      <span>{success ? '●' : '○'}</span>
      {success ? 'Pipeline Complete' : 'Pipeline Failed'}
    </div>
  );
}

function TypingIndicator({ agent }: { agent: string }) {
  const config = getAgent(agent);
  return (
    <div className="flex gap-2.5 mb-4">
      <div
        className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 agent-working"
        style={{ background: `${config.color}20`, color: config.color }}
      >
        {config.label[0]}
      </div>
      <div className="flex items-center gap-1 pt-2">
        <span className="w-1.5 h-1.5 rounded-full bg-zinc-500 animate-bounce" style={{ animationDelay: '0ms' }} />
        <span className="w-1.5 h-1.5 rounded-full bg-zinc-500 animate-bounce" style={{ animationDelay: '150ms' }} />
        <span className="w-1.5 h-1.5 rounded-full bg-zinc-500 animate-bounce" style={{ animationDelay: '300ms' }} />
      </div>
    </div>
  );
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '';
  }
}

export function TeamChat({ messages, typingAgent }: TeamChatProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, typingAgent]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-1 pb-3 border-b border-white/[0.04] mb-4">
        <span className="text-[13px] font-medium text-zinc-300">Team Chat</span>
        <span className="text-[11px] text-zinc-600 ml-auto">
          {messages.length} messages
        </span>
      </div>
      <div className="flex-1 overflow-y-auto pr-1">
        {messages.map((msg) => (
          <AgentBubble key={msg.id} msg={msg} />
        ))}
        {typingAgent && <TypingIndicator agent={typingAgent} />}
        <div ref={endRef} />
      </div>
    </div>
  );
}
