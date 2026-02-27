/* ------------------------------------------------------------------ */
/*  Settings — premium light-theme settings panel                      */
/* ------------------------------------------------------------------ */
import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, readJson } from "../api";
import LogViewer from "./LogViewer";
import type { EngineRuntimeConfig } from "../types";

/* ---- Types ---- */
interface ProviderInfo {
  configured: boolean;
  masked: string;
  key_env: string;
  label: string;
  link: string;
}

interface AvailableModel {
  id: string;
  label: string;
  provider: string;
  tier: string;
}

interface SettingsData {
  providers: Record<string, ProviderInfo>;
  default_model: string;
  agent_models: Record<string, string>;
  available_models: AvailableModel[];
  default_agent_models: Record<string, string>;
  agent_tools: Record<string, string[]>;
  plugins_policy: {
    enabled: boolean;
    enable_connector_tools: boolean;
    enable_mcp_tools: boolean;
    enable_action_tools: boolean;
    min_trust_level: string;
    dry_run: boolean;
    allow_approval_required_actions: boolean;
    allow_sensitive_payload_keys: boolean;
    allowed_plugin_ids: string[];
    allowed_connector_operations: string[];
    allowed_mcp_operations: string[];
    allowed_action_operations: string[];
  };
  ollama_url: string;
  custom_base_url: string;
  database: {
    backend: "sqlite" | "postgres";
    local_db_path: string;
    dsn_configured: boolean;
    dsn_masked: string;
  };
  yml_raw: string;
}

interface RuntimeCapabilities {
  orchestration: {
    parallel_agents: boolean;
    max_retries: number;
    consultation_enabled: boolean;
    replan: { enabled: boolean; max_replans_per_task: number; trigger_retry_count: number };
  };
  plugins: {
    enabled: boolean;
    enable_connector_tools: boolean;
    enable_mcp_tools: boolean;
    enable_action_tools: boolean;
    min_trust_level: string;
    dry_run: boolean;
  };
  runtime: {
    filesystem_sandbox: string;
    worktree_mode: string;
    worktree_root: string;
    debate_enabled: boolean;
    debate_max_rounds: number;
    quality_gate_enabled: boolean;
    memory_learning_enabled: boolean;
  };
  database?: { backend: string; local_path: string; dsn_configured: boolean };
}

interface IntegrationsPolicyResponse {
  policy: {
    plugins_enabled: boolean;
    enable_connector_tools: boolean;
    enable_mcp_tools: boolean;
    enable_action_tools: boolean;
    min_trust_level: string;
    allowed_plugin_ids: string[];
    allowed_connector_operations: string[];
    allowed_mcp_operations: string[];
    allowed_action_operations: string[];
    allow_approval_required_actions: boolean;
    allow_sensitive_payload_keys: boolean;
    dry_run: boolean;
  };
  plugins: Array<{
    plugin_id: string;
    name: string;
    trust_level: string;
    allowed: boolean;
    reasons: string[];
    connectors: Array<{ id: string; operations: string[]; allowed: boolean }>;
    mcp_servers: Array<{ id: string; operations: string[]; allowed: boolean }>;
    actions: Array<{ id: string; kind: string; requires_approval: boolean; allowed: boolean }>;
  }>;
}

interface SettingsProps { onBack: () => void }

const ROLE_META: Record<string, { label: string; desc: string; icon: string }> = {
  lead:     { label: "Lead",     desc: "Architecture decisions", icon: "\uD83C\uDFAF" },
  planner:  { label: "Planner",  desc: "Task decomposition",    icon: "\uD83D\uDCCB" },
  coder:    { label: "Coder",    desc: "Code implementation",   icon: "\uD83D\uDCBB" },
  reviewer: { label: "Reviewer", desc: "Code review",           icon: "\uD83D\uDD0D" },
  qa:       { label: "QA",       desc: "Test generation",       icon: "\u2705" },
  security: { label: "Security", desc: "Security audit",        icon: "\uD83D\uDD12" },
  devops:   { label: "DevOps",   desc: "Infrastructure config", icon: "\u2699\uFE0F" },
  sre:      { label: "SRE",      desc: "Reliability checks",    icon: "\uD83D\uDCCA" },
  docs:     { label: "Docs",     desc: "Documentation",         icon: "\uD83D\uDCD6" },
};

/* Fix 4 — human-readable tier labels for model selects */
const TIER_LABEL: Record<string, string> = {
  premium: "most capable",
  standard: "balanced",
  fast: "fastest",
  local: "local",
};

type TabId = "keys" | "agents" | "capabilities" | "storage" | "config" | "logs";
const TAB_LABELS: Record<TabId, string> = {
  keys: "API Keys",
  agents: "Agents",
  capabilities: "Capabilities",
  storage: "Storage",
  config: "Config",
  logs: "Logs",
};

/* Shared input class */
const INPUT_CLS =
  "w-full rounded-lg border bg-white px-3 py-2 text-sm font-mono outline-none transition-colors " +
  "placeholder:text-[var(--ui-text-subtle)] focus:border-[var(--ui-border-strong)] focus:ring-1 focus:ring-[rgba(0,0,0,0.06)]";
const inputBorder = { borderColor: "var(--ui-border)" };

/* ================================================================== */
export default function Settings({ onBack }: SettingsProps) {
  const [data, setData] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);
  const [tab, setTab] = useState<TabId>("keys");
  const [runtimeCaps, setRuntimeCaps] = useState<RuntimeCapabilities | null>(null);
  const [engineRuntime, setEngineRuntime] = useState<EngineRuntimeConfig | null>(null);

  const [keys, setKeys] = useState<Record<string, string>>({});
  const [keyEditing, setKeyEditing] = useState<string | null>(null);
  const [defaultModel, setDefaultModel] = useState("");
  const [agentModels, setAgentModels] = useState<Record<string, string>>({});
  const [agentTools, setAgentTools] = useState<Record<string, string[]>>({});
  const [pluginPolicy, setPluginPolicy] = useState<SettingsData["plugins_policy"] | null>(null);
  const [integrationsView, setIntegrationsView] = useState<IntegrationsPolicyResponse | null>(null);
  const [customBaseUrl, setCustomBaseUrl] = useState("");
  const [ollamaUrl, setOllamaUrl] = useState("");
  const [dbBackend, setDbBackend] = useState<"sqlite" | "postgres">("sqlite");
  const [dbLocalPath, setDbLocalPath] = useState(".rigovo/local.db");
  const [dbUrl, setDbUrl] = useState("");
  const [ymlRaw, setYmlRaw] = useState("");
  const [ymlView, setYmlView] = useState<"friendly" | "raw">("friendly");
  const ymlRef = useRef<HTMLTextAreaElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const res = await readJson<SettingsData>(`${API_BASE}/v1/settings`);
    if (res) {
      setData(res);
      setDefaultModel(res.default_model || "");
      setAgentModels({ ...res.agent_models });
      setAgentTools({ ...res.agent_tools });
      setPluginPolicy({ ...res.plugins_policy });
      setCustomBaseUrl(res.custom_base_url || "");
      setOllamaUrl(res.ollama_url || "http://localhost:11434");
      setDbBackend(res.database?.backend || "sqlite");
      setDbLocalPath(res.database?.local_db_path || ".rigovo/local.db");
      setDbUrl("");
      setYmlRaw(res.yml_raw || "");
    }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    void (async () => {
      const caps = await readJson<RuntimeCapabilities>(`${API_BASE}/v1/runtime/capabilities`);
      if (caps) setRuntimeCaps(caps);
      const integrations = await readJson<IntegrationsPolicyResponse>(`${API_BASE}/v1/integrations/policy`);
      if (integrations) setIntegrationsView(integrations);
      if (window.electronAPI?.engineRuntimeConfig) {
        try { setEngineRuntime(await window.electronAPI.engineRuntimeConfig()); } catch { /* */ }
      }
    })();
  }, []);

  const showToast = (msg: string, type: "success" | "error") => {
    setToast({ msg, type });
    window.setTimeout(() => setToast(null), type === "error" ? 8000 : 4000);
  };

  const save = async (payload: Record<string, unknown>) => {
    setSaving(true);
    try {
      const res = await fetch(`${API_BASE}/v1/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        const d = await res.json();
        showToast(`Saved. ${d.note || ""}`, "success");
        void load();
      } else {
        let detail = `HTTP ${res.status}`;
        try {
          const errBody = await res.json();
          if (typeof errBody?.detail === "string") detail = errBody.detail;
          else if (Array.isArray(errBody?.detail)) detail = errBody.detail.map((e: { msg?: string }) => e.msg || JSON.stringify(e)).join("; ");
          else if (errBody?.errors?.length) detail = errBody.errors.join("; ");
        } catch { /* */ }
        showToast(`Save failed: ${detail}`, "error");
      }
    } catch (e) {
      showToast(`Cannot reach API (${e instanceof Error ? e.message : "unknown"})`, "error");
    }
    setSaving(false);
  };

  const saveKey = (provider: string, value: string) => {
    void save({ api_keys: { [provider]: value } });
    setKeyEditing(null);
    setKeys((prev) => ({ ...prev, [provider]: "" }));
  };
  const saveAgentModels = () => void save({ default_model: defaultModel, agent_models: agentModels });
  const parseCsvList = (v: string): string[] => v.split(",").map((x) => x.trim()).filter(Boolean);
  const saveCapabilities = () => { if (pluginPolicy) void save({ agent_tools: agentTools, plugin_policy: pluginPolicy }); };
  const saveEndpoints = () => {
    const payload: Record<string, unknown> = {};
    if (customBaseUrl !== (data?.custom_base_url || "")) payload.custom_base_url = customBaseUrl;
    if (ollamaUrl !== (data?.ollama_url || "")) payload.ollama_url = ollamaUrl;
    if (Object.keys(payload).length) void save(payload);
    else showToast("No endpoint changes to save.", "success");
  };
  const saveDatabase = () => {
    const payload: Record<string, unknown> = { db_backend: dbBackend, local_db_path: dbLocalPath };
    if (dbBackend === "postgres") payload.db_url = dbUrl; else payload.db_url = "";
    void save(payload);
    if (dbBackend === "postgres") setDbUrl("");
  };
  const saveYml = () => void save({ yml_raw: ymlRaw });
  const parseYmlSections = (raw: string): { key: string; value: string }[] => {
    if (!raw.trim()) return [];
    const sections: { key: string; value: string }[] = [];
    const lines = raw.split("\n");
    let currentKey = "";
    let currentLines: string[] = [];
    for (const line of lines) {
      if (/^[a-zA-Z_][a-zA-Z0-9_]*:/.test(line)) {
        if (currentKey) sections.push({ key: currentKey, value: currentLines.join("\n") });
        currentKey = line.split(":")[0].trim();
        currentLines = [line];
      } else {
        currentLines.push(line);
      }
    }
    if (currentKey) sections.push({ key: currentKey, value: currentLines.join("\n") });
    return sections;
  };

  /* ---- Loading state ---- */
  if (loading || !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin h-5 w-5 rounded-full border-2 border-t-transparent" style={{ borderColor: "var(--ui-border-strong)", borderTopColor: "transparent" }} />
      </div>
    );
  }

  const providerEntries = Object.entries(data.providers);

  return (
    <div className="w-full py-6 px-6 animate-fadeup">
      {/* Header */}
      <div className="flex items-center gap-3 mb-5">
        <button type="button" onClick={onBack}
          className="flex h-7 w-7 items-center justify-center rounded-lg transition-colors hover:bg-[rgba(0,0,0,0.04)]"
          style={{ color: "var(--ui-text-muted)" }}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M10 12L6 8L10 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </button>
        <h1 className="text-lg font-semibold" style={{ color: "var(--ui-text)" }}>Settings</h1>
      </div>

      {/* Tabs */}
      <div className="flex gap-0.5 rounded-xl p-0.5 mb-5" style={{ background: "rgba(0,0,0,0.04)" }}>
        {(Object.keys(TAB_LABELS) as TabId[]).map((t) => (
          <button key={t} type="button" onClick={() => setTab(t)}
            className={`flex-1 py-2 px-3 text-xs font-medium rounded-lg transition-all ${
              tab === t
                ? "bg-white text-[var(--ui-text)] shadow-sm"
                : "text-[var(--ui-text-muted)] hover:text-[var(--ui-text-secondary)]"
            }`}>
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>

      {/* Toast */}
      {toast && (
        <div className={`mb-4 rounded-xl px-4 py-2.5 text-sm animate-fadeup border flex items-center justify-between ${
          toast.type === "error"
            ? "bg-[rgba(244,63,94,0.05)] border-[rgba(244,63,94,0.12)] text-[#be123c]"
            : "bg-[rgba(16,185,129,0.05)] border-[rgba(16,185,129,0.12)] text-[#047857]"
        }`}>
          <span>{toast.type === "error" && <span className="font-semibold mr-1.5">Error:</span>}{toast.msg}</span>
          <button type="button" onClick={() => setToast(null)} className="ml-3 opacity-50 hover:opacity-80 text-xs">&#10005;</button>
        </div>
      )}

      {/* ──────────── API Keys ──────────── */}
      {tab === "keys" && (
        <div className="space-y-3">
          <p className="text-sm mb-2" style={{ color: "var(--ui-text-muted)" }}>
            API keys are encrypted at rest in your local database. Never sent to Rigovo's servers.
          </p>

          {/* Fix 5: skip the Ollama provider card — it has no key input and confuses users.
              Ollama is handled by its own URL card below. */}
          {providerEntries.filter(([provider]) => provider !== "ollama").map(([provider, info]) => {
            const isEditing = keyEditing === provider;
            return (
              <div key={provider} className="rounded-xl border bg-white p-4" style={{ borderColor: "var(--ui-border)" }}>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2.5">
                    <div className={`h-2 w-2 rounded-full ${info.configured ? "bg-emerald-500" : "bg-[rgba(0,0,0,0.15)]"}`} />
                    <span className="text-sm font-medium" style={{ color: "var(--ui-text)" }}>{info.label}</span>
                    {info.configured && (
                      <span className="text-[10px] font-medium px-1.5 py-0.5 rounded" style={{ background: "rgba(16,185,129,0.08)", color: "#047857" }}>active</span>
                    )}
                  </div>
                  <a href={info.link} target="_blank" rel="noreferrer"
                    className="text-xs font-medium transition-colors hover:underline" style={{ color: "var(--ui-text-muted)" }}>
                    Get key ↗
                  </a>
                </div>

                {!isEditing ? (
                  <div className="flex items-center gap-3">
                    <div className="flex-1 rounded-lg px-3 py-2 text-sm font-mono" style={{ background: "rgba(0,0,0,0.03)", color: info.configured ? "var(--ui-text-secondary)" : "var(--ui-text-subtle)" }}>
                      {info.configured ? info.masked : "Not configured"}
                    </div>
                    <button type="button" onClick={() => setKeyEditing(provider)}
                      className="px-3 py-2 text-xs font-medium rounded-lg border transition-colors hover:bg-[rgba(0,0,0,0.02)]"
                      style={{ borderColor: "var(--ui-border-strong)", color: "var(--ui-text-secondary)" }}>
                      {info.configured ? "Update" : "Add key"}
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <input type="password" autoFocus
                      placeholder={`Paste your ${info.label} API key...`}
                      value={keys[provider] || ""}
                      onChange={(e) => setKeys((prev) => ({ ...prev, [provider]: e.target.value }))}
                      className={INPUT_CLS} style={inputBorder} />
                    <button type="button" disabled={saving || !keys[provider]?.trim()}
                      onClick={() => saveKey(provider, keys[provider] || "")}
                      className="primary-btn px-3 py-2 text-xs">Save</button>
                    <button type="button"
                      onClick={() => { setKeyEditing(null); setKeys((p) => ({ ...p, [provider]: "" })); }}
                      className="ghost-btn px-3 py-2 text-xs">Cancel</button>
                  </div>
                )}
              </div>
            );
          })}

          {/* Custom endpoint */}
          <div className="rounded-xl border bg-white p-4" style={{ borderColor: "var(--ui-border)" }}>
            <div className="flex items-center gap-2.5 mb-3">
              <div className={`h-2 w-2 rounded-full ${customBaseUrl ? "bg-emerald-500" : "bg-[rgba(0,0,0,0.15)]"}`} />
              <span className="text-sm font-medium" style={{ color: "var(--ui-text)" }}>Custom Endpoint</span>
              <span className="text-[10px] font-medium px-1.5 py-0.5 rounded" style={{ background: "rgba(0,0,0,0.04)", color: "var(--ui-text-subtle)" }}>OpenAI-compatible</span>
            </div>
            <p className="text-xs mb-3" style={{ color: "var(--ui-text-muted)" }}>
              Use any OpenAI-compatible API (vLLM, LiteLLM, Azure, etc.).
            </p>
            <div className="flex items-center gap-2">
              <input type="url" placeholder="https://your-api.example.com/v1" value={customBaseUrl}
                onChange={(e) => setCustomBaseUrl(e.target.value)} className={INPUT_CLS} style={inputBorder} />
              <button type="button" disabled={saving} onClick={saveEndpoints} className="ghost-btn px-3 py-2 text-xs">Save</button>
            </div>
          </div>

          {/* Fix 5: Ollama as a first-class provider card with URL field */}
          <div className="rounded-xl border bg-white p-4" style={{ borderColor: "var(--ui-border)" }}>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2.5">
                <div className={`h-2 w-2 rounded-full ${ollamaUrl && ollamaUrl !== "http://localhost:11434" ? "bg-emerald-500" : "bg-[rgba(0,0,0,0.15)]"}`} />
                <span className="text-sm font-medium" style={{ color: "var(--ui-text)" }}>Ollama</span>
                <span className="text-[10px] font-medium px-1.5 py-0.5 rounded" style={{ background: "rgba(0,0,0,0.04)", color: "var(--ui-text-subtle)" }}>local</span>
              </div>
              <a href="https://ollama.com" target="_blank" rel="noreferrer"
                className="text-xs font-medium transition-colors hover:underline" style={{ color: "var(--ui-text-muted)" }}>
                Install ↗
              </a>
            </div>
            <p className="text-xs mb-3" style={{ color: "var(--ui-text-muted)" }}>
              Run models locally — no API key needed. Install Ollama, pull a model (e.g.{" "}
              <code className="rounded px-1 py-0.5 text-[11px]" style={{ background: "rgba(0,0,0,0.04)" }}>ollama pull llama3</code>),
              then set agent models to <code className="rounded px-1 py-0.5 text-[11px]" style={{ background: "rgba(0,0,0,0.04)" }}>llama3</code> in the Agents tab.
            </p>
            <div className="flex items-center gap-2">
              <input type="url" placeholder="http://localhost:11434" value={ollamaUrl}
                onChange={(e) => setOllamaUrl(e.target.value)} className={INPUT_CLS} style={inputBorder} />
              <button type="button" disabled={saving} onClick={saveEndpoints} className="ghost-btn px-3 py-2 text-xs">Save</button>
            </div>
          </div>
        </div>
      )}

      {/* ──────────── Agents ──────────── */}
      {tab === "agents" && (
        <div className="space-y-3">
          <p className="text-sm mb-2" style={{ color: "var(--ui-text-muted)" }}>
            Choose which LLM powers each agent role. The default model is used for any role without an override.
          </p>

          {/* Default model — Fix 1: was fetched but never shown */}
          <div className="rounded-xl border bg-white p-4" style={{ borderColor: "var(--ui-border)" }}>
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium" style={{ color: "var(--ui-text)" }}>Default model</p>
                <p className="text-xs mt-0.5" style={{ color: "var(--ui-text-muted)" }}>
                  Fallback for any agent that has no role-specific override below.
                </p>
              </div>
              <select
                value={defaultModel}
                onChange={(e) => setDefaultModel(e.target.value)}
                className="rounded-lg border bg-white px-3 py-2 text-sm outline-none transition-colors min-w-[200px] cursor-pointer"
                style={{ borderColor: "var(--ui-border)", color: "var(--ui-text-secondary)" }}
              >
                {data.available_models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}{TIER_LABEL[m.tier] ? ` — ${TIER_LABEL[m.tier]}` : ""}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {Object.entries(ROLE_META).map(([role, meta]) => {
            const current = agentModels[role] || data.default_agent_models[role] || defaultModel || "claude-sonnet-4-6";
            const isDefault = !agentModels[role] || agentModels[role] === data.default_agent_models[role];
            return (
              <div key={role} className="rounded-xl border bg-white p-4" style={{ borderColor: "var(--ui-border)" }}>
                <div className="flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-base">{meta.icon}</span>
                      <span className="text-sm font-medium" style={{ color: "var(--ui-text)" }}>{meta.label}</span>
                      {isDefault && (
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded" style={{ background: "rgba(0,0,0,0.04)", color: "var(--ui-text-subtle)" }}>default</span>
                      )}
                    </div>
                    <p className="text-xs mt-0.5 ml-7" style={{ color: "var(--ui-text-muted)" }}>{meta.desc}</p>
                  </div>
                  <select value={current}
                    onChange={(e) => setAgentModels((prev) => ({ ...prev, [role]: e.target.value }))}
                    className="rounded-lg border bg-white px-3 py-2 text-sm outline-none transition-colors min-w-[180px] cursor-pointer"
                    style={{ borderColor: "var(--ui-border)", color: "var(--ui-text-secondary)" }}>
                    {data.available_models.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}{TIER_LABEL[m.tier] ? ` — ${TIER_LABEL[m.tier]}` : ""}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            );
          })}
          <div className="flex justify-end pt-2">
            <button type="button" disabled={saving} onClick={saveAgentModels} className="primary-btn">
              {saving ? "Saving..." : "Save agent models"}
            </button>
          </div>
        </div>
      )}

      {/* ──────────── Capabilities ──────────── */}
      {tab === "capabilities" && (
        <div className="space-y-4">
          <p className="text-sm" style={{ color: "var(--ui-text-muted)" }}>
            Configure global integration policy and per-agent tool permissions.
          </p>

          {pluginPolicy && (
            <div className="rounded-xl border bg-white p-4 space-y-3" style={{ borderColor: "var(--ui-border)" }}>
              <p className="text-sm font-medium" style={{ color: "var(--ui-text)" }}>Global plugin policy</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
                {([
                  ["enabled", "Plugins enabled"],
                  ["enable_connector_tools", "Connector tools"],
                  ["enable_mcp_tools", "MCP tools"],
                  ["enable_action_tools", "Action tools"],
                  ["dry_run", "Dry run mode"],
                  ["allow_approval_required_actions", "Allow approval-required actions"],
                  ["allow_sensitive_payload_keys", "Allow sensitive payload keys"],
                ] as Array<[keyof SettingsData["plugins_policy"], string]>).map(([key, label]) => (
                  <label key={key} className="rounded-lg px-3 py-2 flex items-center justify-between" style={{ background: "rgba(0,0,0,0.02)" }}>
                    <span style={{ color: "var(--ui-text-secondary)" }}>{label}</span>
                    <input type="checkbox" checked={Boolean(pluginPolicy[key])}
                      onChange={(e) => setPluginPolicy((prev) => prev ? { ...prev, [key]: e.target.checked } : prev)} />
                  </label>
                ))}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                <label className="rounded-lg px-3 py-2 text-xs" style={{ background: "rgba(0,0,0,0.02)", color: "var(--ui-text-secondary)" }}>
                  Trust floor
                  <select value={pluginPolicy.min_trust_level}
                    onChange={(e) => setPluginPolicy((prev) => prev ? { ...prev, min_trust_level: e.target.value } : prev)}
                    className="mt-1 w-full rounded border bg-white px-2 py-1 text-xs" style={{ borderColor: "var(--ui-border)", color: "var(--ui-text)" }}>
                    <option value="community">community</option>
                    <option value="verified">verified</option>
                    <option value="internal">internal</option>
                  </select>
                </label>
                <label className="rounded-lg px-3 py-2 text-xs" style={{ background: "rgba(0,0,0,0.02)", color: "var(--ui-text-secondary)" }}>
                  Allowed plugin ids
                  <input type="text" value={pluginPolicy.allowed_plugin_ids.join(", ")}
                    onChange={(e) => setPluginPolicy((prev) => prev ? { ...prev, allowed_plugin_ids: parseCsvList(e.target.value) } : prev)}
                    className="mt-1 w-full rounded border bg-white px-2 py-1 text-xs font-mono" style={{ borderColor: "var(--ui-border)", color: "var(--ui-text)" }} />
                </label>
                <label className="rounded-lg px-3 py-2 text-xs" style={{ background: "rgba(0,0,0,0.02)", color: "var(--ui-text-secondary)" }}>
                  Connector ops
                  <input type="text" value={pluginPolicy.allowed_connector_operations.join(", ")}
                    onChange={(e) => setPluginPolicy((prev) => prev ? { ...prev, allowed_connector_operations: parseCsvList(e.target.value) } : prev)}
                    className="mt-1 w-full rounded border bg-white px-2 py-1 text-xs font-mono" style={{ borderColor: "var(--ui-border)", color: "var(--ui-text)" }} />
                </label>
                <label className="rounded-lg px-3 py-2 text-xs" style={{ background: "rgba(0,0,0,0.02)", color: "var(--ui-text-secondary)" }}>
                  MCP ops
                  <input type="text" value={pluginPolicy.allowed_mcp_operations.join(", ")}
                    onChange={(e) => setPluginPolicy((prev) => prev ? { ...prev, allowed_mcp_operations: parseCsvList(e.target.value) } : prev)}
                    className="mt-1 w-full rounded border bg-white px-2 py-1 text-xs font-mono" style={{ borderColor: "var(--ui-border)", color: "var(--ui-text)" }} />
                </label>
                <label className="rounded-lg px-3 py-2 text-xs md:col-span-2" style={{ background: "rgba(0,0,0,0.02)", color: "var(--ui-text-secondary)" }}>
                  Action ops
                  <input type="text" value={pluginPolicy.allowed_action_operations.join(", ")}
                    onChange={(e) => setPluginPolicy((prev) => prev ? { ...prev, allowed_action_operations: parseCsvList(e.target.value) } : prev)}
                    className="mt-1 w-full rounded border bg-white px-2 py-1 text-xs font-mono" style={{ borderColor: "var(--ui-border)", color: "var(--ui-text)" }} />
                </label>
              </div>
            </div>
          )}

          {/* Agent tool matrix */}
          <div className="rounded-xl border bg-white p-4 space-y-3" style={{ borderColor: "var(--ui-border)" }}>
            <p className="text-sm font-medium" style={{ color: "var(--ui-text)" }}>Agent tool matrix</p>
            <div className="space-y-2">
              {Object.entries(ROLE_META).map(([role, meta]) => (
                <label key={role} className="block rounded-lg px-3 py-2 text-xs" style={{ background: "rgba(0,0,0,0.02)" }}>
                  <span className="font-medium" style={{ color: "var(--ui-text-secondary)" }}>{meta.label}</span>
                  <input type="text" value={(agentTools[role] || []).join(", ")}
                    onChange={(e) => setAgentTools((prev) => ({ ...prev, [role]: parseCsvList(e.target.value) }))}
                    placeholder="read_file, write_file, invoke_integration"
                    className="mt-1 w-full rounded border bg-white px-2 py-1 text-xs font-mono" style={{ borderColor: "var(--ui-border)", color: "var(--ui-text)" }} />
                </label>
              ))}
            </div>
          </div>

          {/* Loaded integrations */}
          <div className="rounded-xl border bg-white p-4" style={{ borderColor: "var(--ui-border)" }}>
            <p className="text-xs font-medium uppercase tracking-wider mb-2" style={{ color: "var(--ui-text-subtle)" }}>Loaded integrations</p>
            {!integrationsView?.plugins?.length ? (
              <p className="text-xs" style={{ color: "var(--ui-text-subtle)" }}>No plugins loaded.</p>
            ) : (
              <div className="space-y-2">
                {integrationsView.plugins.map((p) => (
                  <div key={p.plugin_id} className="rounded-lg border px-3 py-2" style={{ borderColor: "var(--ui-border)", background: "rgba(0,0,0,0.015)" }}>
                    <p className="text-xs" style={{ color: "var(--ui-text)" }}>
                      {p.name} <span style={{ color: "var(--ui-text-subtle)" }}>({p.plugin_id})</span>
                    </p>
                    <p className="text-[10px]" style={{ color: "var(--ui-text-subtle)" }}>
                      trust={p.trust_level} &middot; {p.allowed ? "allowed" : `blocked (${(p.reasons || []).join(", ") || "policy"})`}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="flex justify-end">
            <button type="button" disabled={saving} onClick={saveCapabilities} className="primary-btn">
              {saving ? "Saving..." : "Save capability policy"}
            </button>
          </div>
        </div>
      )}

      {/* ──────────── Storage ──────────── */}
      {tab === "storage" && (
        <div className="space-y-4">
          <p className="text-sm" style={{ color: "var(--ui-text-muted)" }}>
            Configure where task history, audit logs, and memory artifacts are stored.
          </p>

          <div className="rounded-xl border bg-white p-4 space-y-3" style={{ borderColor: "var(--ui-border)" }}>
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium" style={{ color: "var(--ui-text)" }}>Database backend</p>
                <p className="text-xs" style={{ color: "var(--ui-text-muted)" }}>Switch between local SQLite and external PostgreSQL.</p>
              </div>
              <select value={dbBackend} onChange={(e) => setDbBackend(e.target.value === "postgres" ? "postgres" : "sqlite")}
                className="rounded-lg border bg-white px-3 py-2 text-sm outline-none cursor-pointer min-w-[180px]"
                style={{ borderColor: "var(--ui-border)", color: "var(--ui-text-secondary)" }}>
                <option value="sqlite">SQLite (local file)</option>
                <option value="postgres">PostgreSQL (DSN)</option>
              </select>
            </div>
            <div className="rounded-lg px-3 py-2 text-xs" style={{ background: "rgba(0,0,0,0.02)", color: "var(--ui-text-muted)" }}>
              Current: <span style={{ color: "var(--ui-text)" }}>{data.database.backend}</span>
            </div>
          </div>

          {/* Fix 2: show only the relevant field for the selected backend */}
          {dbBackend === "sqlite" ? (
            <div className="rounded-xl border bg-white p-4 space-y-3" style={{ borderColor: "var(--ui-border)" }}>
              <div>
                <p className="text-sm font-medium" style={{ color: "var(--ui-text)" }}>SQLite file path</p>
                <p className="text-xs mt-0.5" style={{ color: "var(--ui-text-muted)" }}>
                  Relative to project root. The file is created automatically on first run.
                </p>
              </div>
              <input type="text" value={dbLocalPath} onChange={(e) => setDbLocalPath(e.target.value)}
                placeholder=".rigovo/local.db" className={INPUT_CLS} style={inputBorder} />
            </div>
          ) : (
            <div className="rounded-xl border bg-white p-4 space-y-3" style={{ borderColor: "var(--ui-border)" }}>
              <div>
                <p className="text-sm font-medium" style={{ color: "var(--ui-text)" }}>PostgreSQL connection string</p>
                <p className="text-xs mt-0.5" style={{ color: "var(--ui-text-muted)" }}>
                  Stored encrypted. Existing SQLite data is not migrated automatically.
                </p>
              </div>
              <input type="password" value={dbUrl} onChange={(e) => setDbUrl(e.target.value)}
                placeholder="postgresql://user:pass@host:5432/dbname" className={INPUT_CLS} style={inputBorder} />
              <p className="text-xs" style={{ color: "var(--ui-text-subtle)" }}>
                Current: {data.database.dsn_configured ? data.database.dsn_masked : "not configured"}
              </p>
            </div>
          )}

          <div className="flex justify-end">
            <button type="button" disabled={saving} onClick={saveDatabase} className="primary-btn">
              {saving ? "Saving..." : "Save storage settings"}
            </button>
          </div>
        </div>
      )}

      {/* ──────────── Config ──────────── */}
      {tab === "config" && (
        <div className="space-y-4">
          <div className="rounded-xl border bg-white p-4" style={{ borderColor: "var(--ui-border)" }}>
            <p className="text-xs font-medium uppercase tracking-wider mb-2" style={{ color: "var(--ui-text-subtle)" }}>Runtime Guardrails</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
              {[
                ["Electron sandbox", engineRuntime?.electronSandbox ? "enabled" : "disabled"],
                ["Worktree mode", engineRuntime?.worktreeMode ?? runtimeCaps?.runtime.worktree_mode ?? "project"],
                ["File sandbox", runtimeCaps?.runtime.filesystem_sandbox ?? "project_root"],
                ["Plugin trust floor", runtimeCaps?.plugins.min_trust_level ?? "verified"],
                ["Parallel agents", runtimeCaps?.orchestration.parallel_agents ? "on" : "off"],
                ["Consultation", runtimeCaps?.orchestration.consultation_enabled ? "on" : "off"],
                ["Replan policy", runtimeCaps?.orchestration.replan.enabled ? "enabled" : "disabled"],
                ["Debate loop", runtimeCaps?.runtime.debate_enabled ? `on (max ${runtimeCaps.runtime.debate_max_rounds})` : "off"],
                ["DB backend", runtimeCaps?.database?.backend ?? data.database.backend],
              ].map(([label, val]) => (
                <div key={label} className="rounded-lg px-3 py-2" style={{ background: "rgba(0,0,0,0.02)", color: "var(--ui-text-muted)" }}>
                  {label}: <span style={{ color: "var(--ui-text)" }}>{val}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="flex items-center justify-between mb-2">
            <p className="text-sm" style={{ color: "var(--ui-text-muted)" }}>
              <code className="text-xs rounded px-1.5 py-0.5" style={{ background: "rgba(0,0,0,0.04)" }}>rigovo.yml</code>
            </p>
            <div className="flex gap-0.5 rounded-lg p-0.5" style={{ background: "rgba(0,0,0,0.04)" }}>
              {(["friendly", "raw"] as const).map((v) => (
                <button key={v} type="button" onClick={() => setYmlView(v)}
                  className={`px-2.5 py-1 text-xs font-medium rounded-md transition-all ${
                    ymlView === v ? "bg-white shadow-sm text-[var(--ui-text)]" : "text-[var(--ui-text-muted)]"
                  }`}>
                  {v === "friendly" ? "Friendly" : "Raw YAML"}
                </button>
              ))}
            </div>
          </div>

          {ymlView === "friendly" ? (
            <div className="space-y-2">
              {/* Fix 3: make read-only nature explicit + give clear path to editing */}
              <div className="rounded-lg px-3 py-2 flex items-center justify-between text-xs"
                style={{ background: "rgba(0,0,0,0.02)", color: "var(--ui-text-muted)" }}>
                <span>Read-only preview. Switch to Raw YAML to edit.</span>
                <button type="button" onClick={() => setYmlView("raw")}
                  className="underline font-medium" style={{ color: "var(--ui-text-secondary)" }}>
                  Edit in Raw YAML →
                </button>
              </div>
              {parseYmlSections(ymlRaw).filter(({ key }) => !key.startsWith("#")).map(({ key, value }) => (
                <details key={key} className="rounded-xl border bg-white group" style={{ borderColor: "var(--ui-border)" }}>
                  <summary className="cursor-pointer px-4 py-3 flex items-center gap-2 text-sm font-medium transition-colors" style={{ color: "var(--ui-text)" }}>
                    <span className="text-[10px] transition group-open:rotate-90" style={{ color: "var(--ui-text-subtle)" }}>&#9654;</span>
                    <span className="capitalize">{key.replace(/_/g, " ")}</span>
                    <span className="text-[10px] ml-auto font-mono" style={{ color: "var(--ui-text-subtle)" }}>{key}:</span>
                  </summary>
                  <div className="px-4 pb-3 border-t pt-3" style={{ borderColor: "var(--ui-border)" }}>
                    <pre className="text-xs font-mono whitespace-pre-wrap overflow-x-auto" style={{ color: "var(--ui-text-secondary)" }}>{value}</pre>
                  </div>
                </details>
              ))}
            </div>
          ) : (
            <div className="space-y-3">
              <textarea ref={ymlRef} value={ymlRaw} onChange={(e) => setYmlRaw(e.target.value)} spellCheck={false}
                className="w-full h-80 rounded-xl border bg-white px-4 py-3 text-sm font-mono outline-none resize-y"
                style={{ borderColor: "var(--ui-border)", color: "var(--ui-text)" }}
                placeholder="# rigovo.yml" />
              <div className="flex justify-end">
                <button type="button" disabled={saving} onClick={saveYml} className="primary-btn">
                  {saving ? "Saving..." : "Save config"}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ──────────── Logs ──────────── */}
      {tab === "logs" && <LogViewer onBack={onBack} />}
    </div>
  );
}
