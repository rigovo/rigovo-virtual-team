import type { ConnectorStatus, PersonaMember } from "../../types";

interface SkillsPageProps {
  agentModels: Record<string, string>;
  agentTools: Record<string, string[]>;
  personas: PersonaMember[];
  connectors: ConnectorStatus[];
}

/* ── Role metadata ──────────────────────────────────────────────── */
const ROLE_META: Record<string, { icon: string; label: string; desc: string; color: string }> = {
  lead:     { icon: "🎯", label: "Lead",     desc: "Architecture decisions",    color: "#4338ca" },
  planner:  { icon: "📋", label: "Planner",  desc: "Task decomposition",        color: "#0284c7" },
  coder:    { icon: "💻", label: "Coder",    desc: "Code implementation",       color: "#15803d" },
  reviewer: { icon: "🔍", label: "Reviewer", desc: "Code review",               color: "#b45309" },
  qa:       { icon: "✅", label: "QA",       desc: "Test generation",           color: "#047857" },
  security: { icon: "🔐", label: "Security", desc: "Security audit",            color: "#b91c1c" },
  devops:   { icon: "⚙️",  label: "DevOps",  desc: "Infrastructure config",     color: "#6d28d9" },
  sre:      { icon: "📊", label: "SRE",      desc: "Reliability checks",        color: "#0369a1" },
  docs:     { icon: "📖", label: "Docs",     desc: "Documentation",             color: "#374151" },
};

/* ── Model tier badge ───────────────────────────────────────────── */
function ModelTierBadge({ modelId }: { modelId: string }) {
  const id = modelId.toLowerCase();
  let tier = "standard";
  let bg = "rgba(0,0,0,0.06)";
  let color = "var(--t3)";

  if (id.includes("opus") || id.includes("pro") || id.includes("premium")) {
    tier = "premium"; bg = "rgba(79,70,229,0.08)"; color = "#4338ca";
  } else if (id.includes("sonnet") || id.includes("standard")) {
    tier = "standard"; bg = "rgba(2,132,199,0.08)"; color = "#0369a1";
  } else if (id.includes("haiku") || id.includes("flash") || id.includes("fast")) {
    tier = "fast"; bg = "rgba(22,163,74,0.08)"; color = "#15803d";
  } else if (id.includes("local") || id.includes("ollama") || id.includes("llama") || id.includes("qwen")) {
    tier = "local"; bg = "rgba(120,113,108,0.08)"; color = "#57534e";
  }

  return (
    <span style={{ fontSize: 10, fontWeight: 600, padding: "1px 7px", borderRadius: 100, background: bg, color }}>
      {tier}
    </span>
  );
}

/* ── Agent role card ────────────────────────────────────────────── */
function AgentRoleCard({ role, model, tools }: { role: string; model: string; tools: string[] }) {
  const meta = ROLE_META[role] ?? { icon: "🤖", label: role, desc: "Agent role", color: "var(--t2)" };

  return (
    <div style={{
      border: "1px solid var(--border)",
      borderRadius: 12,
      background: "var(--canvas)",
      padding: "14px 16px",
      display: "flex",
      flexDirection: "column",
      gap: 10,
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <div style={{
          width: 36, height: 36, borderRadius: 10, flexShrink: 0,
          background: `${meta.color}12`,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 18,
        }}>
          {meta.icon}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: "var(--t1)" }}>{meta.label}</span>
            <ModelTierBadge modelId={model} />
          </div>
          <p style={{ fontSize: 11, color: "var(--t3)", margin: "2px 0 0" }}>{meta.desc}</p>
        </div>
        <span style={{
          fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 100, flexShrink: 0,
          background: tools.length > 0 ? "rgba(22,163,74,0.08)" : "rgba(0,0,0,0.05)",
          color: tools.length > 0 ? "#15803d" : "var(--t4)",
        }}>
          {tools.length} tools
        </span>
      </div>

      {/* Model name */}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 10, fontWeight: 600, color: "var(--t4)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Model</span>
        <code style={{ fontSize: 11, color: "var(--t2)", background: "rgba(0,0,0,0.04)", padding: "1px 7px", borderRadius: 5 }}>
          {model || "not configured"}
        </code>
      </div>

      {/* Tools */}
      {tools.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {tools.map((tool) => (
            <span key={tool} style={{
              fontSize: 10, padding: "2px 7px", borderRadius: 5, fontFamily: "monospace",
              background: "rgba(0,0,0,0.04)", color: "var(--t2)",
              border: "1px solid var(--border)",
            }}>
              {tool}
            </span>
          ))}
        </div>
      ) : (
        <p style={{ fontSize: 11, color: "var(--t4)", margin: 0, fontStyle: "italic" }}>
          Inherits global tool policy
        </p>
      )}
    </div>
  );
}

/* ── Connector state dot + badge ────────────────────────────────── */
function ConnectorStateBadge({ state }: { state: string }) {
  const cfg: Record<string, { bg: string; color: string; dot: string }> = {
    connected: { bg: "rgba(22,163,74,0.08)",  color: "#15803d", dot: "#22c55e" },
    degraded:  { bg: "rgba(245,158,11,0.08)", color: "#b45309", dot: "#f59e0b" },
    offline:   { bg: "rgba(220,38,38,0.08)",  color: "#b91c1c", dot: "#ef4444" },
  };
  const c = cfg[state] ?? cfg.offline;
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 100, background: c.bg, color: c.color }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: c.dot }} />
      {state}
    </span>
  );
}

/* ── Connector card ─────────────────────────────────────────────── */
function ConnectorCard({ connector }: { connector: ConnectorStatus }) {
  const typeIcon: Record<string, string> = {
    messaging:   "💬",
    identity:    "🔑",
    workflow:    "🔄",
    knowledge:   "📚",
    database:    "🗄️",
    storage:     "📦",
    monitoring:  "📈",
    ticketing:   "🎫",
    git:         "🌿",
    ci:          "🏗️",
  };
  const icon = typeIcon[connector.type?.toLowerCase() ?? ""] ?? "🔌";

  return (
    <div style={{
      border: "1px solid var(--border)", borderRadius: 10,
      background: "var(--canvas)", padding: "12px 14px",
      display: "flex", alignItems: "center", gap: 10,
    }}>
      <span style={{ fontSize: 20, flexShrink: 0 }}>{icon}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>{connector.name}</span>
          <ConnectorStateBadge state={connector.state} />
          {connector.type && (
            <span style={{ fontSize: 10, color: "var(--t4)", background: "rgba(0,0,0,0.04)", padding: "1px 6px", borderRadius: 4 }}>
              {connector.type}
            </span>
          )}
        </div>
        {connector.notes && (
          <p style={{ fontSize: 11, color: "var(--t3)", margin: "3px 0 0" }}>{connector.notes}</p>
        )}
        {connector.channel && (
          <p style={{ fontSize: 11, color: "var(--t4)", margin: "2px 0 0", fontFamily: "monospace" }}>#{connector.channel}</p>
        )}
      </div>
    </div>
  );
}

/* ── Persona card ───────────────────────────────────────────────── */
const ROLE_BADGE_CFG: Record<string, { bg: string; color: string }> = {
  admin:     { bg: "rgba(220,38,38,0.08)",   color: "#b91c1c" },
  tech_lead: { bg: "rgba(79,70,229,0.08)",   color: "#4338ca" },
  devops:    { bg: "rgba(109,40,217,0.08)",  color: "#6d28d9" },
  qa:        { bg: "rgba(22,163,74,0.08)",   color: "#15803d" },
  sre:       { bg: "rgba(2,132,199,0.08)",   color: "#0284c7" },
  reviewer:  { bg: "rgba(217,119,6,0.08)",   color: "#b45309" },
};

function PersonaCard({ persona }: { persona: PersonaMember }) {
  const badge = ROLE_BADGE_CFG[persona.role] ?? { bg: "rgba(0,0,0,0.06)", color: "var(--t3)" };
  const initials = persona.name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase();

  return (
    <div style={{
      border: "1px solid var(--border)", borderRadius: 10,
      background: "var(--canvas)", padding: "10px 14px",
      display: "flex", alignItems: "center", gap: 10,
    }}>
      {/* Avatar */}
      <div style={{
        width: 32, height: 32, borderRadius: "50%", flexShrink: 0,
        background: `${badge.color}18`,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 11, fontWeight: 700, color: badge.color,
      }}>
        {initials}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)", display: "block" }}>{persona.name}</span>
        <span style={{ fontSize: 10, fontWeight: 600, padding: "0 6px", borderRadius: 4, background: badge.bg, color: badge.color }}>
          {persona.role.replace("_", " ")}
        </span>
      </div>
      {persona.team && (
        <span style={{ fontSize: 10, color: "var(--t4)", fontFamily: "monospace" }}>{persona.team.slice(0, 6)}…</span>
      )}
    </div>
  );
}

/* ── Section header ─────────────────────────────────────────────── */
function SectionHeader({ title, count, description }: { title: string; count?: number; description?: string }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <h3 style={{ fontSize: 13, fontWeight: 700, color: "var(--t1)", margin: 0, letterSpacing: "-0.01em" }}>{title}</h3>
        {count !== undefined && (
          <span style={{ fontSize: 11, fontWeight: 600, padding: "1px 7px", borderRadius: 100, background: "rgba(0,0,0,0.06)", color: "var(--t3)" }}>
            {count}
          </span>
        )}
      </div>
      {description && (
        <p style={{ fontSize: 12, color: "var(--t4)", margin: "3px 0 0" }}>{description}</p>
      )}
    </div>
  );
}

/* ── Main page ─────────────────────────────────────────────────────── */
export default function SkillsPage({ agentModels, agentTools, personas, connectors }: SkillsPageProps): JSX.Element {
  const roles = Object.keys(agentModels);
  const totalTools = Object.values(agentTools).reduce((sum, t) => sum + t.length, 0);
  const connectedCount = connectors.filter((c) => c.state === "connected").length;

  return (
    <section className="workspace-page">

      {/* ── Page header ─────────────────────────────────────────── */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
          <div>
            <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--t1)", letterSpacing: "-0.02em", margin: 0 }}>Skills</h2>
            <p style={{ fontSize: 13, color: "var(--t3)", marginTop: 4 }}>
              Agent workforce — models, tools, and integrations powering every task.
            </p>
          </div>
          {/* Summary badges */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {[
              { val: roles.length,      label: "Agents",       color: "#4338ca", bg: "rgba(79,70,229,0.08)"  },
              { val: totalTools,        label: "Tools",        color: "#15803d", bg: "rgba(22,163,74,0.08)"  },
              { val: connectedCount,    label: "Connected",    color: "#0284c7", bg: "rgba(2,132,199,0.08)"  },
              { val: personas.length,   label: "Personas",     color: "#b45309", bg: "rgba(217,119,6,0.08)"  },
            ].map(({ val, label, color, bg }) => (
              <div key={label} style={{
                display: "flex", flexDirection: "column", alignItems: "center",
                padding: "6px 14px", borderRadius: 10, background: bg,
                minWidth: 60, gap: 1,
              }}>
                <span style={{ fontSize: 18, fontWeight: 700, color, letterSpacing: "-0.02em", lineHeight: 1 }}>{val}</span>
                <span style={{ fontSize: 10, color, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", opacity: 0.75 }}>{label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Agent roster ────────────────────────────────────────── */}
      <div style={{ marginBottom: 28 }}>
        <SectionHeader
          title="Agent Roster"
          count={roles.length}
          description="Each agent role runs a dedicated model with its own tool permissions."
        />
        {roles.length === 0 ? (
          <div style={{
            textAlign: "center", padding: "28px 20px",
            border: "1px dashed var(--border)", borderRadius: 12,
          }}>
            <p style={{ fontSize: 13, color: "var(--t4)", margin: 0 }}>No agent models configured yet.</p>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 10 }}>
            {roles.map((role) => (
              <AgentRoleCard
                key={role}
                role={role}
                model={agentModels[role] || "not configured"}
                tools={agentTools[role] || []}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Integrations ─────────────────────────────────────────── */}
      <div style={{ marginBottom: 28 }}>
        <SectionHeader
          title="Integrations"
          count={connectors.length}
          description={`${connectedCount} of ${connectors.length} connectors online.`}
        />
        {connectors.length === 0 ? (
          <div style={{
            textAlign: "center", padding: "24px 20px",
            border: "1px dashed var(--border)", borderRadius: 12,
          }}>
            <p style={{ fontSize: 13, color: "var(--t4)", margin: 0 }}>No connectors registered in control state.</p>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 8 }}>
            {connectors.map((c, i) => (
              <ConnectorCard key={`${c.name}-${i}`} connector={c} />
            ))}
          </div>
        )}
      </div>

      {/* ── Team personas ───────────────────────────────────────── */}
      <div>
        <SectionHeader
          title="Team Personas"
          count={personas.length}
          description="Human members and their roles in the governance workflow."
        />
        {personas.length === 0 ? (
          <div style={{
            textAlign: "center", padding: "24px 20px",
            border: "1px dashed var(--border)", borderRadius: 12,
          }}>
            <p style={{ fontSize: 13, color: "var(--t4)", margin: 0 }}>No personas configured. Add team members via the control plane.</p>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }}>
            {personas.map((p) => (
              <PersonaCard key={p.id} persona={p} />
            ))}
          </div>
        )}
      </div>

    </section>
  );
}
