interface DocumentsPageProps {
  projectName?: string;
  projectPath?: string;
  projectLoading: boolean;
  onOpenFolder: () => void;
}

export default function DocumentsPage({
  projectName,
  projectPath,
  projectLoading,
  onOpenFolder,
}: DocumentsPageProps): JSX.Element {
  return (
    <section className="workspace-page">
      <div className="workspace-page-header">
        <h2>Documents</h2>
        <p>Add PRDs, architecture notes, and runbooks so agents can plan with project context.</p>
      </div>

      <article className="workspace-card">
        <div className="workspace-card-head">
          <div>
            <h3>{projectName || "No project selected"}</h3>
            <p>{projectPath || "Connect a folder to index documents."}</p>
          </div>
          <button type="button" className="action-btn" onClick={onOpenFolder} disabled={projectLoading}>
            {projectLoading ? "Opening..." : "Add folder"}
          </button>
        </div>
      </article>
    </section>
  );
}

