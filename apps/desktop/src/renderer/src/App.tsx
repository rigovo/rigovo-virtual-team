import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  Route, AuthSession, InboxTask, ApprovalItem,
  EngineStatus, Project, TaskDetail as TaskDetailType, ControlStatePayload
} from "./types";

import { API_BASE, readJson, isApiHealthy, isUuid } from "./api";
import { fallbackInbox, fallbackApprovals, demoTaskDetails } from "./defaults";

/* ---- Components ---- */
import AuthScreen from "./components/AuthScreen";
import Sidebar from "./components/Sidebar";
import EmptyState from "./components/EmptyState";
import TaskInput, { type TaskInputHandle } from "./components/TaskInput";
import TaskDetail from "./components/TaskDetail";
import Settings from "./components/Settings";
import { UI_LABELS, buildPermissionLabel, type WorkspaceControls } from "./ui/tokens";
import AutomationsPage from "./components/pages/AutomationsPage";
import SkillsPage from "./components/pages/SkillsPage";
import DocumentsPage from "./components/pages/DocumentsPage";
import LanguagePage from "./components/pages/LanguagePage";

/* ---- Electron API ---- */
const electronAPI = typeof window !== "undefined" ? window.electronAPI : undefined;
type WorkspacePage = "threads" | "automations" | "skills" | "documents" | "language" | "settings";
type SettingsSnapshot = {
  agent_models?: Record<string, string>;
  agent_tools?: Record<string, string[]>;
  default_model?: string;
  plugins_policy?: { min_trust_level?: string };
};

/* ---- Utility: derive a short label from a filesystem path ---- */
function pathLabel(p: string): string {
  if (!p) return "";
  const parts = p.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts[parts.length - 1] || p;
}

/* ---- Utility: derive repo name from git URL ---- */
function repoNameFromUrl(url: string): string {
  try {
    const clean = url.trim().replace(/\.git\s*$/, "");
    const parts = clean.split(/[/\\]/).filter(Boolean);
    return parts[parts.length - 1] || "repo";
  } catch {
    return "repo";
  }
}

/* ================================================================== */
/*  WorkspaceStrip — shown above TaskInput in new-thread mode         */
/* ================================================================== */
interface WorkspaceStripProps {
  workspacePath: string;
  workspaceLabel: string;
  onChangeFolder: () => void;
  onCloneRepo: () => void;
}

function WorkspaceStrip({ workspacePath, workspaceLabel, onChangeFolder, onCloneRepo }: WorkspaceStripProps): JSX.Element {
  const displayLabel = workspaceLabel || (workspacePath ? pathLabel(workspacePath) : "");
  return (
    <div className="workspace-strip" role="region" aria-label="Workspace context">
      <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" width="12" height="12" className="ws-icon" aria-hidden="true">
        <path d="M1.5 4.5h11v7a.5.5 0 0 1-.5.5h-10a.5.5 0 0 1-.5-.5v-7zM1.5 4.5l1-2H6l1 1.5h4.5" />
      </svg>
      <span className="ws-path" title={workspacePath || undefined}>
        {displayLabel || <span className="ws-path-empty">No workspace</span>}
      </span>
      <div className="ws-actions">
        <button type="button" className="ws-btn" onClick={onChangeFolder} title="Select local folder">
          <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" width="11" height="11" aria-hidden="true">
            <path d="M1.5 4.5h11v7a.5.5 0 0 1-.5.5h-10a.5.5 0 0 1-.5-.5v-7zM1.5 4.5l1-2H6l1 1.5h4.5" />
          </svg>
          Open folder
        </button>
        <button type="button" className="ws-btn ws-btn-clone" onClick={onCloneRepo} title="Clone a git repository">
          <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" width="11" height="11" aria-hidden="true">
            <circle cx="3" cy="3" r="1.5" />
            <circle cx="11" cy="3" r="1.5" />
            <circle cx="7" cy="11" r="1.5" />
            <path d="M3 4.5v1.5a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2V4.5" />
            <path d="M7 7.5V9.5" />
          </svg>
          Clone repo
        </button>
      </div>
    </div>
  );
}

/* ================================================================== */
/*  CloneModal — git clone URL + destination picker                    */
/* ================================================================== */
interface CloneModalProps {
  onClose: () => void;
  onCloned: (path: string, label: string) => void;
}

function CloneModal({ onClose, onCloned }: CloneModalProps): JSX.Element {
  const [url, setUrl] = useState("");
  const [destParent, setDestParent] = useState("");
  const [cloning, setCloning] = useState(false);
  const [error, setError] = useState("");
  const urlInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => { urlInputRef.current?.focus(); }, []);

  // Close on Escape
  useEffect(() => {
    const handler = (e: globalThis.KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const repoName = repoNameFromUrl(url);
  const destPath = destParent ? `${destParent}/${repoName}` : "";

  const handlePickDest = async () => {
    const dir = electronAPI?.pickCloneDest ? await electronAPI.pickCloneDest() : window.prompt("Enter destination parent directory:");
    if (dir) setDestParent(dir);
  };

  const handleClone = async () => {
    const trimUrl = url.trim();
    if (!trimUrl) { setError("Enter a git URL."); return; }
    if (!trimUrl.toLowerCase().startsWith("http")) { setError("URL should start with http:// or https://"); return; }
    if (!destParent) { setError("Choose a destination folder."); return; }
    setCloning(true);
    setError("");
    const dest = `${destParent}/${repoName}`;
    try {
      if (electronAPI?.gitClone) {
        const result = await electronAPI.gitClone(trimUrl, dest);
        onCloned(result, repoName);
      } else {
        // Web preview fallback — simulate success
        await new Promise((res) => window.setTimeout(res, 800));
        onCloned(dest, repoName);
      }
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "Clone failed";
      setError(errMsg);
      // Auto-clear error after 4s
      window.setTimeout(() => setError(""), 4000);
    }
    setCloning(false);
  };

  return (
    <div className="clone-modal-overlay" role="dialog" aria-modal="true" aria-label="Clone repository">
      <div className="clone-modal">
        <div className="clone-modal-header">
          <span className="clone-modal-title">Clone a repository</span>
          <button type="button" className="clone-modal-close" onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" width="12" height="12">
              <path d="M2 2l8 8M10 2l-8 8" />
            </svg>
          </button>
        </div>

        <div className="clone-modal-body">
          <label className="clone-field-label" htmlFor="clone-url">Repository URL</label>
          <input
            id="clone-url"
            ref={urlInputRef}
            className="clone-input"
            type="url"
            placeholder="https://github.com/owner/repo.git"
            value={url}
            onChange={(e) => { setUrl(e.target.value); setError(""); }}
            disabled={cloning}
          />

          <label className="clone-field-label" style={{ marginTop: 12 }}>Destination</label>
          <div className="clone-dest-row">
            <button type="button" className="clone-dest-btn" onClick={() => void handlePickDest()} disabled={cloning}>
              <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" width="11" height="11" aria-hidden="true">
                <path d="M1.5 4.5h11v7a.5.5 0 0 1-.5.5h-10a.5.5 0 0 1-.5-.5v-7zM1.5 4.5l1-2H6l1 1.5h4.5" />
              </svg>
              Choose folder
            </button>
            {destPath ? (
              <span className="clone-dest-preview" title={destPath}>{destPath}</span>
            ) : (
              <span className="clone-dest-placeholder">No folder selected</span>
            )}
          </div>
        </div>

        {error && <div className="clone-error">{error}</div>}

        <div className="clone-modal-footer">
          <button type="button" className="clone-cancel-btn" onClick={onClose} disabled={cloning}>
            Cancel
          </button>
          <button
            type="button"
            className="clone-action-btn"
            onClick={() => void handleClone()}
            disabled={cloning || !url.trim() || !destParent}
          >
            {cloning ? (
              <>
                <span className="clone-spinner" aria-hidden="true" />
                Cloning…
              </>
            ) : "Clone"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ================================================================== */
/*  App — thin shell: state + effects + component composition          */
/* ================================================================== */
export default function App(): JSX.Element {
  const parsedApi = useMemo(() => {
    try { const u = new URL(API_BASE); return { host: u.hostname, port: Number(u.port || "80") }; }
    catch { return { host: "127.0.0.1", port: 8787 }; }
  }, []);

  /* ---- State ---- */
  const [route, setRoute] = useState<Route>("auth");
  const [authSession, setAuthSession] = useState<AuthSession | null>(null);
  const [inbox, setInbox] = useState<InboxTask[]>(fallbackInbox);
  const [approvals, setApprovals] = useState<ApprovalItem[]>(fallbackApprovals);
  const [selected, setSelected] = useState("");
  const [, setMode] = useState<"live" | "fallback">("fallback");
  const [engine, setEngine] = useState<EngineStatus>({ running: false, pid: null, apiUrl: API_BASE });
  const [engineError, setEngineError] = useState<string>("");
  const [apiReachable, setApiReachable] = useState<boolean | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProject, setActiveProject] = useState<Project | null>(null);
  const [projectFiles, setProjectFiles] = useState<string[]>([]);
  const [projectLoading, setProjectLoading] = useState(false);
  const [taskInput, setTaskInput] = useState("");
  const [taskCreating, setTaskCreating] = useState(false);
  const [taskMsg, setTaskMsg] = useState("");
  const taskInputRef = useRef<TaskInputHandle>(null);
  const [taskDetail, setTaskDetail] = useState<TaskDetailType | null>(null);
  const [onboardingMsg, setOnboardingMsg] = useState("");
  const [actionMsg, setActionMsg] = useState("");
  const [showSettings, setShowSettings] = useState(false);
  const [workspacePage, setWorkspacePage] = useState<WorkspacePage>("threads");
  const [workspaceMeta, setWorkspaceMeta] = useState<{ org: string; users: number }>({ org: "", users: 0 });
  const [controlState, setControlState] = useState<ControlStatePayload | null>(null);
  const [settingsSnapshot, setSettingsSnapshot] = useState<SettingsSnapshot | null>(null);
  const [uiLanguage, setUiLanguage] = useState("en-US");
  const [newThreadMode, setNewThreadMode] = useState(true);
  const [taskTier, setTaskTier] = useState<"auto" | "notify" | "approve">("auto");
  const [workspaceControls, setWorkspaceControls] = useState<WorkspaceControls>({
    runtime: UI_LABELS.runtimeLocal,
    permissions: UI_LABELS.defaultPermissions,
    model: "Default model",
    effort: UI_LABELS.defaultEffort,
  });

  /* ---- Workspace (folder / git clone) for new tasks ---- */
  const [taskWorkspacePath, setTaskWorkspacePath] = useState("");
  const [taskWorkspaceLabel, setTaskWorkspaceLabel] = useState("");
  const [cloneModalOpen, setCloneModalOpen] = useState(false);

  /* ---- Engine management ---- */
  const startEngine = useCallback(async (projectDir?: string): Promise<void> => {
    if (!electronAPI) return;
    try {
      setEngineError("");
      const s = await electronAPI.startEngine({ host: parsedApi.host, port: parsedApi.port, projectDir: projectDir || "." });
      setEngine(s);
    } catch (err) {
      setEngineError(err instanceof Error ? err.message : String(err));
    }
  }, [parsedApi.host, parsedApi.port]);

  useEffect(() => {
    if (!electronAPI) return;
    void (async () => {
      try {
        const s = await electronAPI.engineStatus();
        setEngine(s);
        // Only auto-start if engine isn't running AND the API isn't reachable
        // (avoids conflicting with an externally-started API from e2e_desktop.sh)
        if (!s.running) {
          const alreadyHealthy = await isApiHealthy(API_BASE);
          if (!alreadyHealthy) await startEngine();
        }
      } catch (err) {
        setEngineError(err instanceof Error ? err.message : String(err));
      }
    })();
  }, [startEngine]);

  // Poll engine last-error when engine is not running, so startup failures surface automatically
  useEffect(() => {
    if (!electronAPI?.engineLastError) return;
    let cancelled = false;
    const poll = async (): Promise<void> => {
      if (cancelled) return;
      try {
        const s = await electronAPI!.engineStatus();
        setEngine(s);
        if (!s.running) {
          const err = await electronAPI!.engineLastError!();
          if (!cancelled) setEngineError(err || "");
        } else {
          if (!cancelled) setEngineError("");
        }
      } catch { /* best-effort */ }
    };
    const id = window.setInterval(() => { void poll(); }, 5000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  /* ---- Boot — auth check, fallback to demo mode if API down ---- */
  useEffect(() => {
    const stored = window.localStorage.getItem("rigovo.ui.language");
    const fallback = navigator.language || "en-US";
    setUiLanguage(stored || fallback);
  }, []);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
      const healthy = await isApiHealthy(API_BASE);
      if (!active) return;
      setApiReachable(healthy);

      if (!healthy) {
        // API unreachable — stay on auth screen, show a warning so the user
        // knows the engine is not running (do NOT auto-login as demo user).
        setRoute("auth");
        return;
      }

      const session = await readJson<AuthSession>(`${API_BASE}/v1/auth/session`);
      const projectList = await readJson<Project[]>(`${API_BASE}/v1/projects`);
      const controlStatePayload = await readJson<ControlStatePayload>(`${API_BASE}/v1/control/state`);
      const auth = session ?? { signed_in: false, email: "", full_name: "", first_name: "", last_name: "", role: "", organization_id: "", organization_name: "", workspace: { name: "", slug: "", admin_email: "", region: "" } };
      if (!active) return;
      setAuthSession(auth.signed_in ? auth : null);
      setControlState(controlStatePayload || null);
      // Apply saved governance tier — so new tasks default to what the user configured
      const savedTier = controlStatePayload?.policy?.defaultTier;
      if (savedTier === "auto" || savedTier === "notify" || savedTier === "approve") {
        setTaskTier(savedTier);
      }
      setWorkspaceMeta({
        org: auth.organization_name || auth.workspace?.name || controlStatePayload?.workspace?.workspaceName || controlStatePayload?.workspace?.workspaceSlug || "",
        users: Array.isArray(controlStatePayload?.personas) ? controlStatePayload.personas.length : 0,
      });
      if (projectList?.length) { setProjects(projectList); setActiveProject(projectList[0]); }
      setRoute(auth.signed_in ? "control" : "auth");
      } catch { /* bootstrap fetch failed — stay on auth screen */ }
    })();
    return () => { active = false; };
  }, []);

  /* ---- Polling: inbox + approvals ---- */
  useEffect(() => {
    if (route !== "control") return;
    let active = true;
    const load = async () => {
      if (electronAPI) { try { setEngine(await electronAPI.engineStatus()); } catch { /* swallow */ } }
      const [tasks, queue] = await Promise.all([
        readJson<InboxTask[]>(`${API_BASE}/v1/ui/inbox`),
        readJson<ApprovalItem[]>(`${API_BASE}/v1/ui/approvals`),
      ]);
      if (!active) return;
      setApiReachable(Boolean(tasks || queue));
      setMode(Boolean(tasks || queue) ? "live" : "fallback");
      if (tasks) {
        // Merge: keep optimistic entries that haven't appeared from server yet
        setInbox((prev) => {
          const serverIds = new Set(tasks.map((t) => t.id));
          const optimistic = prev.filter((t) => !serverIds.has(t.id) && t.updatedAt === "just now");
          return [...optimistic, ...tasks];
        });
        setSelected((p) => {
          if (newThreadMode || workspacePage !== "threads") return "";
          if (p) return p; // keep current selection stable
          // On first load, only auto-select if there's an active (non-terminal) task
          const activeTask = tasks.find((t) => {
            const s = t.status.toLowerCase();
            return !s.includes("complete") && !s.includes("fail") && !s.includes("reject");
          });
          return activeTask ? activeTask.id : "";
        });
      }
      if (queue) setApprovals(queue);
    };
    void load();
    const id = window.setInterval(() => { void load(); }, 4000);
    return () => { active = false; window.clearInterval(id); };
  }, [route, newThreadMode, workspacePage]);

  /* ---- Workspace controls (mode, permission profile, model) ---- */
  useEffect(() => {
    if (route !== "control") return;
    let active = true;
    void (async () => {
      try {
        const settings = await readJson<SettingsSnapshot>(`${API_BASE}/v1/settings`);

        // Always show "Local" when running in Electron — we never use a remote cloud runtime
        const runtime: string = electronAPI ? UI_LABELS.runtimeLocal : UI_LABELS.runtimeCloud;

        if (!active) return;
        setSettingsSnapshot(settings || null);
        setWorkspaceControls({
          runtime,
          permissions: buildPermissionLabel(settings?.plugins_policy?.min_trust_level),
          model: settings?.default_model || "Default model",
          effort: UI_LABELS.defaultEffort,
        });
      } catch { /* settings fetch failed — use defaults */ }
    })();
    return () => { active = false; };
  }, [route]);

  /* ---- Poll task detail (or use demo data) ---- */
  useEffect(() => {
    if (!selected) { setTaskDetail(null); return; }

    // Demo task — use static demo data
    if (selected.startsWith("demo-")) {
      const demo = demoTaskDetails[selected] ?? null;
      setTaskDetail(demo);
      return;
    }

    if (!isUuid(selected)) { setTaskDetail(null); return; }
    let active = true;
    let fast = true; // fast polling initially (task might not be in DB yet)
    const f = async () => {
      const d = await readJson<TaskDetailType>(`${API_BASE}/v1/tasks/${selected}/detail`);
      if (active && d) { setTaskDetail(d); fast = false; } // got data, slow down
    };
    void f();
    // Start with 1.5s polling (for newly created tasks), switch to 5s once data arrives
    const id = window.setInterval(() => { void f(); }, fast ? 1500 : 5000);
    // Also set up the slower interval after 10s regardless
    const slowId = window.setTimeout(() => {
      if (!active) return;
      window.clearInterval(id);
      const id2 = window.setInterval(() => { void f(); }, 5000);
      // store for cleanup
      cleanupIds.push(id2);
    }, 10000);
    const cleanupIds: number[] = [];
    return () => { active = false; window.clearInterval(id); window.clearTimeout(slowId); cleanupIds.forEach((i) => window.clearInterval(i)); };
  }, [selected]);

  /* ---- Auth flow ---- */
  const authPollRef = useRef<number | null>(null);
  const [authWaiting, setAuthWaiting] = useState(false);
  const stopAuthPolling = useCallback(() => { if (authPollRef.current) { window.clearInterval(authPollRef.current); authPollRef.current = null; } setAuthWaiting(false); }, []);
  const authStartTimeRef = useRef<number>(0);
  const AUTH_TIMEOUT_MS = 120_000; // 2 minutes max wait
  const startAuthPolling = useCallback(() => {
    stopAuthPolling(); setAuthWaiting(true); setOnboardingMsg("");
    authStartTimeRef.current = Date.now();
    authPollRef.current = window.setInterval(async () => {
      // Timeout: stop polling after 2 minutes and show error
      if (Date.now() - authStartTimeRef.current > AUTH_TIMEOUT_MS) {
        stopAuthPolling();
        setOnboardingMsg("Sign-in timed out. Please try again.");
        return;
      }
      try {
        const s = await readJson<AuthSession>(`${API_BASE}/v1/auth/session`);
        if (s?.signed_in) { stopAuthPolling(); setOnboardingMsg(""); setAuthSession(s); setRoute("control"); }
      } catch { /* swallow */ }
    }, 1500);
  }, [stopAuthPolling]);
  useEffect(() => () => stopAuthPolling(), [stopAuthPolling]);

  const onSignIn = async () => {
    const ok = await isApiHealthy(API_BASE); setApiReachable(ok);
    if (!ok) { setOnboardingMsg(`Cannot reach API at ${API_BASE}.`); return; }
    const res = await readJson<{ url: string }>(`${API_BASE}/v1/auth/url`);
    if (!res?.url) { setOnboardingMsg("Failed to start auth."); return; }
    if (electronAPI?.openExternal) await electronAPI.openExternal(res.url); else window.open(res.url, "_blank");
    setOnboardingMsg(""); startAuthPolling();
  };
  const signOut = () => { void fetch(`${API_BASE}/v1/auth/logout`, { method: "POST" }); setAuthSession(null); setRoute("auth"); };

  /* ---- Open folder (optional) ---- */
  const openProject = async () => {
    setProjectLoading(true);
    let folderPath: string | null = null;
    try {
      folderPath = electronAPI?.openFolder ? await electronAPI.openFolder() : window.prompt("Enter project folder path:");
    } catch (err) {
      setOnboardingMsg(`Failed to open folder: ${err instanceof Error ? err.message : String(err)}`);
      setProjectLoading(false);
      return;
    }
    if (!folderPath) { setProjectLoading(false); return; }
    try {
      const res = await fetch(`${API_BASE}/v1/projects`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: folderPath }) });
      if (res.ok) {
        const p: Project = await res.json();
        setProjects((prev) => [...prev.filter((x) => x.id !== p.id), p]);
        setActiveProject(p);
        await startEngine(folderPath);
      } else {
        const err = await res.json().catch(() => ({ detail: "Unknown error" }));
        setOnboardingMsg(`Failed to open project: ${err.detail || res.statusText}`);
      }
    } catch (err) {
      setOnboardingMsg(`Failed to register project: ${err instanceof Error ? err.message : String(err)}`);
    }
    setProjectLoading(false);
  };

  /* ---- Handle workspace folder selection for new tasks ---- */
  const handleChangeWorkspace = async () => {
    try {
      const folderPath = electronAPI?.openFolder ? await electronAPI.openFolder() : window.prompt("Enter workspace folder path:");
      if (!folderPath) {
        setTaskMsg("");
        return;
      }
      setTaskWorkspacePath(folderPath);
      setTaskWorkspaceLabel(pathLabel(folderPath));
      setTaskMsg(`Workspace set to ${pathLabel(folderPath)}`);
      window.setTimeout(() => setTaskMsg(""), 2000);
    } catch (err) {
      setTaskMsg(`Failed to open folder: ${err instanceof Error ? err.message : String(err)}`);
      window.setTimeout(() => setTaskMsg(""), 3000);
    }
  };

  /* ---- Rename a thread ---- */
  const renameTask = useCallback(async (id: string, title: string) => {
    // Optimistic update
    setInbox((prev) => prev.map((t) => t.id === id ? { ...t, title } : t));
    try {
      await fetch(`${API_BASE}/v1/tasks/${id}/rename`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
    } catch {
      // Non-fatal — the optimistic label is shown; will be reverted on next poll
    }
  }, []);

  /* ---- Create task ---- */
  const createTask = async (e: FormEvent) => {
    e.preventDefault();
    const desc = taskInput.trim();
    if (!desc) return;
    setTaskCreating(true); setTaskMsg("");
    try {
      const body: Record<string, unknown> = {
        description: desc,
        tier: taskTier,
        project_id: activeProject?.id ?? "",
      };
      if (taskWorkspacePath) {
        body.workspace_path = taskWorkspacePath;
        body.workspace_label = taskWorkspaceLabel || pathLabel(taskWorkspacePath);
      }
      const res = await fetch(`${API_BASE}/v1/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        const d = await res.json();
        const taskId = d.task_id as string;
        // Optimistic: add task to inbox immediately so UI shows it before next poll
        const optimisticTask: InboxTask = {
          id: taskId,
          title: desc,
          source: "manual",
          tier: taskTier,
          status: "classifying",
          team: "default",
          updatedAt: "just now",
          workspacePath: taskWorkspacePath || undefined,
          workspaceLabel: taskWorkspaceLabel || undefined,
        };
        setInbox((prev) => [optimisticTask, ...prev.filter((t) => t.id !== taskId)]);
        setNewThreadMode(false);
        setWorkspacePage("threads");
        setSelected(taskId);
        setTaskInput("");
        setTaskMsg("Task created — agents starting...");
        window.setTimeout(() => setTaskMsg(""), 4000);
      } else {
        const err = await res.json().catch(() => ({ detail: "Unknown" }));
        setTaskMsg(`Failed: ${err.detail || res.statusText}`);
      }
    } catch {
      // Demo mode — create a local task so user sees something happen
      const demoId = `demo-local-${Date.now()}`;
      const newTask: InboxTask = {
        id: demoId,
        title: desc,
        source: "manual",
        tier: "auto",
        status: "classifying",
        team: "default",
        updatedAt: "just now",
        workspacePath: taskWorkspacePath || undefined,
        workspaceLabel: taskWorkspaceLabel || undefined,
      };
      setInbox((prev) => [newTask, ...prev]);
      setNewThreadMode(false);
      setWorkspacePage("threads");
      setSelected(demoId);
      setTaskInput("");
      setTaskMsg("Task created (demo mode — engine not running)");
      window.setTimeout(() => setTaskMsg(""), 4000);
    }
    setTaskCreating(false);
  };

  /* ---- Task actions ---- */
  const act = async (path: string, body: Record<string, unknown>) => {
    setActionMsg("...");
    try { const r = await fetch(`${API_BASE}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); setActionMsg(r.ok ? "Done" : "Failed"); }
    catch { setActionMsg("Failed"); }
    window.setTimeout(() => setActionMsg(""), 2200);
  };

  const executeCommand = useCallback((input: string): boolean => {
    if (!input.startsWith("/")) return false;
    const command = input.slice(1).split(/\s+/)[0].toLowerCase();
    switch (command) {
      case "new":
      case "new-thread":
        setShowSettings(false);
        setNewThreadMode(true);
        setWorkspacePage("threads");
        setSelected("");
        setTaskInput("");
        taskInputRef.current?.focus();
        setTaskMsg("New thread ready.");
        window.setTimeout(() => setTaskMsg(""), 1800);
        return true;
      case "settings":
        setShowSettings(true);
        setWorkspacePage("settings");
        return true;
      case "skills":
        setShowSettings(false);
        setWorkspacePage("skills");
        setSelected("");
        return true;
      case "automations":
        setShowSettings(false);
        setWorkspacePage("automations");
        setSelected("");
        return true;
      case "documents":
        setShowSettings(false);
        setWorkspacePage("documents");
        setSelected("");
        return true;
      case "language":
        setShowSettings(false);
        setWorkspacePage("language");
        setSelected("");
        return true;
      case "open-folder":
        void openProject();
        return true;
      case "help":
        setTaskMsg("Commands: /new-thread /settings /skills /automations /documents /language /open-folder");
        window.setTimeout(() => setTaskMsg(""), 3500);
        return true;
      default:
        setTaskMsg(`Unknown command: /${command}`);
        window.setTimeout(() => setTaskMsg(""), 2500);
        return true;
    }
  }, [openProject]);

  /* ---- Derived ---- */
  const userName = authSession?.full_name || authSession?.first_name || authSession?.email?.split("@")[0] || "User";
  const userEmail = authSession?.email || "";
  const userInitials = userName.split(" ").map((w) => w[0]).join("").toUpperCase().slice(0, 2);
  const selectedTask = useMemo(() => inbox.find((t) => t.id === selected) ?? null, [inbox, selected]);
  // Load project files when active project changes (for @ mention autocomplete)
  useEffect(() => {
    if (!activeProject?.path || !electronAPI) { setProjectFiles([]); return; }
    void electronAPI.listProjectFiles(activeProject.path).then((files) => {
      setProjectFiles(files);
    }).catch(() => setProjectFiles([]));
  }, [activeProject?.path]);

  const mentionFiles = useMemo(() => {
    const fromSteps = taskDetail?.steps?.flatMap((step) => step.files_changed) ?? [];
    // Merge project files (for new threads) + task-changed files (for active tasks)
    return [...new Set([...projectFiles, ...fromSteps])].sort();
  }, [projectFiles, taskDetail]);
  const availableLanguages = useMemo(() => {
    const languages = Array.from(new Set([...(navigator.languages || []), navigator.language, "en-US"].filter(Boolean)));
    return languages.length ? languages : ["en-US"];
  }, []);

  // Suppress unused warnings for variables used indirectly
  void engine; void projects;

  /* ================================================================ */
  /*  AUTH SCREEN                                                      */
  /* ================================================================ */
  if (route === "auth") {
    return (
      <AuthScreen
        onSignIn={() => void onSignIn()}
        waiting={authWaiting}
        onCancel={stopAuthPolling}
        message={onboardingMsg}
        apiStatus={apiReachable}
      />
    );
  }

  /* ================================================================ */
  /*  MAIN — 2-panel layout                                            */
  /* ================================================================ */
  const pageTitle =
    workspacePage === "settings"   ? "Settings"
    : workspacePage === "automations" ? "Automations"
    : workspacePage === "skills"      ? "Skills"
    : workspacePage === "documents"   ? "Documents"
    : workspacePage === "language"    ? "Language"
    : selectedTask                    ? selectedTask.title
    : "New thread";

  return (
    <div className="shell">
      <Sidebar
        userName={userName}
        userEmail={userEmail}
        userInitials={userInitials}
        organizationName={workspaceMeta.org}
        totalUsers={workspaceMeta.users}
        inbox={inbox}
        selected={selected}
        activeView={workspacePage}
        onSelect={(id) => {
          setShowSettings(false);
          setNewThreadMode(false);
          setWorkspacePage("threads");
          setSelected(id);
        }}
        onNewTask={() => {
          setShowSettings(false);
          setNewThreadMode(true);
          setWorkspacePage("threads");
          setSelected("");
          setTaskInput("");
          taskInputRef.current?.focus();
        }}
        onOpenFolder={() => void openProject()}
        activeProject={activeProject}
        projectLoading={projectLoading}
        onSignOut={signOut}
        apiReachable={apiReachable}
        onOpenSettings={() => { setShowSettings(true); setWorkspacePage("settings"); }}
        onOpenAutomations={() => { setShowSettings(false); setNewThreadMode(false); setWorkspacePage("automations"); setSelected(""); }}
        onOpenSkills={() => { setShowSettings(false); setNewThreadMode(false); setWorkspacePage("skills"); setSelected(""); }}
        onOpenDocuments={() => { setShowSettings(false); setNewThreadMode(false); setWorkspacePage("documents"); setSelected(""); }}
        onOpenLanguage={() => { setShowSettings(false); setNewThreadMode(false); setWorkspacePage("language"); setSelected(""); }}
        onRenameTask={(id, title) => void renameTask(id, title)}
      />

      <main className="main-panel">
        {/* Engine error banner — shown when engine failed to start */}
        {engineError && !engine.running && (
          <div className="engine-error-banner" role="alert">
            <span className="engine-error-icon">⚠</span>
            <span className="engine-error-text">Engine offline: {engineError.split("\n")[0]}</span>
            <button
              className="engine-error-retry"
              onClick={() => { void startEngine(activeProject?.path); }}
              aria-label="Retry engine start"
            >
              Retry
            </button>
            <button
              className="engine-error-dismiss"
              onClick={() => setEngineError("")}
              aria-label="Dismiss error"
            >
              ✕
            </button>
          </div>
        )}

        {/* Drag region — minimal header */}
        <div className="panel-header">
          <span className="panel-header-title">{pageTitle}</span>
        </div>

        {showSettings || workspacePage === "settings" ? (
          <div className="content-area flush">
            <Settings onBack={() => { setShowSettings(false); setWorkspacePage("threads"); }} />
          </div>
        ) : workspacePage === "automations" ? (
          <div className="content-area">
            <AutomationsPage inbox={inbox} approvals={approvals} policy={controlState?.policy || null} />
          </div>
        ) : workspacePage === "skills" ? (
          <div className="content-area">
            <SkillsPage
              agentModels={settingsSnapshot?.agent_models || {}}
              agentTools={settingsSnapshot?.agent_tools || {}}
              personas={controlState?.personas || []}
              connectors={controlState?.connectors || []}
            />
          </div>
        ) : workspacePage === "documents" ? (
          <div className="content-area">
            <DocumentsPage
              projectName={activeProject?.name}
              projectPath={activeProject?.path}
              projectLoading={projectLoading}
              onOpenFolder={() => void openProject()}
            />
          </div>
        ) : workspacePage === "language" ? (
          <div className="content-area">
            <LanguagePage
              selectedLanguage={uiLanguage}
              availableLanguages={availableLanguages}
              onSelectLanguage={(language) => {
                setUiLanguage(language);
                window.localStorage.setItem("rigovo.ui.language", language);
              }}
            />
          </div>
        ) : (
          <>
            {/* Scrollable content zone */}
            <div className="content-area">
              {!selectedTask && (
                <EmptyState onSelectExample={(text) => { setTaskInput(text); taskInputRef.current?.focus(); }} />
              )}

              {selectedTask && (
                <TaskDetail
                  task={selectedTask}
                  detail={taskDetail}
                  onAction={act}
                  actionMsg={actionMsg}
                  projectPath={activeProject?.path}
                  onOpenInEditor={(url) => electronAPI?.openExternal(url)}
                />
              )}
            </div>

            {/* Workspace context strip — only in new-thread mode */}
            {newThreadMode && (
              <WorkspaceStrip
                workspacePath={taskWorkspacePath}
                workspaceLabel={taskWorkspaceLabel}
                onChangeFolder={() => void handleChangeWorkspace()}
                onCloneRepo={() => setCloneModalOpen(true)}
              />
            )}

            {/* Fixed input dock — always at bottom, no scroll */}
            <TaskInput
              ref={taskInputRef}
              value={taskInput}
              onChange={setTaskInput}
              onSubmit={(e) => void createTask(e)}
              onExecuteCommand={executeCommand}
              creating={taskCreating}
              message={taskMsg}
              onDismissMessage={() => setTaskMsg("")}
              apiReachable={apiReachable}
              runtimeLabel={workspaceControls.runtime}
              permissionsLabel={workspaceControls.permissions}
              modelLabel={workspaceControls.model}
              effortLabel={workspaceControls.effort}
              onOpenSettings={() => { setShowSettings(true); setWorkspacePage("settings"); }}
              onAddFiles={() => { void openProject(); }}
              mentionFiles={mentionFiles}
              taskTier={taskTier}
              onTierChange={setTaskTier}
            />
          </>
        )}
      </main>

      {/* Git clone modal — rendered outside main for proper z-index */}
      {cloneModalOpen && (
        <CloneModal
          onClose={() => setCloneModalOpen(false)}
          onCloned={(clonedPath, label) => {
            setTaskWorkspacePath(clonedPath);
            setTaskWorkspaceLabel(label);
            setCloneModalOpen(false);
          }}
        />
      )}
    </div>
  );
}
