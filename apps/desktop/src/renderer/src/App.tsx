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
        if (!s.running) await startEngine();
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
      const healthy = await isApiHealthy(API_BASE);
      if (!active) return;
      setApiReachable(healthy);

      if (!healthy) {
        // Demo mode — skip auth, show UI with demo data immediately
        setAuthSession({ signed_in: true, email: "demo@rigovo.dev", full_name: "Demo User", first_name: "Demo", last_name: "User", role: "admin", organization_id: "demo", organization_name: "Rigovo Demo", workspace: { name: "Demo", slug: "demo", admin_email: "demo@rigovo.dev", region: "local" } });
        setInbox(fallbackInbox);
        setSelected("");
        setNewThreadMode(true);
        setMode("fallback");
        setRoute("control");
        setWorkspacePage("threads");
        return;
      }

      const session = await readJson<AuthSession>(`${API_BASE}/v1/auth/session`);
      const projectList = await readJson<Project[]>(`${API_BASE}/v1/projects`);
      const controlStatePayload = await readJson<ControlStatePayload>(`${API_BASE}/v1/control/state`);
      const auth = session ?? { signed_in: false, email: "", full_name: "", first_name: "", last_name: "", role: "", organization_id: "", organization_name: "", workspace: { name: "", slug: "", admin_email: "", region: "" } };
      if (!active) return;
      setAuthSession(auth.signed_in ? auth : null);
      setControlState(controlStatePayload || null);
      setWorkspaceMeta({
        org: auth.organization_name || auth.workspace?.name || controlStatePayload?.workspace?.workspaceName || controlStatePayload?.workspace?.workspaceSlug || "",
        users: Array.isArray(controlStatePayload?.personas) ? controlStatePayload.personas.length : 0,
      });
      if (projectList?.length) { setProjects(projectList); setActiveProject(projectList[0]); }
      setRoute(auth.signed_in ? "control" : "auth");
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
  const startAuthPolling = useCallback(() => {
    stopAuthPolling(); setAuthWaiting(true);
    authPollRef.current = window.setInterval(async () => {
      try {
        const s = await readJson<AuthSession>(`${API_BASE}/v1/auth/session`);
        if (s?.signed_in) { stopAuthPolling(); setAuthSession(s); setRoute("control"); }
      } catch { /* swallow */ }
    }, 1500);
  }, [stopAuthPolling]);
  useEffect(() => () => stopAuthPolling(), [stopAuthPolling]);

  const onSignIn = async (hint: "sign-in" | "sign-up" = "sign-in") => {
    const ok = await isApiHealthy(API_BASE); setApiReachable(ok);
    if (!ok) { setOnboardingMsg(`Cannot reach API at ${API_BASE}.`); return; }
    const res = await readJson<{ url: string }>(`${API_BASE}/v1/auth/url?screen_hint=${hint}`);
    if (!res?.url) { setOnboardingMsg("Failed to start auth."); return; }
    if (electronAPI?.openExternal) await electronAPI.openExternal(res.url); else window.open(res.url, "_blank");
    setOnboardingMsg(""); startAuthPolling();
  };
  const signOut = () => { void fetch(`${API_BASE}/v1/auth/logout`, { method: "POST" }); setAuthSession(null); setRoute("auth"); };

  /* ---- Open folder (optional) ---- */
  const openProject = async () => {
    setProjectLoading(true);
    const folderPath = electronAPI?.openFolder ? await electronAPI.openFolder() : window.prompt("Enter project folder path:");
    if (!folderPath) { setProjectLoading(false); return; }
    try {
      const res = await fetch(`${API_BASE}/v1/projects`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ path: folderPath }) });
      if (res.ok) {
        const p: Project = await res.json();
        setProjects((prev) => [...prev.filter((x) => x.id !== p.id), p]);
        setActiveProject(p);
        await startEngine(folderPath);
      }
    } catch { /* swallow */ }
    setProjectLoading(false);
  };

  /* ---- Create task ---- */
  const createTask = async (e: FormEvent) => {
    e.preventDefault();
    const desc = taskInput.trim();
    if (!desc) return;
    setTaskCreating(true); setTaskMsg("");
    try {
      const res = await fetch(`${API_BASE}/v1/tasks`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ description: desc, tier: taskTier, project_id: activeProject?.id ?? "" }) });
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
          updatedAt: "just now"
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
      const newTask: InboxTask = { id: demoId, title: desc, source: "manual", tier: "auto", status: "classifying", team: "default", updatedAt: "just now" };
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
        onSignIn={() => void onSignIn("sign-in")}
        onSignUp={() => void onSignIn("sign-up")}
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

        {/* Drag region — minimal header, replaces WorkspaceStrip */}
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
    </div>
  );
}
