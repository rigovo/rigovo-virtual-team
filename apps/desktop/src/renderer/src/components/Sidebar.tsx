import { useEffect, useRef, useState, KeyboardEvent } from "react";
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
  /** Called when user renames a thread via double-click or context menu. */
  onRenameTask?: (id: string, title: string) => void;
}

function dotClass(status: string): string {
  if (status === "running" || status === "in_progress") return "running";
  if (status === "failed" || status === "error") return "failed";
  if (status === "waiting" || status === "pending" || status === "paused") return "waiting";
  return "";
}

/** Group inbox tasks by workspaceLabel. Unlabelled tasks → "" group. */
function groupInbox(inbox: InboxTask[]): Array<{ label: string; tasks: InboxTask[] }> {
  const map = new Map<string, InboxTask[]>();
  for (const t of inbox) {
    const key = t.workspaceLabel?.trim() || "";
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(t);
  }
  // Put named groups first (sorted), unnamed last
  const named: Array<{ label: string; tasks: InboxTask[] }> = [];
  let unnamed: InboxTask[] | undefined;
  for (const [label, tasks] of map) {
    if (label === "") { unnamed = tasks; }
    else { named.push({ label, tasks }); }
  }
  named.sort((a, b) => a.label.localeCompare(b.label));
  if (unnamed?.length) named.push({ label: "", tasks: unnamed });
  return named;
}

interface ContextMenu {
  taskId: string;
  x: number;
  y: number;
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
  onRenameTask,
}: SidebarProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  // Inline rename state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const editInputRef = useRef<HTMLInputElement | null>(null);

  // Context menu state
  const [ctxMenu, setCtxMenu] = useState<ContextMenu | null>(null);
  const ctxRef = useRef<HTMLDivElement | null>(null);

  // Collapsed groups
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  // Close account menu on outside click
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

  // Close context menu on outside click or Escape
  useEffect(() => {
    if (!ctxMenu) return;
    const handler = (e: MouseEvent) => {
      if (ctxRef.current && !ctxRef.current.contains(e.target as Node)) {
        setCtxMenu(null);
      }
    };
    const keyHandler = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setCtxMenu(null);
    };
    window.addEventListener("mousedown", handler);
    window.addEventListener("keydown", keyHandler);
    return () => {
      window.removeEventListener("mousedown", handler);
      window.removeEventListener("keydown", keyHandler);
    };
  }, [ctxMenu]);

  // Auto-focus rename input when edit starts
  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);

  const startEditing = (task: InboxTask) => {
    setEditingId(task.id);
    setEditingTitle(task.title);
    setCtxMenu(null);
  };

  const commitRename = () => {
    if (!editingId) return;
    const title = editingTitle.trim();
    if (title && onRenameTask) onRenameTask(editingId, title);
    setEditingId(null);
    setEditingTitle("");
  };

  const cancelRename = () => {
    setEditingId(null);
    setEditingTitle("");
  };

  const handleEditKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") { e.preventDefault(); commitRename(); }
    if (e.key === "Escape") { e.preventDefault(); cancelRename(); }
  };

  const handleRightClick = (e: React.MouseEvent, task: InboxTask) => {
    e.preventDefault();
    setCtxMenu({ taskId: task.id, x: e.clientX, y: e.clientY });
  };

  const toggleGroup = (label: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  };

  const groups = groupInbox(inbox);

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

      {/* Threads section header */}
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

      {/* Thread list — grouped by workspace label, only this section scrolls */}
      <div className="sb-threads">
        {inbox.length === 0 ? (
          <div className="sb-no-threads">No threads yet</div>
        ) : (
          groups.map(({ label, tasks }) => {
            const isCollapsed = label !== "" && collapsedGroups.has(label);
            return (
              <div key={label || "__ungrouped__"} className="sb-group">
                {/* Group header — only rendered for named groups */}
                {label !== "" && (
                  <button
                    type="button"
                    className="sb-group-header"
                    onClick={() => toggleGroup(label)}
                    title={label}
                  >
                    <svg
                      viewBox="0 0 10 10"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.3"
                      strokeLinecap="round"
                      width="8"
                      height="8"
                      style={{ flexShrink: 0, transition: "transform 0.15s", transform: isCollapsed ? "rotate(-90deg)" : "none" }}
                    >
                      <path d="M2 3.5l3 3 3-3" />
                    </svg>
                    <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" width="11" height="11" style={{ flexShrink: 0 }}>
                      <path d="M1.5 4.5h11v7a.5.5 0 0 1-.5.5h-10a.5.5 0 0 1-.5-.5v-7zM1.5 4.5l1-2H6l1 1.5h4.5" />
                    </svg>
                    <span className="sb-group-label-text">{label}</span>
                    <span className="sb-group-count">{tasks.length}</span>
                  </button>
                )}

                {/* Thread items within group */}
                {!isCollapsed && tasks.map((task) => (
                  editingId === task.id ? (
                    /* Inline rename input */
                    <div key={task.id} className="sb-thread sb-thread-editing">
                      <span className={`sb-dot ${dotClass(task.status)}`} aria-hidden="true" />
                      <input
                        ref={editInputRef}
                        className="sb-thread-edit-input"
                        value={editingTitle}
                        onChange={(e) => setEditingTitle(e.target.value)}
                        onKeyDown={handleEditKeyDown}
                        onBlur={commitRename}
                        maxLength={200}
                        aria-label="Rename thread"
                      />
                    </div>
                  ) : (
                    <button
                      key={task.id}
                      type="button"
                      className={`sb-thread${selected === task.id ? " active" : ""}`}
                      onClick={() => onSelect(task.id)}
                      onDoubleClick={() => startEditing(task)}
                      onContextMenu={(e) => handleRightClick(e, task)}
                      title="Double-click to rename"
                    >
                      <span className={`sb-dot ${dotClass(task.status)}`} aria-hidden="true" />
                      <span className="sb-thread-title">{task.title}</span>
                      <span className="sb-thread-time">{task.updatedAt}</span>
                    </button>
                  )
                ))}
              </div>
            );
          })
        )}
      </div>

      {/* Context menu (right-click) */}
      {ctxMenu && (
        <div
          ref={ctxRef}
          className="sb-ctx-menu"
          style={{ top: ctxMenu.y, left: ctxMenu.x }}
          role="menu"
        >
          <button
            type="button"
            className="sb-ctx-item"
            role="menuitem"
            onClick={() => {
              const task = inbox.find((t) => t.id === ctxMenu.taskId);
              if (task) startEditing(task);
            }}
          >
            <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" width="12" height="12">
              <path d="M10 2l2 2-7 7H3v-2l7-7z" />
            </svg>
            Rename
          </button>
        </div>
      )}

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
