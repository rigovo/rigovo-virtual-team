'use client';

import { useEffect, useRef } from 'react';

export interface CodeFile {
  path: string;
  lines: CodeLine[];
  status: 'writing' | 'reviewing' | 'passed' | 'needs_fix';
}

export interface CodeLine {
  number: number;
  content: string;
  isNew?: boolean;
  hasIssue?: boolean;
  issueMessage?: string;
}

export interface RigourStatus {
  score: number | null;
  passed: boolean;
  violations: string[];
}

interface LiveCodeProps {
  files: CodeFile[];
  activeFile: string | null;
  rigour: RigourStatus;
  activeAgent: string | null;
}

function FileTab({ file, isActive }: { file: CodeFile; isActive: boolean }) {
  const statusDot = getStatusColor(file.status);
  return (
    <button
      className={`flex items-center gap-2 px-3 py-1.5 text-[12px] border-b-2 transition-colors ${
        isActive
          ? 'border-indigo-500 text-zinc-200'
          : 'border-transparent text-zinc-500 hover:text-zinc-400'
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${statusDot}`} />
      {file.path.split('/').pop()}
    </button>
  );
}

function getStatusColor(status: CodeFile['status']): string {
  switch (status) {
    case 'writing': return 'bg-emerald-400 animate-pulse';
    case 'reviewing': return 'bg-amber-400 animate-pulse';
    case 'passed': return 'bg-emerald-400';
    case 'needs_fix': return 'bg-red-400';
  }
}

function getStatusLabel(status: CodeFile['status']): string {
  switch (status) {
    case 'writing': return 'Coder writing...';
    case 'reviewing': return 'Reviewer checking...';
    case 'passed': return 'Passed';
    case 'needs_fix': return 'Fix needed';
  }
}

function LineNumber({ n }: { n: number }) {
  return (
    <span className="inline-block w-8 text-right mr-4 text-zinc-700 select-none text-[11px]">
      {n}
    </span>
  );
}

function IssueAnnotation({ message }: { message: string }) {
  return (
    <div className="ml-12 mt-0.5 mb-1 flex items-start gap-1.5 text-[11px]">
      <span className="text-amber-500 mt-px">▸</span>
      <span className="text-amber-400/80">{message}</span>
    </div>
  );
}

function RigourBar({ rigour }: { rigour: RigourStatus }) {
  if (rigour.score === null) return null;

  const pct = Math.min(100, rigour.score);
  const barColor = pct === 100 ? 'bg-emerald-500' : pct >= 80 ? 'bg-amber-500' : 'bg-red-500';
  const textColor = pct === 100 ? 'text-emerald-400' : pct >= 80 ? 'text-amber-400' : 'text-red-400';

  return (
    <div className="flex items-center gap-3 px-4 py-2 border-t border-white/[0.04]">
      <span className="text-[11px] text-zinc-500">Rigour</span>
      <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`text-[12px] font-mono font-semibold ${textColor}`}>
        {rigour.score}/100
      </span>
    </div>
  );
}

export function LiveCode({ files, activeFile, rigour, activeAgent }: LiveCodeProps) {
  const codeRef = useRef<HTMLDivElement>(null);
  const currentFile = files.find((f) => f.path === activeFile) ?? files[0];

  useEffect(() => {
    if (codeRef.current) {
      codeRef.current.scrollTop = codeRef.current.scrollHeight;
    }
  }, [currentFile?.lines.length]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center border-b border-white/[0.04]">
        <div className="flex overflow-x-auto">
          {files.map((f) => (
            <FileTab key={f.path} file={f} isActive={f.path === currentFile?.path} />
          ))}
        </div>
        {currentFile && (
          <span className="ml-auto px-3 text-[11px] text-zinc-600 shrink-0">
            {getStatusLabel(currentFile.status)}
            {activeAgent && ` · ${activeAgent}`}
          </span>
        )}
      </div>

      <div ref={codeRef} className="flex-1 overflow-y-auto py-3 font-mono text-[12px] leading-5">
        {currentFile ? (
          currentFile.lines.map((line) => (
            <div key={line.number}>
              <div className={`px-3 ${line.isNew ? 'code-line-new' : ''} ${line.hasIssue ? 'bg-red-500/5' : ''}`}>
                <LineNumber n={line.number} />
                <span className="text-zinc-300">{line.content}</span>
              </div>
              {line.hasIssue && line.issueMessage && (
                <IssueAnnotation message={line.issueMessage} />
              )}
            </div>
          ))
        ) : (
          <div className="flex items-center justify-center h-full text-zinc-600 text-[13px]">
            Waiting for code generation...
          </div>
        )}
      </div>

      <RigourBar rigour={rigour} />
    </div>
  );
}
