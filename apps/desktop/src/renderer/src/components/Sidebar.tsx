import { type ReactNode, useEffect, useRef, useState } from "react";
import type { InboxTask, Project } from "../types";

type SidebarView = "threads" | "automations" | "skills" | "documents" | "language" | "settings";

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

function SvgIcon({ children, size = 16 }: { children: ReactNode; size?: number }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      width={size}
      height={size}
    >
      {children}
    </svg>
  );
}

function NavItem({
  active,
  label,
  icon,
  onClick,
  shortcut,
}: {
  active: boolean;
  label: string;
  icon: ReactNode;
  onClick: () => void;
  shortcut?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`sidebar-nav-btn${active ? " active" : ""}`}
    >
      <span className="sidebar-icon">{icon}</span>
      <span className="flex-1">{label}</span>
      {shortcut && (
        <span className="text-[11px] font-normal" style={{ color: "var(--ui-text-subtle)" }}>
          {shortcut}
        </span>
      )}
    </button>
  );
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
  onOpenFolder: _onOpenFolder,
  activeProject,
  projectLoading: _projectLoading,
  onSignOut,
  apiReachable: _apiReachable,
  onOpenSettings,
  onOpenAutomations,
  onOpenSkills,
  onOpenDocuments,
  onOpenLanguage,
}: SidebarProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (!menuRef.current) return;
      if (menuRef.current.contains(event.target as Node)) return;
      setMenuOpen(false);
    };
    if (menuOpen) window.addEventListener("mousedown", onClick);
    return () => window.removeEventListener("mousedown", onClick);
  }, [menuOpen]);

  return (
    <aside className="sidebar">
      <div className="sidebar-inner codex-sidebar">
        {/* Drag region for native traffic lights */}
        <div className="codex-top-row">
          <div style={{ width: 70 }} aria-hidden="true" />
        </div>

        {/* Primary nav */}
        <nav className="sidebar-nav">
          <NavItem
            active={activeView === "threads" && !selected}
            label="New thread"
            onClick={onNewTask}
            icon={
              <SvgIcon>
                <path d="M3.5 3.5h5M3.5 6.5h4M3.5 9.5h3" />
                <path d="M10.5 8.5l2 2-3.5 3.5h-2v-2l3.5-3.5z" />
              </SvgIcon>
            }
          />
          <NavItem
            active={activeView === "automations"}
            label="Automations"
            onClick={onOpenAutomations}
            icon={
              <SvgIcon>
                <circle cx="8" cy="8" r="5" />
                <path d="M8 5.5v2.5l1.8 1" />
              </SvgIcon>
            }
          />
          <NavItem
            active={activeView === "skills"}
            label="Skills"
            onClick={onOpenSkills}
            icon={
              <SvgIcon>
                <rect x="3" y="3" width="10" height="10" rx="1.5" />
                <path d="M6 3v10M10 3v10" />
              </SvgIcon>
            }
          />
        </nav>

        {/* Threads header */}
        <div className="sidebar-threads-head">
          <span>Threads</span>
          <div className="sidebar-head-actions">
            <button type="button" onClick={onNewTask} className="sidebar-head-btn" title="New thread">
              <SvgIcon size={15}>
                <path d="M8 3.5v9M3.5 8h9" />
              </SvgIcon>
            </button>
          </div>
        </div>

        {/* Documents link */}
        <button
          type="button"
          onClick={onOpenDocuments}
          className={`sidebar-folder-link${activeView === "documents" ? " active" : ""}`}
        >
          <span className="sidebar-icon">
            <SvgIcon size={15}>
              <path d="M2.5 5.5h3.5l1-1.5h6.5v7a1 1 0 01-1 1h-9a1 1 0 01-1-1v-5.5z" />
            </SvgIcon>
          </span>
          Documents
        </button>

        {/* Scrollable thread list — ONLY this section scrolls */}
        <div className="sidebar-scroll">
          {inbox.length === 0 ? (
            <div className="sidebar-no-threads">No threads yet</div>
          ) : (
            <div className="sidebar-project-group">
              <div className="sidebar-project-row">
                <span className="sidebar-icon">
                  <SvgIcon size={13}>
                    <path d="M2.5 5.5h3.5l1-1.5h6.5v7a1 1 0 01-1 1h-9a1 1 0 01-1-1v-5.5z" />
                  </SvgIcon>
                </span>
                <span className="sidebar-project-label">
                  {activeProject?.name || "rigour"}
                </span>
              </div>

              <div className="sidebar-thread-groups">
                {inbox.map((task) => (
                  <button
                    key={task.id}
                    type="button"
                    onClick={() => onSelect(task.id)}
                    className={`sidebar-thread-row${selected === task.id ? " active" : ""}`}
                  >
                    <span className="sidebar-thread-title">{task.title}</span>
                    <span className="sidebar-thread-time">{task.updatedAt}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Bottom — clean Settings link like Codex */}
        <div className="sidebar-bottom" ref={menuRef}>
          <button
            type="button"
            className="sidebar-nav-btn"
            onClick={() => setMenuOpen((v) => !v)}
          >
            <span className="sidebar-icon">
              <SvgIcon size={15}>
                <circle cx="8" cy="8" r="5.5" />
                <path d="M8 5.5v0M8 10.5v0" strokeWidth="0" />
                <path d="M9.8 6.5a2 2 0 00-2.5-.7 2 2 0 00.7 3.7V11" />
              </SvgIcon>
            </span>
            <span>Settings</span>
          </button>

          {menuOpen && (
            <div className="sidebar-popover animate-fade-in">
              <div className="sidebar-pop-header">
                <div className="flex items-center gap-2">
                  <span
                    className="inline-flex h-5 w-5 items-center justify-center rounded-full text-[9px] font-semibold"
                    style={{ background: "rgba(0,0,0,0.08)", color: "var(--ui-text-secondary)" }}
                  >
                    {userInitials}
                  </span>
                  <span className="text-[var(--ui-text-secondary)] font-medium">
                    {userEmail || userName}
                  </span>
                </div>
                {organizationName && (
                  <div className="mt-0.5 pl-7">
                    {organizationName}
                    {typeof totalUsers === "number" ? ` \u00B7 ${totalUsers} users` : ""}
                  </div>
                )}
              </div>
              <button type="button" className="sidebar-pop-btn" onClick={() => { setMenuOpen(false); onOpenSettings(); }}>
                Settings
              </button>
              <button type="button" className="sidebar-pop-btn" onClick={() => { setMenuOpen(false); onOpenLanguage(); }}>
                Language
              </button>
              <div style={{ height: 1, background: "var(--ui-border)", margin: "4px 8px" }} />
              <button type="button" className="sidebar-pop-btn" onClick={() => { setMenuOpen(false); onSignOut(); }}>
                Log out
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
