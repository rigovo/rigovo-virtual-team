interface WorkspaceStripProps {
  title: string;
  subtitle?: string;
  onOpenFolder?: () => void;
  onOpenSettings: () => void;
}

export default function WorkspaceStrip({
  title,
  subtitle,
  onOpenFolder,
  onOpenSettings,
}: WorkspaceStripProps) {
  return (
    <header className="workspace-strip" style={{ WebkitAppRegion: "drag" } as React.CSSProperties}>
      <div className="workspace-strip-left" style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}>
        <div>
          <h1 className="workspace-title">{title}</h1>
          {subtitle ? <p className="workspace-subtitle">{subtitle}</p> : null}
        </div>
      </div>
      <div className="workspace-strip-right" style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}>
        {onOpenFolder ? (
          <button type="button" className="strip-ghost-btn" onClick={onOpenFolder}>
            Open folder
          </button>
        ) : null}
        <button type="button" className="strip-link-btn" onClick={onOpenSettings} aria-label="Open settings">
          Settings
        </button>
      </div>
    </header>
  );
}
