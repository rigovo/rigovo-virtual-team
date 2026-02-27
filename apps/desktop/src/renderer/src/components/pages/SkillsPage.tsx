import type { ConnectorStatus, PersonaMember } from "../../types";

interface SkillsPageProps {
  agentModels: Record<string, string>;
  agentTools: Record<string, string[]>;
  personas: PersonaMember[];
  connectors: ConnectorStatus[];
}

export default function SkillsPage({ agentModels, agentTools, personas, connectors }: SkillsPageProps): JSX.Element {
  const roles = Object.keys(agentModels);

  return (
    <section className="workspace-page">
      <div className="workspace-page-header">
        <h2>Skills</h2>
        <p>Agent capabilities from `GET /v1/settings` (`agent_models` and `agent_tools`).</p>
      </div>

      <div className="workspace-stack">
        {roles.length === 0 && (
          <article className="workspace-card">
            <div className="workspace-card-head">
              <div>
                <h3>No skill data</h3>
                <p>`/v1/settings` did not return model/tool assignments.</p>
              </div>
            </div>
          </article>
        )}
        {roles.map((role) => (
          <article key={role} className="workspace-card">
            <div className="workspace-card-head">
              <div>
                <h3>{role}</h3>
                <p>Model: {agentModels[role] || "not configured"}</p>
              </div>
              <span className="status-chip status-chip-ready">{(agentTools[role] || []).length} tools</span>
            </div>
            <p className="workspace-card-copy">
              {(agentTools[role] || []).length ? agentTools[role].join(", ") : "No explicit tools configured for this agent."}
            </p>
          </article>
        ))}

        <article className="workspace-card">
          <div className="workspace-card-head">
            <div>
              <h3>Team personas</h3>
              <p>From `GET /v1/control/state` personas</p>
            </div>
            <span className="status-chip status-chip-ready">{personas.length}</span>
          </div>
          <p className="workspace-card-copy">
            {personas.length
              ? personas.map((p) => `${p.name} (${p.role})`).slice(0, 6).join(", ")
              : "No personas returned by API."}
          </p>
        </article>

        <article className="workspace-card">
          <div className="workspace-card-head">
            <div>
              <h3>Connected tools</h3>
              <p>From `GET /v1/control/state` connectors</p>
            </div>
            <span className="status-chip status-chip-ready">{connectors.length}</span>
          </div>
          <p className="workspace-card-copy">
            {connectors.length
              ? connectors.map((c) => `${c.name}:${c.state}`).slice(0, 8).join(", ")
              : "No connectors returned by API."}
          </p>
        </article>
      </div>
    </section>
  );
}
