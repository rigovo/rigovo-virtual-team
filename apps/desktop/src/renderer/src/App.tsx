import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import type {
  Route, AuthSession, InboxTask, ApprovalItem,
  EngineStatus, Project, TaskDetail as TaskDetailType
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

/* ---- Electron API ---- */
const electronAPI = typeof window !== "undefined" ? window.electronAPI : undefined;

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
  const [apiReachable, setApiReachable] = useState<boolean | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProject, setActiveProject] = useState<Project | null>(null);
  const [projectLoading, setProjectLoading] = useState(false);
  const [taskInput, setTaskInput] = useState("");
  const [taskCreating, setTaskCreating] = useState(false);
  const [taskMsg, setTaskMsg] = useState("");
  const taskInputRef = useRef<TaskInputHandle>(null);
  const [taskDetail, setTaskDetail] = useState<TaskDetailType | null>(null);
  const [onboardingMsg, setOnboardingMsg] = useState("");
  const [actionMsg, setActionMsg] = useState("");
  const [showSettings, setShowSettings] = useState(false);

  /* ---- Engine management ---- */
  const startEngine = useCallback(async (projectDir?: string): Promise<void> => {
    if (!electronAPI) return;
    try { setEngine(await electronAPI.startEngine({ host: parsedApi.host, port: parsedApi.port, projectDir: projectDir || "." })); } catch { /* swallow */ }
  }, [parsedApi.host, parsedApi.port]);

  useEffect(() => {
    if (!electronAPI) return;
    void (async () => { try { const s = await electronAPI.engineStatus(); setEngine(s); if (!s.running) await startEngine(); } catch { /* swallow */ } })();
  }, [startEngine]);

  /* ---- Boot — auth check, fallback to demo mode if API down ---- */
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
        setSelected(fallbackInbox[0]?.id ?? "");
        setMode("fallback");
        setRoute("control");
        return;
      }

      const session = await readJson<AuthSession>(`${API_BASE}/v1/auth/session`);
      const projectList = await readJson<Project[]>(`${API_BASE}/v1/projects`);
      const auth = session ?? { signed_in: false, email: "", full_name: "", first_name: "", last_name: "", role: "", organization_id: "", organization_name: "", workspace: { name: "", slug: "", admin_email: "", region: "" } };
      if (!active) return;
      setAuthSession(auth.signed_in ? auth : null);
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
      const res = await fetch(`${API_BASE}/v1/tasks`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ description: desc }) });
      if (res.ok) {
        const d = await res.json();
        const taskId = d.task_id as string;
        // Optimistic: add task to inbox immediately so UI shows it before next poll
        const optimisticTask: InboxTask = {
          id: taskId,
          title: desc,
          source: "manual",
          tier: "auto",
          status: "classifying",
          team: "default",
          updatedAt: "just now"
        };
        setInbox((prev) => [optimisticTask, ...prev.filter((t) => t.id !== taskId)]);
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

  /* ---- Derived ---- */
  const userName = authSession?.full_name || authSession?.first_name || authSession?.email?.split("@")[0] || "User";
  const userInitials = userName.split(" ").map((w) => w[0]).join("").toUpperCase().slice(0, 2);
  const selectedTask = useMemo(() => inbox.find((t) => t.id === selected) ?? null, [inbox, selected]);

  // Suppress unused warnings for variables used indirectly
  void engine; void approvals; void projects;

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
  return (
    <div className="two-panel">
      <Sidebar
        userName={userName}
        userInitials={userInitials}
        inbox={inbox}
        selected={selected}
        onSelect={(id) => { setShowSettings(false); setSelected(id); }}
        onNewTask={() => { setShowSettings(false); setSelected(""); taskInputRef.current?.focus(); }}
        onOpenFolder={() => void openProject()}
        activeProject={activeProject}
        projectLoading={projectLoading}
        onSignOut={signOut}
        apiReachable={apiReachable}
        onOpenSettings={() => setShowSettings(true)}
      />

      <main className="main-panel">
        {showSettings ? (
          <div className="content-scroll">
            <Settings onBack={() => setShowSettings(false)} />
          </div>
        ) : (
          <>
            {/* Scrollable content zone */}
            <div className="content-scroll px-6 py-5">
              {!selectedTask && inbox.length === 0 && (
                <EmptyState onSelectExample={(text) => { setTaskInput(text); taskInputRef.current?.focus(); }} />
              )}

              {!selectedTask && inbox.length > 0 && (
                <div className="flex items-center justify-center h-full">
                  <p className="text-sm text-slate-600">Select a task from the sidebar</p>
                </div>
              )}

              {selectedTask && (
                <TaskDetail task={selectedTask} detail={taskDetail} onAction={act} actionMsg={actionMsg} />
              )}
            </div>

            {/* Fixed input dock — always at bottom, no scroll */}
            <TaskInput
              ref={taskInputRef}
              value={taskInput}
              onChange={setTaskInput}
              onSubmit={(e) => void createTask(e)}
              creating={taskCreating}
              message={taskMsg}
              onDismissMessage={() => setTaskMsg("")}
              apiReachable={apiReachable}
            />
          </>
        )}
      </main>
    </div>
  );
}
