import { useEffect, useRef, useState } from "react";
import type { InboxTask, Project } from "../types";

type SidebarView =
  | "threads"
  | "automations"
  | "skills"
  | "documents"
  | "language"
  | "settings";

interface SidebarProps {
  userName: string;
  userEmail?: string;
  userInitials: string;
  organizationName?: string;
  totalUsers?: number;
  inbox: InboxTask[];
  selected: string;
  activeView: SidebarView;
  onSelect: (id: string) => void;
  onNewTask: () => void;
  onOpenFolder: () => void;
  activeProject: Project | null;
  projectLoading: boolean;
  onSignOut: () => void;
  apiReachable: boolean | null;
  onOpenSettings: () => void;
  onOpenAutomations: () => void;
  onOpenSkills: () => void;
  onOpenDocuments: () => void;
  onOpenLanguage: () => void;
}

function dotClass(status: string): string {
  if (status === "running" || status === "in_progress") return "running";
  if (status === "failed" || status === "error") return "failed";
  if (status === "waiting" || status === "pending" || status === "paused") return "waiting";
  return "";
}

export default function Sidebar({
  userName,
  userEmail,
  userInitials,
  organizationName,
  totalUsers,
  inbox,
  selected,
  activeView,
  onSelect,
  onNewTask,
  onSignOut,
  onOpenSettings,
  onOpenAutomations,
  onOpenSkills,
}: SidebarProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    window.addEventListener("mousedown", handler);
    return () => window.removeEventListener("mousedown", handler);
  }, [menuOpen]);

  return (
    <aside className="sidebar">
      {/* Traffic light region — native macOS buttons live here */}
      <div className="sb-traffic" aria-hidden="true" />

      {/* Primary nav */}
      <nav className="sb-nav">
        <button
          type="button"
          className={`sb-nav-item${activeView === "threads" && !selected ? " active" : ""}`}
          onClick={onNewTask}
        >
          <span className="sb-nav-icon">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" width="14" height="14">
              <path d="M3.5 3.5h5M3.5 6.5h4M3.5 9.5h3" />
              <path d="M10.5 8.5l2 2-3.5 3.5h-2v-2l3.5-3.5z" />
            </svg>
          </span>
          New thread
        </button>

        <button
          type="button"
          className={`sb-nav-item${activeView === "automations" ? " active" : ""}`}
          onClick={onOpenAutomations}
        >
          <span className="sb-nav-icon">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" width="14" height="14">
              <circle cx="8" cy="8" r="5" />
              <path d="M8 5.5v2.5l1.8 1" />
            </svg>
          </span>
          Automations
        </button>

        <button
          type="button"
          className={`sb-nav-item${activeView === "skills" ? " active" : ""}`}
          onClick={onOpenSkills}
        >
          <span className="sb-nav-icon">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" width="14" height="14">
              <rect x="3" y="3" width="10" height="10" rx="1.5" />
              <path d="M6 3v10M10 3v10" />
            </svg>
          </span>
          Skills
        </button>
      </nav>

      <div className="sb-divider" />

      {/* Threads section */}
      <div className="sb-section-label">
        Threads
        <button
          type="button"
          className="sb-section-btn"
          onClick={onNewTask}
          aria-label="New thread"
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" width="12" height="12">
            <path d="M8 3.5v9M3.5 8h9" />
          </svg>
        </button>
      </div>

      {/* Thread list — only this section scrolls */}
      <div className="sb-threads">
        {inbox.length === 0 ? (
          <div className="sb-no-threads">No threads yet</div>
        ) : (
          inbox.map((task) => (
            <button
              key={task.id}
              type="button"
              className={`sb-thread${selected === task.id ? " active" : ""}`}
              onClick={() => onSelect(task.id)}
            >
              <span className={`sb-dot ${dotClass(task.status)}`} aria-hidden="true" />
              <span className="sb-thread-title">{task.title}</span>
              <span className="sb-thread-time">{task.updatedAt}</span>
            </button>
          ))
        )}
      </div>

      {/* User / account — bottom */}
      <div className="sb-user" ref={menuRef}>
        <button
          type="button"
          className="sb-user-btn"
          onClick={() => setMenuOpen((v) => !v)}
          aria-label="Account menu"
          aria-expanded={menuOpen}
        >
          <span className="sb-avatar" aria-hidden="true">{userInitials}</span>
          <span className="sb-user-label">{userName}</span>
          <svg viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" width="10" height="10" style={{ flexShrink: 0, color: "var(--t4)" }}>
            <path d={menuOpen ? "M2 7l3-3 3 3" : "M2 3.5l3 3 3-3"} />
          </svg>
        </button>

        {menuOpen && (
          <div className="sb-popover">
            <div className="sb-pop-header">
              <div className="sb-pop-email">{userEmail || userName}</div>
              {organizationName && (
                <div className="sb-pop-org">
                  {organizationName}
                  {typeof totalUsers === "number" ? ` · ${totalUsers} users` : ""}
                </div>
              )}
            </div>

            <button
              type="button"
              className="sb-pop-btn"
              onClick={() => { setMenuOpen(false); onOpenSettings(); }}
            >
              Settings
            </button>

            <div className="sb-pop-sep" />

            <button
              type="button"
              className="sb-pop-btn"
              onClick={() => { setMenuOpen(false); onSignOut(); }}
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
