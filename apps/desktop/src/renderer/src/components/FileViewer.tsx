/* ------------------------------------------------------------------ */
/*  FileViewer — Monaco-based code viewer for changed files             */
/*  Shows file tree + code preview when a file is selected              */
/* ------------------------------------------------------------------ */
import { useCallback, useEffect, useState } from "react";
import Editor from "@monaco-editor/react";
import { API_BASE, readJson } from "../api";

/* ---- Types ---- */
interface FileViewerProps {
  taskId: string;
  filesByAgent: Record<string, string[]>;
  allFiles: string[];
}

interface FileContent {
  path: string;
  content: string;
  language: string;
}

/* ---- Language detection ---- */
const EXT_LANG: Record<string, string> = {
  ts: "typescript", tsx: "typescript", js: "javascript", jsx: "javascript",
  py: "python", rs: "rust", go: "go", rb: "ruby",
  sql: "sql", json: "json", yaml: "yaml", yml: "yaml",
  md: "markdown", html: "html", css: "css", scss: "scss",
  sh: "shell", bash: "shell", zsh: "shell",
  toml: "toml", xml: "xml", java: "java", kt: "kotlin",
  swift: "swift", c: "c", cpp: "cpp", h: "c", hpp: "cpp",
  dockerfile: "dockerfile",
};

function detectLanguage(path: string): string {
  const name = path.split("/").pop()?.toLowerCase() || "";
  if (name === "dockerfile") return "dockerfile";
  if (name === "makefile") return "makefile";
  const ext = name.split(".").pop() || "";
  return EXT_LANG[ext] || "plaintext";
}

/* Role color helpers */
const ROLE_COLORS: Record<string, string> = {
  planner: "text-violet-600", lead: "text-purple-600", coder: "text-sky-600",
  reviewer: "text-emerald-600", qa: "text-amber-600", security: "text-rose-600",
  devops: "text-indigo-600", sre: "text-cyan-600", docs: "text-stone-500",
};
const roleColor = (r: string) => ROLE_COLORS[r.toLowerCase()] ?? "text-[var(--ui-text-muted)]";

/* File icon by extension */
function fileIcon(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() || "";
  if (["ts", "tsx"].includes(ext)) return "\uD83D\uDCD8"; // blue book
  if (["js", "jsx"].includes(ext)) return "\uD83D\uDCD9"; // orange book
  if (["py"].includes(ext)) return "\uD83D\uDC0D"; // snake
  if (["sql"].includes(ext)) return "\uD83D\uDDC3\uFE0F"; // file cabinet
  if (["json", "yaml", "yml", "toml"].includes(ext)) return "\u2699\uFE0F"; // gear
  if (["md"].includes(ext)) return "\uD83D\uDCDD"; // memo
  if (["css", "scss"].includes(ext)) return "\uD83C\uDFA8"; // palette
  return "\uD83D\uDCC4"; // document
}

/* ================================================================== */
/*  FileViewer component                                               */
/* ================================================================== */
export default function FileViewer({ taskId, filesByAgent, allFiles }: FileViewerProps) {
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<FileContent | null>(null);
  const [fileError, setFileError] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set(Object.keys(filesByAgent)));

  /* Fetch file content from backend */
  const fetchFileContent = useCallback(async (path: string) => {
    setLoading(true);
    setFileContent(null);
    setFileError("");

    const res = await readJson<{ content: string; path: string; error?: string }>(
      `${API_BASE}/v1/tasks/${taskId}/files/${encodeURIComponent(path)}`
    );

    if (res?.content && res.content.length > 0) {
      setFileContent({ path, content: res.content, language: detectLanguage(path) });
    } else {
      setFileError(res?.error || "File content is unavailable for this run. The file path is recorded, but content was not persisted.");
    }
    setLoading(false);
  }, [taskId]);

  /* Load content when file is selected */
  useEffect(() => {
    if (selectedFile) {
      void fetchFileContent(selectedFile);
    }
  }, [selectedFile, fetchFileContent]);

  const toggleAgent = (agent: string) => {
    setExpandedAgents((prev) => {
      const next = new Set(prev);
      if (next.has(agent)) next.delete(agent);
      else next.add(agent);
      return next;
    });
  };

  const hasFiles = allFiles.length > 0;

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* File tree section */}
      <div className={`${selectedFile ? "max-h-[180px]" : "flex-1"} overflow-y-auto`}>
        {!hasFiles && (
          <p className="text-xs text-[var(--ui-text-muted)] py-6 text-center">No files changed yet</p>
        )}
        {Object.entries(filesByAgent).map(([agent, agentFiles]) => (
          <div key={agent}>
            <button
              type="button"
              className="flex items-center gap-2 w-full px-3 py-1.5 hover:bg-[rgba(0,0,0,0.02)] transition-colors"
              onClick={() => toggleAgent(agent)}
            >
              <span className="text-[10px] text-[var(--ui-text-subtle)]">
                {expandedAgents.has(agent) ? "\u25BC" : "\u25B6"}
              </span>
              <span className={`text-[10px] font-semibold uppercase tracking-wider ${roleColor(agent)}`}>
                {agent}
              </span>
              <span className="text-[10px] text-[var(--ui-text-subtle)] ml-auto">{agentFiles.length}</span>
            </button>
            {expandedAgents.has(agent) && agentFiles.map((f) => {
              const shortName = f.split("/").pop() || f;
              const dir = f.includes("/") ? f.slice(0, f.lastIndexOf("/")) : "";
              return (
                <button
                  key={f}
                  type="button"
                  onClick={() => setSelectedFile(f)}
                  className={`file-tree-item w-full pl-7 ${selectedFile === f ? "active" : ""}`}
                >
                  <span className="text-[11px]">{fileIcon(f)}</span>
                  <div className="flex-1 min-w-0 text-left">
                    <span className="text-xs font-mono truncate block">{shortName}</span>
                    {dir && <span className="text-[10px] text-[var(--ui-text-subtle)] font-mono truncate block">{dir}/</span>}
                  </div>
                  <span className="text-emerald-500 text-[10px] flex-shrink-0">+</span>
                </button>
              );
            })}
          </div>
        ))}
      </div>

      {/* Monaco editor */}
      {selectedFile && (
        <div className="flex-1 min-h-0 flex flex-col border-t border-[var(--ui-border)]">
          <div className="flex items-center gap-2 px-3 py-1.5 bg-[rgba(0,0,0,0.015)]">
            <span className="text-[11px]">{fileIcon(selectedFile)}</span>
            <span className="text-[11px] font-mono text-[var(--ui-text-secondary)] truncate flex-1">
              {selectedFile.split("/").pop()}
            </span>
            <button
              type="button"
              onClick={() => { setSelectedFile(null); setFileContent(null); }}
              className="text-[10px] text-[var(--ui-text-subtle)] hover:text-[var(--ui-text-muted)] transition px-1.5 py-0.5 rounded hover:bg-[rgba(0,0,0,0.03)]"
            >
              Close
            </button>
          </div>

          <div className="flex-1 min-h-0">
            {loading ? (
              <div className="flex items-center justify-center h-full">
                <div className="animate-spin h-4 w-4 border-2 border-[var(--ui-text)] border-t-transparent rounded-full" />
              </div>
            ) : fileContent ? (
              <Editor
                height="100%"
                language={fileContent.language}
                value={fileContent.content}
                theme="vs-dark"
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  fontSize: 12,
                  lineNumbers: "on",
                  scrollBeyondLastLine: false,
                  wordWrap: "on",
                  renderLineHighlight: "none",
                  overviewRulerBorder: false,
                  hideCursorInOverviewRuler: true,
                  scrollbar: {
                    vertical: "hidden",
                    horizontal: "auto",
                    verticalScrollbarSize: 4,
                  },
                  padding: { top: 8, bottom: 8 },
                  contextmenu: false,
                  folding: true,
                  links: false,
                }}
              />
            ) : fileError ? (
              <div className="flex h-full items-start justify-start p-3">
                <div className="w-full rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
                  <p className="text-[11px] font-semibold uppercase tracking-wider text-amber-700">Evidence unavailable</p>
                  <p className="mt-1 text-xs text-amber-600">{fileError}</p>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
