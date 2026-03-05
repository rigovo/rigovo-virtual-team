import { useEffect, useState } from "react";
import type { ConnectorStatus, PersonaMember } from "../../types";

interface SkillsPageProps {
  agentModels: Record<string, string>;
  agentTools: Record<string, string[]>;
  personas: PersonaMember[];
  connectors: ConnectorStatus[];
  onOpenSettings?: () => void;
  onOpenAutomations?: () => void;
  onSaveRoleConfig?: (
    role: string,
    model: string,
    tools: string[],
  ) => Promise<string | null>;
  onOpenCapabilitiesForConnector?: (
    connectorName: string,
    source?: "marketplace" | "github",
  ) => void;
  onAssignConnectorTools?: (
    connectorName: string,
    role: string,
  ) => Promise<string | null>;
  onInstallAndAssignConnectorTools?: (
    connectorName: string,
    role: string,
  ) => Promise<{ ok: boolean; message: string }>;
  onRefreshIntegrations?: () => Promise<string | null>;
  onSavePersonas?: (personas: PersonaMember[]) => Promise<string | null>;
}

/* ── Role metadata ──────────────────────────────────────────────── */
const ROLE_META: Record<
  string,
  { label: string; desc: string; color: string }
> = {
  lead: {
    label: "Tech Lead",
    desc: "Architecture decisions",
    color: "var(--accent-text)",
  },
  planner: {
    label: "Project Manager",
    desc: "Task decomposition",
    color: "var(--accent-text)",
  },
  coder: {
    label: "Software Engineer",
    desc: "Code implementation",
    color: "var(--accent-text)",
  },
  reviewer: {
    label: "Code Reviewer",
    desc: "Code review",
    color: "var(--accent-text)",
  },
  qa: {
    label: "QA Engineer",
    desc: "Test generation",
    color: "var(--accent-text)",
  },
  security: {
    label: "Security Engineer",
    desc: "Security audit",
    color: "var(--accent-text)",
  },
  devops: {
    label: "DevOps",
    desc: "Infrastructure config",
    color: "var(--accent-text)",
  },
  sre: {
    label: "SRE",
    desc: "Reliability checks",
    color: "var(--accent-text)",
  },
  docs: {
    label: "Technical Writer",
    desc: "Documentation",
    color: "var(--accent-text)",
  },
};

function roleIcon(role: string): JSX.Element {
  const common = {
    width: 18,
    height: 18,
    viewBox: "0 0 20 20",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  if (role === "lead")
    return (
      <svg {...common}>
        <path d="M10 3l2 4 4 .6-3 3 .7 4.4L10 13l-3.7 2 0.7-4.4-3-3L8 7z" />
      </svg>
    );
  if (role === "planner")
    return (
      <svg {...common}>
        <rect x="4" y="3.5" width="12" height="13" rx="2" />
        <path d="M7 3.5V2.5M13 3.5V2.5M7 8.5h6M7 11.5h6M7 14.5h4" />
      </svg>
    );
  if (role === "coder")
    return (
      <svg {...common}>
        <rect x="2.5" y="4" width="15" height="10" rx="2" />
        <path d="M8 16h4M6.5 9.2l-2 1.8 2 1.8M13.5 9.2l2 1.8-2 1.8" />
      </svg>
    );
  if (role === "reviewer")
    return (
      <svg {...common}>
        <circle cx="9" cy="9" r="4.5" />
        <path d="M12.6 12.6L16.5 16.5" />
      </svg>
    );
  if (role === "qa")
    return (
      <svg {...common}>
        <rect x="3" y="3" width="14" height="14" rx="2.5" />
        <path d="M6.8 10.2l2 2 4.3-4.5" />
      </svg>
    );
  if (role === "security")
    return (
      <svg {...common}>
        <path d="M10 2.8l6 2.4v4.4c0 3.5-2.3 6.1-6 7.6-3.7-1.5-6-4.1-6-7.6V5.2z" />
      </svg>
    );
  if (role === "devops")
    return (
      <svg {...common}>
        <circle cx="10" cy="10" r="2.3" />
        <path d="M10 3.2v2.1M10 14.7v2.1M16.8 10h-2.1M5.3 10H3.2" />
      </svg>
    );
  if (role === "sre")
    return (
      <svg {...common}>
        <path d="M3.5 15.5h13M6 12V8M10 12V5.5M14 12V9.5" />
      </svg>
    );
  return (
    <svg {...common}>
      <path d="M4.5 3.5h11v13h-11zM7.5 3.5v13M7.5 7.5h8" />
    </svg>
  );
}

/* ── Model tier badge ───────────────────────────────────────────── */
function ModelTierBadge({ modelId }: { modelId: string }) {
  const id = modelId.toLowerCase();
  let tier = "standard";
  let bg = "rgba(0,0,0,0.06)";
  let color = "var(--t3)";

  if (id.includes("opus") || id.includes("pro") || id.includes("premium")) {
    tier = "premium";
    bg = "var(--accent-bg)";
    color = "var(--accent-text)";
  } else if (id.includes("sonnet") || id.includes("standard")) {
    tier = "standard";
    bg = "var(--accent-bg)";
    color = "var(--accent-text)";
  } else if (
    id.includes("haiku") ||
    id.includes("flash") ||
    id.includes("fast")
  ) {
    tier = "fast";
    bg = "var(--accent-bg)";
    color = "var(--accent-text)";
  } else if (
    id.includes("local") ||
    id.includes("ollama") ||
    id.includes("llama") ||
    id.includes("qwen")
  ) {
    tier = "local";
    bg = "rgba(120,113,108,0.08)";
    color = "#57534e";
  }

  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 600,
        padding: "1px 7px",
        borderRadius: 100,
        background: bg,
        color,
      }}
    >
      {tier}
    </span>
  );
}

/* ── Agent role card ────────────────────────────────────────────── */
function AgentRoleCard({
  role,
  model,
  tools,
  onOpenSettings,
  onSave,
}: {
  role: string;
  model: string;
  tools: string[];
  onOpenSettings?: () => void;
  onSave?: (role: string, model: string, tools: string[]) => Promise<string | null>;
}) {
  const meta = ROLE_META[role] ?? {
    label: role,
    desc: "Agent role",
    color: "var(--t2)",
  };
  const [editing, setEditing] = useState(false);
  const [draftModel, setDraftModel] = useState(model || "");
  const [draftTools, setDraftTools] = useState((tools || []).join(", "));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (editing) return;
    setDraftModel(model || "");
    setDraftTools((tools || []).join(", "));
  }, [model, tools, editing]);

  const saveInline = async () => {
    if (!onSave) return;
    setSaving(true);
    setError("");
    const nextModel = draftModel.trim() || model || "";
    const nextTools = draftTools
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    const err = await onSave(role, nextModel, nextTools);
    setSaving(false);
    if (err) {
      setError(err);
      return;
    }
    setEditing(false);
  };

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 12,
        background: "var(--canvas)",
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 10,
            flexShrink: 0,
            background: `${meta.color}12`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--t2)",
          }}
        >
          {roleIcon(role)}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: "var(--t1)" }}>
              {meta.label}
            </span>
            <ModelTierBadge modelId={model} />
          </div>
          <p style={{ fontSize: 11, color: "var(--t3)", margin: "2px 0 0" }}>
            {meta.desc}
          </p>
        </div>
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            padding: "2px 8px",
            borderRadius: 100,
            flexShrink: 0,
            background:
              tools.length > 0 ? "var(--accent-bg)" : "rgba(0,0,0,0.05)",
            color: tools.length > 0 ? "var(--accent-text)" : "var(--t4)",
          }}
        >
          {tools.length} tools
        </span>
      </div>

      {/* Model name */}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span
          style={{
            fontSize: 10,
            fontWeight: 600,
            color: "var(--t4)",
            textTransform: "uppercase",
            letterSpacing: "0.05em",
          }}
        >
          Model
        </span>
        <code
          style={{
            fontSize: 11,
            color: "var(--t2)",
            background: "rgba(0,0,0,0.04)",
            padding: "1px 7px",
            borderRadius: 5,
          }}
        >
          {model || "not configured"}
        </code>
      </div>

      {editing ? (
        <div style={{ display: "grid", gap: 8 }}>
          <label style={{ display: "grid", gap: 4 }}>
            <span style={{ fontSize: 11, color: "var(--t3)", fontWeight: 600 }}>
              Model id
            </span>
            <input
              value={draftModel}
              onChange={(e) => setDraftModel(e.target.value)}
              className="sb-thread-search"
              placeholder="claude-sonnet-4-6"
              style={{ fontSize: 12 }}
            />
          </label>
          <label style={{ display: "grid", gap: 4 }}>
            <span style={{ fontSize: 11, color: "var(--t3)", fontWeight: 600 }}>
              Tool grants (comma separated)
            </span>
            <input
              value={draftTools}
              onChange={(e) => setDraftTools(e.target.value)}
              className="sb-thread-search"
              placeholder="mcp.figma.read_frame, connector.gdrive.search, mcp.miro.get_board"
              style={{ fontSize: 12 }}
            />
          </label>
          {error && <p style={{ margin: 0, fontSize: 11, color: "#dc2626" }}>{error}</p>}
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              className="ghost-btn"
              onClick={() => void saveInline()}
              disabled={saving}
              style={{ fontSize: 11, padding: "4px 8px" }}
            >
              {saving ? "Saving..." : "Save overrides"}
            </button>
            <button
              type="button"
              className="ghost-btn"
              onClick={() => {
                setEditing(false);
                setError("");
                setDraftModel(model || "");
                setDraftTools((tools || []).join(", "));
              }}
              disabled={saving}
              style={{ fontSize: 11, padding: "4px 8px" }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* Tools */}
          {tools.length > 0 ? (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {tools.map((tool) => (
                <span
                  key={tool}
                  style={{
                    fontSize: 10,
                    padding: "2px 7px",
                    borderRadius: 5,
                    fontFamily: "monospace",
                    background: "rgba(0,0,0,0.04)",
                    color: "var(--t2)",
                    border: "1px solid var(--border)",
                  }}
                >
                  {tool}
                </span>
              ))}
            </div>
          ) : (
            <p
              style={{
                fontSize: 11,
                color: "var(--t4)",
                margin: 0,
                fontStyle: "italic",
              }}
            >
              No explicit tool grants. Add MCP/connector tools to enable Figma,
              Miro, GDrive, etc.
            </p>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 2 }}>
            {onSave && (
              <button
                type="button"
                className="ghost-btn"
                onClick={() => setEditing(true)}
                style={{ fontSize: 11, padding: "4px 8px" }}
              >
                Edit inline
              </button>
            )}
            {onOpenSettings && (
              <button
                type="button"
                className="ghost-btn"
                onClick={onOpenSettings}
                style={{ fontSize: 11, padding: "4px 8px" }}
              >
                Open settings
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/* ── Connector state dot + badge ────────────────────────────────── */
function ConnectorStateBadge({ state }: { state: string }) {
  const cfg: Record<string, { bg: string; color: string; dot: string }> = {
    connected: {
      bg: "var(--accent-bg)",
      color: "var(--accent-text)",
      dot: "var(--accent)",
    },
    degraded: {
      bg: "var(--accent-bg)",
      color: "var(--accent-text)",
      dot: "var(--accent)",
    },
    offline: { bg: "rgba(220,38,38,0.08)", color: "#b91c1c", dot: "#ef4444" },
  };
  const c = cfg[state] ?? cfg.offline;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        fontSize: 10,
        fontWeight: 600,
        padding: "2px 8px",
        borderRadius: 100,
        background: c.bg,
        color: c.color,
      }}
    >
      <span
        style={{ width: 6, height: 6, borderRadius: "50%", background: c.dot }}
      />
      {state}
    </span>
  );
}

/* ── Connector card ─────────────────────────────────────────────── */
function ConnectorCard({
  connector,
  onOpenCapabilitiesForConnector,
  onAssignConnectorTools,
  onInstallAndAssignConnectorTools,
  onRefreshIntegrations,
}: {
  connector: ConnectorStatus;
  onOpenCapabilitiesForConnector?: (
    connectorName: string,
    source?: "marketplace" | "github",
  ) => void;
  onAssignConnectorTools?: (
    connectorName: string,
    role: string,
  ) => Promise<string | null>;
  onInstallAndAssignConnectorTools?: (
    connectorName: string,
    role: string,
  ) => Promise<{ ok: boolean; message: string }>;
  onRefreshIntegrations?: () => Promise<string | null>;
}) {
  const connectorIcon = (type: string): JSX.Element => {
    const common = {
      width: 18,
      height: 18,
      viewBox: "0 0 20 20",
      fill: "none",
      stroke: "currentColor",
      strokeWidth: 1.7,
      strokeLinecap: "round" as const,
      strokeLinejoin: "round" as const,
    };
    if (type === "identity")
      return (
        <svg {...common}>
          <path d="M12 3.5a4 4 0 0 0-4 4v1.5h-2.2l-1.8 1.8 1.2 1.2-1.2 1.2 1.4 1.4 1.2-1.2 1.2 1.2L9.8 13V11h2.2a4 4 0 0 0 0-7.5z" />
        </svg>
      );
    if (type === "workflow")
      return (
        <svg {...common}>
          <path d="M4 7h9M10 4l3 3-3 3M16 13H7M10 10l-3 3 3 3" />
        </svg>
      );
    if (type === "knowledge")
      return (
        <svg {...common}>
          <path d="M4 4.5h5a2 2 0 0 1 2 2V16H6a2 2 0 0 1-2-2zM16 4.5h-5a2 2 0 0 0-2 2V16h5a2 2 0 0 0 2-2z" />
        </svg>
      );
    return (
      <svg {...common}>
        <path d="M8 5.5h4v4M12 5.5 7.5 10M3.5 8a4.5 4.5 0 0 1 4.5-4.5h1.5M16.5 12a4.5 4.5 0 0 1-4.5 4.5h-1.5" />
      </svg>
    );
  };
  const type = connector.type?.toLowerCase() ?? "";
  const [assignRole, setAssignRole] = useState("planner");
  const [assigning, setAssigning] = useState(false);
  const [installingAssigning, setInstallingAssigning] = useState(false);
  const [testing, setTesting] = useState(false);
  const [msg, setMsg] = useState("");
  const actionLabel =
    connector.state === "connected" ? "Configure" : "Connect";

  const assignTools = async () => {
    if (!onAssignConnectorTools) return;
    setAssigning(true);
    setMsg("");
    const err = await onAssignConnectorTools(connector.name, assignRole);
    setAssigning(false);
    setMsg(err ? err : `Assigned tool grants to ${ROLE_META[assignRole]?.label || assignRole}.`);
    window.setTimeout(() => setMsg(""), 2500);
  };

  const testConnector = async () => {
    if (!onRefreshIntegrations) return;
    setTesting(true);
    setMsg("");
    const err = await onRefreshIntegrations();
    setTesting(false);
    setMsg(err ? err : "Connector status refreshed.");
    window.setTimeout(() => setMsg(""), 2500);
  };

  const installAndAssign = async () => {
    if (!onInstallAndAssignConnectorTools) return;
    setInstallingAssigning(true);
    setMsg("");
    const result = await onInstallAndAssignConnectorTools(
      connector.name,
      assignRole,
    );
    setInstallingAssigning(false);
    setMsg(result.message);
    window.setTimeout(() => setMsg(""), 2800);
  };

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--canvas)",
        padding: "12px 14px",
        display: "flex",
        alignItems: "center",
        gap: 10,
      }}
    >
      <span style={{ flexShrink: 0, color: "var(--t2)" }}>
        {connectorIcon(type)}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            flexWrap: "wrap",
          }}
        >
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--t1)" }}>
            {connector.name}
          </span>
          <ConnectorStateBadge state={connector.state} />
          {connector.type && (
            <span
              style={{
                fontSize: 10,
                color: "var(--t4)",
                background: "rgba(0,0,0,0.04)",
                padding: "1px 6px",
                borderRadius: 4,
              }}
            >
              {connector.type}
            </span>
          )}
        </div>
        {connector.notes && (
          <p style={{ fontSize: 11, color: "var(--t3)", margin: "3px 0 0" }}>
            {connector.notes}
          </p>
        )}
        {connector.channel && (
          <p
            style={{
              fontSize: 11,
              color: "var(--t4)",
              margin: "2px 0 0",
              fontFamily: "monospace",
            }}
          >
            #{connector.channel}
          </p>
        )}
        <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
          <button
            type="button"
            className="ghost-btn"
            style={{ fontSize: 11, padding: "4px 8px" }}
            onClick={() =>
              onOpenCapabilitiesForConnector?.(connector.name, "marketplace")
            }
          >
            {actionLabel}
          </button>
          <button
            type="button"
            className="ghost-btn"
            style={{ fontSize: 11, padding: "4px 8px" }}
            onClick={() =>
              onOpenCapabilitiesForConnector?.(connector.name, "github")
            }
          >
            Assign tools
          </button>
          <button
            type="button"
            className="ghost-btn"
            style={{ fontSize: 11, padding: "4px 8px" }}
            onClick={() => void testConnector()}
            disabled={testing}
          >
            {testing ? "Testing..." : "Test"}
          </button>
        </div>
        {onAssignConnectorTools && (
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
            <select
              value={assignRole}
              onChange={(e) => setAssignRole(e.target.value)}
              className="sb-thread-search"
              style={{ fontSize: 11, maxWidth: 150 }}
            >
              {Object.entries(ROLE_META).map(([role, meta]) => (
                <option key={role} value={role}>
                  {meta.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="ghost-btn"
              style={{ fontSize: 11, padding: "4px 8px" }}
              onClick={() => void assignTools()}
              disabled={assigning}
            >
              {assigning ? "Assigning..." : "Apply to role"}
            </button>
            {onInstallAndAssignConnectorTools && (
              <button
                type="button"
                className="ghost-btn"
                style={{ fontSize: 11, padding: "4px 8px" }}
                onClick={() => void installAndAssign()}
                disabled={installingAssigning}
              >
                {installingAssigning ? "Installing..." : "Install + Assign"}
              </button>
            )}
          </div>
        )}
        {msg && (
          <p style={{ fontSize: 11, color: "var(--t3)", margin: "6px 0 0" }}>
            {msg}
          </p>
        )}
      </div>
    </div>
  );
}

/* ── Persona card ───────────────────────────────────────────────── */
const ROLE_BADGE_CFG: Record<string, { bg: string; color: string }> = {
  admin: { bg: "rgba(220,38,38,0.08)", color: "#b91c1c" },
  tech_lead: { bg: "var(--accent-bg)", color: "var(--accent-text)" },
  devops: { bg: "var(--accent-bg)", color: "var(--accent-text)" },
  qa: { bg: "var(--accent-bg)", color: "var(--accent-text)" },
  sre: { bg: "var(--accent-bg)", color: "var(--accent-text)" },
  reviewer: { bg: "var(--accent-bg)", color: "var(--accent-text)" },
};

function PersonaCard({
  persona,
  onEdit,
  onRemove,
}: {
  persona: PersonaMember;
  onEdit?: (persona: PersonaMember) => void;
  onRemove?: (persona: PersonaMember) => void;
}) {
  const badge = ROLE_BADGE_CFG[persona.role] ?? {
    bg: "rgba(0,0,0,0.06)",
    color: "var(--t3)",
  };
  const initials = persona.name
    .split(" ")
    .map((w) => w[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 10,
        background: "var(--canvas)",
        padding: "10px 14px",
        display: "flex",
        alignItems: "center",
        gap: 10,
      }}
    >
      {/* Avatar */}
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: "50%",
          flexShrink: 0,
          background: `${badge.color}18`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 11,
          fontWeight: 700,
          color: badge.color,
        }}
      >
        {initials}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <span
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: "var(--t1)",
            display: "block",
          }}
        >
          {persona.name}
        </span>
        <span
          style={{
            fontSize: 10,
            fontWeight: 600,
            padding: "0 6px",
            borderRadius: 4,
            background: badge.bg,
            color: badge.color,
          }}
        >
          {persona.role.replace("_", " ")}
        </span>
      </div>
      {persona.team && (
        <span
          style={{ fontSize: 10, color: "var(--t4)", fontFamily: "monospace" }}
        >
          {persona.team.slice(0, 6)}…
        </span>
      )}
      <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
        {onEdit && (
          <button
            type="button"
            className="ghost-btn"
            onClick={() => onEdit(persona)}
            style={{ fontSize: 10, padding: "3px 7px" }}
          >
            Edit
          </button>
        )}
        {onRemove && (
          <button
            type="button"
            className="ghost-btn"
            onClick={() => onRemove(persona)}
            style={{ fontSize: 10, padding: "3px 7px" }}
          >
            Remove
          </button>
        )}
      </div>
    </div>
  );
}

/* ── Section header ─────────────────────────────────────────────── */
function SectionHeader({
  title,
  count,
  description,
}: {
  title: string;
  count?: number;
  description?: string;
}) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <h3
          style={{
            fontSize: 13,
            fontWeight: 700,
            color: "var(--t1)",
            margin: 0,
            letterSpacing: "-0.01em",
          }}
        >
          {title}
        </h3>
        {count !== undefined && (
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              padding: "1px 7px",
              borderRadius: 100,
              background: "rgba(0,0,0,0.06)",
              color: "var(--t3)",
            }}
          >
            {count}
          </span>
        )}
      </div>
      {description && (
        <p style={{ fontSize: 12, color: "var(--t4)", margin: "3px 0 0" }}>
          {description}
        </p>
      )}
    </div>
  );
}

/* ── Main page ─────────────────────────────────────────────────────── */
export default function SkillsPage({
  agentModels,
  agentTools,
  personas,
  connectors,
  onOpenSettings,
  onOpenAutomations,
  onSaveRoleConfig,
  onOpenCapabilitiesForConnector,
  onAssignConnectorTools,
  onInstallAndAssignConnectorTools,
  onRefreshIntegrations,
  onSavePersonas,
}: SkillsPageProps): JSX.Element {
  const roles = Object.keys(agentModels);
  const totalTools = Object.values(agentTools).reduce(
    (sum, t) => sum + t.length,
    0,
  );
  const connectedCount = connectors.filter(
    (c) => c.state === "connected",
  ).length;
  const [personaEditorOpen, setPersonaEditorOpen] = useState(false);
  const [personaEditingId, setPersonaEditingId] = useState("");
  const [personaName, setPersonaName] = useState("");
  const [personaRole, setPersonaRole] =
    useState<PersonaMember["role"]>("reviewer");
  const [personaTeam, setPersonaTeam] = useState("");
  const [personaSaving, setPersonaSaving] = useState(false);
  const [personaError, setPersonaError] = useState("");

  const openAddPersona = () => {
    setPersonaEditorOpen(true);
    setPersonaEditingId("");
    setPersonaName("");
    setPersonaRole("reviewer");
    setPersonaTeam("");
    setPersonaError("");
  };

  const openEditPersona = (p: PersonaMember) => {
    setPersonaEditorOpen(true);
    setPersonaEditingId(p.id);
    setPersonaName(p.name);
    setPersonaRole(p.role);
    setPersonaTeam(p.team);
    setPersonaError("");
  };

  const savePersona = async () => {
    if (!onSavePersonas) return;
    const name = personaName.trim();
    if (!name) {
      setPersonaError("Name is required.");
      return;
    }
    setPersonaSaving(true);
    setPersonaError("");
    const id =
      personaEditingId ||
      (window.crypto?.randomUUID
        ? window.crypto.randomUUID()
        : `persona-${Date.now()}`);
    const nextPersona: PersonaMember = {
      id,
      name,
      role: personaRole,
      team: personaTeam.trim(),
    };
    const nextList = personaEditingId
      ? personas.map((p) => (p.id === personaEditingId ? nextPersona : p))
      : [...personas, nextPersona];
    const err = await onSavePersonas(nextList);
    setPersonaSaving(false);
    if (err) {
      setPersonaError(err);
      return;
    }
    setPersonaEditorOpen(false);
  };

  const removePersona = async (p: PersonaMember) => {
    if (!onSavePersonas) return;
    const ok = window.confirm(`Remove persona "${p.name}"?`);
    if (!ok) return;
    setPersonaSaving(true);
    setPersonaError("");
    const err = await onSavePersonas(personas.filter((x) => x.id !== p.id));
    setPersonaSaving(false);
    if (err) {
      setPersonaError(err);
    }
  };

  return (
    <section className="workspace-page">
      {/* ── Page header ─────────────────────────────────────────── */}
      <div style={{ marginBottom: 24 }}>
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <div>
            <h2
              style={{
                fontSize: 16,
                fontWeight: 700,
                color: "var(--t1)",
                letterSpacing: "-0.02em",
                margin: 0,
              }}
            >
              Skills
            </h2>
            <p style={{ fontSize: 13, color: "var(--t3)", marginTop: 4 }}>
              Configure models, tool coverage, and connector readiness before
              execution starts.
            </p>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="button" className="ghost-btn" onClick={onOpenSettings}>
              Configure Agents
            </button>
            <button
              type="button"
              className="ghost-btn"
              onClick={onOpenAutomations}
            >
              Open Automations
            </button>
          </div>
          {/* Summary badges */}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {[
              {
                val: roles.length,
                label: "Agents",
                color: "var(--accent-text)",
                bg: "var(--accent-bg)",
              },
              {
                val: totalTools,
                label: "Tools",
                color: "var(--accent-text)",
                bg: "var(--accent-bg)",
              },
              {
                val: connectedCount,
                label: "Connected",
                color: "var(--accent-text)",
                bg: "var(--accent-bg)",
              },
              {
                val: personas.length,
                label: "Personas",
                color: "var(--t2)",
                bg: "rgba(0,0,0,0.05)",
              },
            ].map(({ val, label, color, bg }) => (
              <div
                key={label}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  padding: "6px 14px",
                  borderRadius: 10,
                  background: bg,
                  minWidth: 60,
                  gap: 1,
                }}
              >
                <span
                  style={{
                    fontSize: 18,
                    fontWeight: 700,
                    color,
                    letterSpacing: "-0.02em",
                    lineHeight: 1,
                  }}
                >
                  {val}
                </span>
                <span
                  style={{
                    fontSize: 10,
                    color,
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.04em",
                    opacity: 0.75,
                  }}
                >
                  {label}
                </span>
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
        {totalTools === 0 && (
          <div
            style={{
              marginBottom: 10,
              border: "1px solid var(--border)",
              borderRadius: 10,
              background: "var(--canvas)",
              padding: "10px 12px",
            }}
          >
            <p style={{ margin: 0, fontSize: 12, color: "var(--t3)" }}>
              No tool grants are configured. Add MCP/connector operations per
              role to use Figma, Miro, GDrive, and similar tools.
            </p>
          </div>
        )}
        {roles.length === 0 ? (
          <div
            style={{
              textAlign: "center",
              padding: "28px 20px",
              border: "1px dashed var(--border)",
              borderRadius: 12,
            }}
          >
            <p style={{ fontSize: 13, color: "var(--t4)", margin: 0 }}>
              No agent models configured yet.
            </p>
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
              gap: 10,
            }}
          >
            {roles.map((role) => (
              <AgentRoleCard
                key={role}
                role={role}
                model={agentModels[role] || "not configured"}
                tools={agentTools[role] || []}
                onOpenSettings={onOpenSettings}
                onSave={onSaveRoleConfig}
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
          <div
            style={{
              textAlign: "center",
              padding: "24px 20px",
              border: "1px dashed var(--border)",
              borderRadius: 12,
            }}
          >
            <p style={{ fontSize: 13, color: "var(--t4)", margin: 0 }}>
              No connectors registered in control state.
            </p>
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
              gap: 8,
            }}
          >
            {connectors.map((c, i) => (
              <ConnectorCard
                key={`${c.name}-${i}`}
                connector={c}
                onOpenCapabilitiesForConnector={onOpenCapabilitiesForConnector}
                onAssignConnectorTools={onAssignConnectorTools}
                onInstallAndAssignConnectorTools={onInstallAndAssignConnectorTools}
                onRefreshIntegrations={onRefreshIntegrations}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Team personas ───────────────────────────────────────── */}
      <div>
        <div
          style={{
            marginBottom: 12,
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          <SectionHeader
            title="Team Personas"
            count={personas.length}
            description="Human members and their roles in the governance workflow."
          />
          {onSavePersonas && (
            <button
              type="button"
              className="ghost-btn"
              onClick={openAddPersona}
              style={{ fontSize: 12, padding: "5px 10px" }}
            >
              Add member
            </button>
          )}
        </div>
        {personaEditorOpen && onSavePersonas && (
          <div
            style={{
              marginBottom: 10,
              border: "1px solid var(--border)",
              borderRadius: 10,
              background: "var(--canvas)",
              padding: "10px 12px",
              display: "grid",
              gap: 8,
            }}
          >
            <div
              style={{ display: "grid", gridTemplateColumns: "1fr 180px 160px", gap: 8 }}
            >
              <input
                value={personaName}
                onChange={(e) => setPersonaName(e.target.value)}
                className="sb-thread-search"
                placeholder="Full name"
                style={{ fontSize: 12 }}
              />
              <select
                value={personaRole}
                onChange={(e) =>
                  setPersonaRole(e.target.value as PersonaMember["role"])
                }
                className="sb-thread-search"
                style={{ fontSize: 12 }}
              >
                <option value="admin">admin</option>
                <option value="tech_lead">tech lead</option>
                <option value="devops">devops</option>
                <option value="qa">qa</option>
                <option value="sre">sre</option>
                <option value="reviewer">reviewer</option>
              </select>
              <input
                value={personaTeam}
                onChange={(e) => setPersonaTeam(e.target.value)}
                className="sb-thread-search"
                placeholder="Team (optional)"
                style={{ fontSize: 12 }}
              />
            </div>
            {personaError && (
              <p style={{ margin: 0, fontSize: 11, color: "#dc2626" }}>
                {personaError}
              </p>
            )}
            <div style={{ display: "flex", gap: 8 }}>
              <button
                type="button"
                className="ghost-btn"
                onClick={() => void savePersona()}
                disabled={personaSaving}
                style={{ fontSize: 11, padding: "4px 8px" }}
              >
                {personaSaving
                  ? "Saving..."
                  : personaEditingId
                    ? "Save member"
                    : "Add member"}
              </button>
              <button
                type="button"
                className="ghost-btn"
                onClick={() => {
                  setPersonaEditorOpen(false);
                  setPersonaError("");
                }}
                disabled={personaSaving}
                style={{ fontSize: 11, padding: "4px 8px" }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
        {personas.length === 0 ? (
          <div
            style={{
              textAlign: "center",
              padding: "24px 20px",
              border: "1px dashed var(--border)",
              borderRadius: 12,
            }}
          >
            <p style={{ fontSize: 13, color: "var(--t4)", margin: 0 }}>
              No personas configured. Add team members via the control plane.
            </p>
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
              gap: 8,
            }}
          >
            {personas.map((p) => (
              <PersonaCard
                key={p.id}
                persona={p}
                onEdit={onSavePersonas ? openEditPersona : undefined}
                onRemove={onSavePersonas ? removePersona : undefined}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
