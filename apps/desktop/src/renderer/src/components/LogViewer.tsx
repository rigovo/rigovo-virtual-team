/* ------------------------------------------------------------------ */
/*  LogViewer — browse app, error, and audit logs from the desktop UI  */
/* ------------------------------------------------------------------ */
import { useCallback, useEffect, useState } from "react";
import { API_BASE, readJson } from "../api";

interface LogFile {
  name: string;
  size_bytes: number;
  size_human: string;
  modified_at: string;
}

interface LogData {
  name: string;
  lines: string[];
  total_lines: number;
  truncated: boolean;
  showing?: string;
}

interface LogViewerProps {
  onBack: () => void;
}

const LOG_ICONS: Record<string, string> = {
  "app.log": "\uD83D\uDCDD",     // memo
  "error.log": "\u26A0\uFE0F",   // warning
  "audit.log": "\uD83D\uDD12",   // lock
};

const LOG_DESCRIPTIONS: Record<string, string> = {
  "app.log": "All application events — API requests, startup, task lifecycle",
  "error.log": "Errors and warnings only — save failures, crashes, timeouts",
  "audit.log": "Structured audit trail — task creation, approvals, settings changes",
};

/* Line-level coloring */
function lineClass(line: string): string {
  if (line.includes("ERROR") || line.includes('"level": "ERROR"')) return "text-rose-400";
  if (line.includes("WARNING") || line.includes('"level": "WARNING"')) return "text-amber-400";
  if (line.includes("INFO") && (line.includes("Task created") || line.includes("Updated"))) return "text-emerald-400";
  return "text-slate-400";
}

export default function LogViewer({ onBack }: LogViewerProps) {
  const [files, setFiles] = useState<LogFile[]>([]);
  const [selectedLog, setSelectedLog] = useState<string | null>(null);
  const [logData, setLogData] = useState<LogData | null>(null);
  const [loading, setLoading] = useState(true);
  const [logLoading, setLogLoading] = useState(false);
  const [tail, setTail] = useState(200);
  const [autoRefresh, setAutoRefresh] = useState(false);

  /* Load log file list */
  const loadFiles = useCallback(async () => {
    const res = await readJson<{ files: LogFile[] }>(`${API_BASE}/v1/logs`);
    if (res?.files) setFiles(res.files);
    setLoading(false);
  }, []);

  useEffect(() => { void loadFiles(); }, [loadFiles]);

  /* Load selected log content */
  const loadLog = useCallback(async (name: string, lines: number) => {
    setLogLoading(true);
    const res = await readJson<LogData>(`${API_BASE}/v1/logs/${name}?tail=${lines}`);
    if (res) setLogData(res);
    setLogLoading(false);
  }, []);

  useEffect(() => {
    if (selectedLog) void loadLog(selectedLog, tail);
  }, [selectedLog, tail, loadLog]);

  /* Auto-refresh every 3 seconds when enabled */
  useEffect(() => {
    if (!autoRefresh || !selectedLog) return;
    const interval = window.setInterval(() => {
      void loadLog(selectedLog, tail);
    }, 3000);
    return () => window.clearInterval(interval);
  }, [autoRefresh, selectedLog, tail, loadLog]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin h-6 w-6 border-2 border-brand border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="w-full py-6 px-6 animate-fadeup h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 mb-5 flex-shrink-0">
        <button type="button" onClick={selectedLog ? () => { setSelectedLog(null); setLogData(null); } : onBack}
          className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white transition">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M10 12L6 8L10 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </button>
        <h1 className="text-lg font-semibold text-slate-100">
          {selectedLog ? `Logs: ${selectedLog}` : "System Logs"}
        </h1>
        {selectedLog && (
          <div className="ml-auto flex items-center gap-3">
            {/* Auto-refresh toggle */}
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="rounded border-white/20 bg-white/5 text-brand focus:ring-brand/30"
              />
              <span className="text-xs text-slate-500">Auto-refresh</span>
            </label>
            {/* Tail control */}
            <select
              value={tail}
              onChange={(e) => setTail(Number(e.target.value))}
              className="rounded-lg bg-white/5 border border-white/10 px-2 py-1 text-xs text-slate-300 focus:outline-none focus:border-brand/50"
            >
              <option value={50}>Last 50 lines</option>
              <option value={200}>Last 200 lines</option>
              <option value={500}>Last 500 lines</option>
              <option value={1000}>Last 1000 lines</option>
            </select>
            {/* Refresh button */}
            <button
              type="button"
              onClick={() => void loadLog(selectedLog, tail)}
              className="px-3 py-1.5 text-xs font-medium rounded-lg bg-white/5 text-slate-300 hover:bg-white/10 transition"
            >
              Refresh
            </button>
          </div>
        )}
      </div>

      {!selectedLog ? (
        /* ── Log file list ── */
        <div className="space-y-3">
          <p className="text-sm text-slate-500 mb-4">
            Logs are stored in your project's <code className="text-xs bg-white/5 rounded px-1.5 py-0.5">.rigovo/logs/</code> folder.
            No secrets or API keys are ever logged.
          </p>

          {files.length === 0 ? (
            <div className="card p-6 text-center">
              <p className="text-sm text-slate-500">No log files yet. Logs will appear after the backend processes its first request.</p>
            </div>
          ) : (
            files.map((f) => (
              <button
                key={f.name}
                type="button"
                onClick={() => setSelectedLog(f.name)}
                className="card p-4 w-full text-left hover:border-brand/30 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <span className="text-lg">{LOG_ICONS[f.name] || "\uD83D\uDCC4"}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-slate-200">{f.name}</span>
                      <span className="text-[10px] bg-white/5 text-slate-500 px-1.5 py-0.5 rounded">{f.size_human}</span>
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5">
                      {LOG_DESCRIPTIONS[f.name] || "Log file"}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-[10px] text-slate-600">Last modified</p>
                    <p className="text-xs text-slate-400">
                      {new Date(f.modified_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                    </p>
                  </div>
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="text-slate-600">
                    <path d="M6 4L10 8L6 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
              </button>
            ))
          )}
        </div>
      ) : (
        /* ── Log content viewer ── */
        <div className="flex-1 min-h-0 flex flex-col">
          {/* Status bar */}
          {logData && (
            <div className="flex items-center gap-3 mb-2 flex-shrink-0 text-[10px] text-slate-600">
              <span>{logData.showing || `${logData.lines.length} lines`}</span>
              {logData.truncated && <span className="text-amber-500/60">Truncated — increase tail to see more</span>}
              {autoRefresh && (
                <span className="flex items-center gap-1 text-emerald-500/60">
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  Live
                </span>
              )}
            </div>
          )}

          {/* Log lines */}
          <div className="flex-1 min-h-0 overflow-y-auto rounded-xl border border-white/[0.06] bg-[#0d1117] font-mono text-xs">
            {logLoading && !logData ? (
              <div className="flex items-center justify-center h-full">
                <div className="animate-spin h-4 w-4 border-2 border-brand border-t-transparent rounded-full" />
              </div>
            ) : logData?.lines.length === 0 ? (
              <p className="text-slate-600 p-4 text-center">Log file is empty</p>
            ) : (
              <div className="p-3">
                {logData?.lines.map((line, i) => (
                  <div key={i} className={`py-0.5 leading-relaxed ${lineClass(line)} hover:bg-white/[0.02]`}>
                    <span className="text-slate-700 select-none tabular-nums inline-block w-10 text-right mr-3">
                      {(logData.total_lines - logData.lines.length + i + 1)}
                    </span>
                    {line}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
