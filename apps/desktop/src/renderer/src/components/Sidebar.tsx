/* ------------------------------------------------------------------ */
/*  Sidebar — dark sidebar with task list + settings gear               */
/* ------------------------------------------------------------------ */
import type { InboxTask, Project } from "../types";
import { statusClass } from "../defaults";

interface SidebarProps {
  userName: string;
  userInitials: string;
  inbox: InboxTask[];
  selected: string;
  onSelect: (id: string) => void;
  onNewTask: () => void;
  onOpenFolder: () => void;
  activeProject: Project | null;
  projectLoading: boolean;
  onSignOut: () => void;
  apiReachable: boolean | null;
  onOpenSettings: () => void;
}

/* Split inbox into active vs completed */
function splitTasks(inbox: InboxTask[]) {
  const active: InboxTask[] = [];
  const done: InboxTask[] = [];
  for (const t of inbox) {
    if (t.status.includes("complete") || t.status.includes("fail") || t.status.includes("reject")) {
      done.push(t);
    } else {
      active.push(t);
    }
  }
  return { active, done };
}

export default function Sidebar({
  userName, userInitials, inbox, selected, onSelect,
  onNewTask, onOpenFolder, activeProject, projectLoading,
  onSignOut, apiReachable, onOpenSettings
}: SidebarProps) {
  const { active, done } = splitTasks(inbox);

  return (
    <aside className="sidebar">
      {/* Logo + status */}
      <div className="flex items-center gap-2.5 px-4 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-xl text-sm font-bold text-white bg-brand shadow-lg shadow-brand/20">
          R
        </div>
        <span className="text-sm font-semibold text-slate-200">Rigovo</span>
        <span className={`ml-auto h-2 w-2 rounded-full ${
          apiReachable === null ? "bg-slate-600" : apiReachable ? "bg-emerald-500" : "bg-rose-400"
        }`} title={apiReachable === null ? "Checking..." : apiReachable ? "Connected" : "Disconnected"} />
      </div>

      {/* New task + open folder */}
      <div className="px-3 mb-1">
        <button type="button"
          className="flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-sm font-medium text-slate-300 transition-all hover:bg-white/5 hover:text-white"
          onClick={onNewTask}>
          <span className="flex h-5 w-5 items-center justify-center rounded-md bg-brand/20 text-xs text-brand-light">+</span>
          New task
        </button>
      </div>

      {activeProject && (
        <div className="px-3 mb-2">
          <button type="button"
            className="flex w-full items-center gap-2 rounded-xl px-3 py-1.5 text-[11px] text-slate-600 transition-all hover:bg-white/5 hover:text-slate-400 truncate"
            onClick={onOpenFolder} disabled={projectLoading}>
            <span className="text-[10px]">{"\uD83D\uDCC2"}</span>
            <span className="truncate">{activeProject.name || (projectLoading ? "Opening..." : activeProject.path)}</span>
          </button>
        </div>
      )}

      {!activeProject && (
        <div className="px-3 mb-2">
          <button type="button"
            className="flex w-full items-center gap-2 rounded-xl px-3 py-1.5 text-[11px] text-slate-600 transition-all hover:bg-white/5 hover:text-slate-400"
            onClick={onOpenFolder} disabled={projectLoading}>
            <span className="text-[10px]">{"\uD83D\uDCC2"}</span>
            {projectLoading ? "Opening..." : "Open project folder"}
          </button>
        </div>
      )}

      <div className="px-4 mb-2"><div className="h-px bg-white/5" /></div>

      {/* Task list — scrollable */}
      <div className="flex-1 overflow-y-auto px-2">
        {inbox.length === 0 && (
          <p className="px-3 py-8 text-center text-xs text-slate-600">No tasks yet</p>
        )}

        {/* Active tasks */}
        {active.length > 0 && (
          <div className="mb-2">
            <p className="px-3 py-1.5 text-[10px] font-semibold text-slate-600 uppercase tracking-wider">
              Active ({active.length})
            </p>
            {active.map((it) => (
              <button key={it.id} type="button" onClick={() => onSelect(it.id)}
                className={`task-item ${selected === it.id ? "active" : ""}`}>
                <p className="text-sm font-medium leading-tight truncate">{it.title}</p>
                <div className="mt-1.5 flex items-center gap-2">
                  <span className={statusClass(it.status)}>{it.status}</span>
                  <span className="text-[10px] text-slate-600">{it.updatedAt}</span>
                </div>
              </button>
            ))}
          </div>
        )}

        {/* Completed tasks */}
        {done.length > 0 && (
          <div className="mb-2">
            <p className="px-3 py-1.5 text-[10px] font-semibold text-slate-600 uppercase tracking-wider">
              Completed ({done.length})
            </p>
            {done.map((it) => (
              <button key={it.id} type="button" onClick={() => onSelect(it.id)}
                className={`task-item ${selected === it.id ? "active" : ""} opacity-60`}>
                <p className="text-sm font-medium leading-tight truncate">{it.title}</p>
                <div className="mt-1.5 flex items-center gap-2">
                  <span className={statusClass(it.status)}>{it.status}</span>
                  <span className="text-[10px] text-slate-600">{it.updatedAt}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* User footer */}
      <div className="border-t border-white/5 px-3 py-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-brand/20 text-xs font-semibold text-brand-light">
            {userInitials}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-slate-300 truncate">{userName}</p>
          </div>
          <button type="button" onClick={onOpenSettings} title="Settings"
            className="text-slate-600 hover:text-slate-400 transition p-1">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path d="M6.5 1.5L6.8 3.1C6.1 3.4 5.5 3.8 5 4.3L3.5 3.6L2 6.2L3.3 7.2C3.3 7.5 3.2 7.7 3.2 8C3.2 8.3 3.2 8.5 3.3 8.8L2 9.8L3.5 12.4L5 11.7C5.5 12.2 6.1 12.6 6.8 12.9L6.5 14.5H9.5L9.2 12.9C9.9 12.6 10.5 12.2 11 11.7L12.5 12.4L14 9.8L12.7 8.8C12.8 8.5 12.8 8.3 12.8 8C12.8 7.7 12.8 7.5 12.7 7.2L14 6.2L12.5 3.6L11 4.3C10.5 3.8 9.9 3.4 9.2 3.1L9.5 1.5H6.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/>
              <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.2"/>
            </svg>
          </button>
          <button type="button" onClick={onSignOut}
            className="text-xs text-slate-600 hover:text-slate-400 transition">
            Sign out
          </button>
        </div>
      </div>
    </aside>
  );
}
