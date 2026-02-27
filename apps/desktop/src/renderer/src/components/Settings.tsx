/* ------------------------------------------------------------------ */
/*  Settings — API keys, per-agent models, config editor, logs         */
/*  Talks to GET/POST /v1/settings on the control-plane backend        */
/* ------------------------------------------------------------------ */
import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, readJson } from "../api";
import LogViewer from "./LogViewer";
import type { EngineRuntimeConfig } from "../types";

/* ---- Types (match backend response) ---- */
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
    replan: {
      enabled: boolean;
      max_replans_per_task: number;
      trigger_retry_count: number;
    };
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
  database?: {
    backend: string;
    local_path: string;
    dsn_configured: boolean;
  };
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

interface SettingsProps {
  onBack: () => void;
}

/* ---- Agent role metadata ---- */
const ROLE_META: Record<string, { label: string; desc: string; icon: string }> = {
  lead:     { label: "Lead",      desc: "Architecture decisions",  icon: "\uD83C\uDFAF" },
  planner:  { label: "Planner",   desc: "Task decomposition",     icon: "\uD83D\uDCCB" },
  coder:    { label: "Coder",     desc: "Code implementation",    icon: "\uD83D\uDCBB" },
  reviewer: { label: "Reviewer",  desc: "Code review",            icon: "\uD83D\uDD0D" },
  qa:       { label: "QA",        desc: "Test generation",        icon: "\u2705" },
  security: { label: "Security",  desc: "Security audit",         icon: "\uD83D\uDD12" },
  devops:   { label: "DevOps",    desc: "Infrastructure config",  icon: "\u2699\uFE0F" },
  sre:      { label: "SRE",       desc: "Reliability checks",     icon: "\uD83D\uDCCA" },
  docs:     { label: "Docs",      desc: "Documentation",          icon: "\uD83D\uDCD6" },
};

const TIER_COLORS: Record<string, string> = {
  premium:  "text-amber-400",
  standard: "text-brand-light",
  budget:   "text-slate-400",
  local:    "text-blue-400",
};

/* ================================================================== */
/*  Component                                                          */
/* ================================================================== */
export default function Settings({ onBack }: SettingsProps) {
  const [data, setData] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);
  const [tab, setTab] = useState<"keys" | "agents" | "capabilities" | "storage" | "config" | "logs">("keys");
  const [runtimeCaps, setRuntimeCaps] = useState<RuntimeCapabilities | null>(null);
  const [engineRuntime, setEngineRuntime] = useState<EngineRuntimeConfig | null>(null);

  /* Editable state — keys */
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [keyEditing, setKeyEditing] = useState<string | null>(null);

  /* Editable state — agent models */
  const [agentModels, setAgentModels] = useState<Record<string, string>>({});
  const [agentTools, setAgentTools] = useState<Record<string, string[]>>({});
  const [pluginPolicy, setPluginPolicy] = useState<SettingsData["plugins_policy"] | null>(null);
  const [integrationsView, setIntegrationsView] = useState<IntegrationsPolicyResponse | null>(null);

  /* Editable state — custom endpoint */
  const [customBaseUrl, setCustomBaseUrl] = useState("");
  const [ollamaUrl, setOllamaUrl] = useState("");
  const [dbBackend, setDbBackend] = useState<"sqlite" | "postgres">("sqlite");
  const [dbLocalPath, setDbLocalPath] = useState(".rigovo/local.db");
  const [dbUrl, setDbUrl] = useState("");

  /* Editable state — config editor */
  const [ymlRaw, setYmlRaw] = useState("");
  const [ymlView, setYmlView] = useState<"friendly" | "raw">("friendly");
  const ymlRef = useRef<HTMLTextAreaElement>(null);

  /* ---- Load settings ---- */
  const load = useCallback(async () => {
    setLoading(true);
    const res = await readJson<SettingsData>(`${API_BASE}/v1/settings`);
    if (res) {
      setData(res);
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
        try {
          const cfg = await window.electronAPI.engineRuntimeConfig();
          setEngineRuntime(cfg);
        } catch {
          // ignore when running in browser-only mode
        }
      }
    })();
  }, []);

  /* ---- Save helper ---- */
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
          if (typeof errBody?.detail === "string") {
            detail = errBody.detail;
          } else if (Array.isArray(errBody?.detail)) {
            // Pydantic validation errors come as array of objects
            detail = errBody.detail.map((e: { msg?: string }) => e.msg || JSON.stringify(e)).join("; ");
          } else if (errBody?.errors?.length) {
            detail = errBody.errors.join("; ");
          }
        } catch { /* ignore parse errors */ }
        showToast(`Save failed: ${detail}`, "error");
      }
    } catch (e) {
      showToast(`Cannot reach API — is the backend running? (${e instanceof Error ? e.message : "unknown"})`, "error");
    }
    setSaving(false);
  };

  /* ---- Action handlers ---- */
  const saveKey = (provider: string, value: string) => {
    void save({ api_keys: { [provider]: value } });
    setKeyEditing(null);
    setKeys((prev) => ({ ...prev, [provider]: "" }));
  };

  const saveAgentModels = () => void save({ agent_models: agentModels });

  const parseCsvList = (v: string): string[] =>
    v.split(",").map((x) => x.trim()).filter(Boolean);

  const saveCapabilities = () => {
    if (!pluginPolicy) return;
    void save({
      agent_tools: agentTools,
      plugin_policy: pluginPolicy,
    });
  };

  const saveEndpoints = () => {
    const payload: Record<string, unknown> = {};
    if (customBaseUrl !== (data?.custom_base_url || "")) payload.custom_base_url = customBaseUrl;
    if (ollamaUrl !== (data?.ollama_url || "")) payload.ollama_url = ollamaUrl;
    if (Object.keys(payload).length) void save(payload);
    else showToast("No endpoint changes to save.", "success");
  };

  const saveDatabase = () => {
    const payload: Record<string, unknown> = {
      db_backend: dbBackend,
      local_db_path: dbLocalPath,
    };
    if (dbBackend === "postgres") {
      payload.db_url = dbUrl;
    } else {
      payload.db_url = "";
    }
    void save(payload);
    if (dbBackend === "postgres") {
      setDbUrl("");
    }
  };

  const saveYml = () => void save({ yml_raw: ymlRaw });

  /* ---- Parse yml for friendly view ---- */
  const parseYmlSections = (raw: string): { key: string; value: string }[] => {
    if (!raw.trim()) return [];
    const sections: { key: string; value: string }[] = [];
    const lines = raw.split("\n");
    let currentKey = "";
    let currentLines: string[] = [];

    for (const line of lines) {
      // Top-level key (no indentation, ends with colon)
      if (/^[a-zA-Z_][a-zA-Z0-9_]*:/.test(line)) {
        if (currentKey) {
          sections.push({ key: currentKey, value: currentLines.join("\n") });
        }
        currentKey = line.split(":")[0].trim();
        currentLines = [line];
      } else {
        currentLines.push(line);
      }
    }
    if (currentKey) sections.push({ key: currentKey, value: currentLines.join("\n") });
    return sections;
  };

  /* ---- Render ---- */
  if (loading || !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin h-6 w-6 border-2 border-brand border-t-transparent rounded-full" />
      </div>
    );
  }

  const providerEntries = Object.entries(data.providers);

  return (
    <div className="w-full py-6 px-6 animate-fadeup">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <button type="button" onClick={onBack}
          className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white transition">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M10 12L6 8L10 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </button>
        <h1 className="text-lg font-semibold text-slate-100">Settings</h1>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-white/5 rounded-xl p-1 mb-6">
        {(["keys", "agents", "capabilities", "storage", "config", "logs"] as const).map((t) => (
          <button key={t} type="button" onClick={() => setTab(t)}
            className={`flex-1 py-2 px-3 text-sm font-medium rounded-lg transition ${
              tab === t
                ? "bg-brand text-white shadow-lg shadow-brand/20"
                : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
            }`}>
            {t === "keys" ? "API Keys" : t === "agents" ? "Agents" : t === "capabilities" ? "Capabilities" : t === "storage" ? "Storage" : t === "config" ? "Config" : "Logs"}
          </button>
        ))}
      </div>

      {/* Toast */}
      {toast && (
        <div className={`mb-4 rounded-xl px-4 py-2.5 text-sm animate-fadeup border flex items-center justify-between ${
          toast.type === "error"
            ? "bg-rose-500/10 border-rose-500/20 text-rose-400"
            : "bg-emerald-500/10 border-emerald-500/20 text-emerald-400"
        }`}>
          <span>
            {toast.type === "error" && <span className="font-semibold mr-1.5">Error:</span>}
            {toast.msg}
          </span>
          <button type="button" onClick={() => setToast(null)} className="ml-3 opacity-60 hover:opacity-100 text-xs">✕</button>
        </div>
      )}

      {/* ──────────── Tab: API Keys ──────────── */}
      {tab === "keys" && (
        <div className="space-y-4">
          <p className="text-sm text-slate-500 mb-2">
            API keys are encrypted at rest in your local database. Never sent to Rigovo's servers.
          </p>

          {/* All providers from backend */}
          {providerEntries.map(([provider, info]) => {
            const isEditing = keyEditing === provider;
            const isOllama = provider === "ollama";
            return (
              <div key={provider} className="card p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2.5">
                    <div className={`h-2 w-2 rounded-full ${
                      isOllama ? "bg-blue-500" : info.configured ? "bg-emerald-500" : "bg-slate-600"
                    }`} />
                    <span className="text-sm font-medium text-slate-200">{info.label}</span>
                    {info.configured && !isOllama && (
                      <span className="text-[10px] bg-emerald-500/10 text-emerald-400 px-1.5 py-0.5 rounded">active</span>
                    )}
                  </div>
                  <a href={info.link} target="_blank" rel="noreferrer"
                    className="text-xs text-brand-light hover:text-brand-lighter transition">
                    {isOllama ? "Install ↗" : "Get key ↗"}
                  </a>
                </div>

                {isOllama ? (
                  /* Ollama — no API key, just URL */
                  <p className="text-xs text-slate-500">
                    Run models locally with zero API keys. Install Ollama, pull a model, and set agent models to use <code className="bg-white/5 rounded px-1 py-0.5">llama3</code> etc.
                  </p>
                ) : !isEditing ? (
                  <div className="flex items-center gap-3">
                    <div className="flex-1 rounded-lg bg-white/5 px-3 py-2 text-sm text-slate-500 font-mono">
                      {info.configured ? info.masked : "Not configured"}
                    </div>
                    <button type="button" onClick={() => setKeyEditing(provider)}
                      className="px-3 py-2 text-xs font-medium rounded-lg bg-white/5 text-slate-300 hover:bg-white/10 hover:text-white transition">
                      {info.configured ? "Update" : "Add key"}
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <input
                      type="password"
                      autoFocus
                      placeholder={`Paste your ${info.label} API key...`}
                      value={keys[provider] || ""}
                      onChange={(e) => setKeys((prev) => ({ ...prev, [provider]: e.target.value }))}
                      className="flex-1 rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm text-slate-200 font-mono placeholder:text-slate-600 focus:outline-none focus:border-brand/50 focus:ring-1 focus:ring-brand/30"
                    />
                    <button type="button" disabled={saving || !keys[provider]?.trim()}
                      onClick={() => saveKey(provider, keys[provider] || "")}
                      className="px-3 py-2 text-xs font-medium rounded-lg bg-brand text-white hover:bg-brand-dark transition disabled:opacity-40">
                      Save
                    </button>
                    <button type="button" onClick={() => { setKeyEditing(null); setKeys((p) => ({ ...p, [provider]: "" })); }}
                      className="px-3 py-2 text-xs font-medium rounded-lg bg-white/5 text-slate-400 hover:bg-white/10 transition">
                      Cancel
                    </button>
                  </div>
                )}
              </div>
            );
          })}

          {/* Custom OpenAI-compatible endpoint */}
          <div className="card p-4">
            <div className="flex items-center gap-2.5 mb-3">
              <div className={`h-2 w-2 rounded-full ${customBaseUrl ? "bg-emerald-500" : "bg-slate-600"}`} />
              <span className="text-sm font-medium text-slate-200">Custom Endpoint</span>
              <span className="text-[10px] bg-white/5 text-slate-500 px-1.5 py-0.5 rounded">OpenAI-compatible</span>
            </div>
            <p className="text-xs text-slate-500 mb-3">
              Use any OpenAI-compatible API (vLLM, LiteLLM, Azure, etc.). Set the base URL and use any provider's key above.
            </p>
            <div className="flex items-center gap-2">
              <input
                type="url"
                placeholder="https://your-api.example.com/v1"
                value={customBaseUrl}
                onChange={(e) => setCustomBaseUrl(e.target.value)}
                className="flex-1 rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm text-slate-200 font-mono placeholder:text-slate-600 focus:outline-none focus:border-brand/50 focus:ring-1 focus:ring-brand/30"
              />
              <button type="button" disabled={saving} onClick={saveEndpoints}
                className="px-3 py-2 text-xs font-medium rounded-lg bg-white/5 text-slate-300 hover:bg-white/10 hover:text-white transition disabled:opacity-40">
                Save
              </button>
            </div>
          </div>

          {/* Ollama URL */}
          <div className="card p-4">
            <div className="flex items-center gap-2.5 mb-2">
              <span className="text-sm font-medium text-slate-400">Ollama URL</span>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="url"
                placeholder="http://localhost:11434"
                value={ollamaUrl}
                onChange={(e) => setOllamaUrl(e.target.value)}
                className="flex-1 rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm text-slate-200 font-mono placeholder:text-slate-600 focus:outline-none focus:border-brand/50 focus:ring-1 focus:ring-brand/30"
              />
              <button type="button" disabled={saving} onClick={saveEndpoints}
                className="px-3 py-2 text-xs font-medium rounded-lg bg-white/5 text-slate-300 hover:bg-white/10 hover:text-white transition disabled:opacity-40">
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ──────────── Tab: Agent Models ──────────── */}
      {tab === "agents" && (
        <div className="space-y-3">
          <p className="text-sm text-slate-500 mb-2">
            Choose which LLM powers each agent. Premium models cost more but produce better results for complex reasoning.
          </p>

          {Object.entries(ROLE_META).map(([role, meta]) => {
            const current = agentModels[role] || data.default_agent_models[role] || "claude-sonnet-4-6";
            const isDefault = current === data.default_agent_models[role];
            return (
              <div key={role} className="card p-4">
                <div className="flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-base">{meta.icon}</span>
                      <span className="text-sm font-medium text-slate-200">{meta.label}</span>
                      {isDefault && (
                        <span className="text-[10px] bg-white/5 text-slate-500 px-1.5 py-0.5 rounded">default</span>
                      )}
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5 ml-7">{meta.desc}</p>
                  </div>

                  <select
                    value={current}
                    onChange={(e) => setAgentModels((prev) => ({ ...prev, [role]: e.target.value }))}
                    className="rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand/50 focus:ring-1 focus:ring-brand/30 appearance-none cursor-pointer min-w-[180px]"
                  >
                    {data.available_models.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label} ({m.tier})
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            );
          })}

          {/* Cost hint */}
          <div className="card p-4 mt-4">
            <p className="text-xs font-medium text-slate-400 mb-2">Model tiers</p>
            <div className="flex flex-wrap gap-4 text-xs">
              <span className={TIER_COLORS.premium}>● Premium — best reasoning, highest cost</span>
              <span className={TIER_COLORS.standard}>● Standard — good balance</span>
              <span className={TIER_COLORS.budget}>● Budget — fast and cheap</span>
              <span className={TIER_COLORS.local}>● Local — Ollama, no API cost</span>
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <button type="button" disabled={saving} onClick={saveAgentModels}
              className="px-5 py-2.5 text-sm font-medium rounded-xl bg-brand text-white hover:bg-brand-dark transition shadow-lg shadow-brand/20 disabled:opacity-40">
              {saving ? "Saving..." : "Save agent models"}
            </button>
          </div>
        </div>
      )}

      {/* ──────────── Tab: Capabilities ──────────── */}
      {tab === "capabilities" && (
        <div className="space-y-4">
          <p className="text-sm text-slate-500">
            Configure global integration policy and per-agent tool permissions. This is the control surface for plugin, connector, and MCP safety.
          </p>

          {pluginPolicy && (
            <div className="card p-4 space-y-3">
              <p className="text-sm font-medium text-slate-200">Global plugin policy</p>
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
                  <label key={key} className="rounded-lg bg-white/5 px-3 py-2 flex items-center justify-between">
                    <span className="text-slate-400">{label}</span>
                    <input
                      type="checkbox"
                      checked={Boolean(pluginPolicy[key])}
                      onChange={(e) => setPluginPolicy((prev) => prev ? { ...prev, [key]: e.target.checked } : prev)}
                    />
                  </label>
                ))}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                <label className="rounded-lg bg-white/5 px-3 py-2 text-xs text-slate-400">
                  Trust floor
                  <select
                    value={pluginPolicy.min_trust_level}
                    onChange={(e) => setPluginPolicy((prev) => prev ? { ...prev, min_trust_level: e.target.value } : prev)}
                    className="mt-1 w-full rounded bg-white/5 border border-white/10 px-2 py-1 text-xs text-slate-200"
                  >
                    <option value="community">community</option>
                    <option value="verified">verified</option>
                    <option value="internal">internal</option>
                  </select>
                </label>
                <label className="rounded-lg bg-white/5 px-3 py-2 text-xs text-slate-400">
                  Allowed plugin ids (comma-separated)
                  <input
                    type="text"
                    value={pluginPolicy.allowed_plugin_ids.join(", ")}
                    onChange={(e) => setPluginPolicy((prev) => prev ? { ...prev, allowed_plugin_ids: parseCsvList(e.target.value) } : prev)}
                    className="mt-1 w-full rounded bg-white/5 border border-white/10 px-2 py-1 text-xs text-slate-200 font-mono"
                  />
                </label>
                <label className="rounded-lg bg-white/5 px-3 py-2 text-xs text-slate-400">
                  Allowed connector ops
                  <input
                    type="text"
                    value={pluginPolicy.allowed_connector_operations.join(", ")}
                    onChange={(e) => setPluginPolicy((prev) => prev ? { ...prev, allowed_connector_operations: parseCsvList(e.target.value) } : prev)}
                    className="mt-1 w-full rounded bg-white/5 border border-white/10 px-2 py-1 text-xs text-slate-200 font-mono"
                  />
                </label>
                <label className="rounded-lg bg-white/5 px-3 py-2 text-xs text-slate-400">
                  Allowed MCP ops
                  <input
                    type="text"
                    value={pluginPolicy.allowed_mcp_operations.join(", ")}
                    onChange={(e) => setPluginPolicy((prev) => prev ? { ...prev, allowed_mcp_operations: parseCsvList(e.target.value) } : prev)}
                    className="mt-1 w-full rounded bg-white/5 border border-white/10 px-2 py-1 text-xs text-slate-200 font-mono"
                  />
                </label>
                <label className="rounded-lg bg-white/5 px-3 py-2 text-xs text-slate-400 md:col-span-2">
                  Allowed action ops
                  <input
                    type="text"
                    value={pluginPolicy.allowed_action_operations.join(", ")}
                    onChange={(e) => setPluginPolicy((prev) => prev ? { ...prev, allowed_action_operations: parseCsvList(e.target.value) } : prev)}
                    className="mt-1 w-full rounded bg-white/5 border border-white/10 px-2 py-1 text-xs text-slate-200 font-mono"
                  />
                </label>
              </div>
            </div>
          )}

          <div className="card p-4 space-y-3">
            <p className="text-sm font-medium text-slate-200">Agent-level tool matrix (engineering team)</p>
            <div className="space-y-2">
              {Object.entries(ROLE_META).map(([role, meta]) => (
                <label key={role} className="block rounded-lg bg-white/5 px-3 py-2 text-xs text-slate-400">
                  <span className="font-medium text-slate-300">{meta.label}</span>
                  <input
                    type="text"
                    value={(agentTools[role] || []).join(", ")}
                    onChange={(e) =>
                      setAgentTools((prev) => ({ ...prev, [role]: parseCsvList(e.target.value) }))
                    }
                    placeholder="e.g. read_file, write_file, invoke_integration, consult_agent"
                    className="mt-1 w-full rounded bg-white/5 border border-white/10 px-2 py-1 text-xs text-slate-200 font-mono"
                  />
                </label>
              ))}
            </div>
          </div>

          <div className="card p-4">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Loaded integrations</p>
            {!integrationsView?.plugins?.length ? (
              <p className="text-xs text-slate-600">No plugins loaded.</p>
            ) : (
              <div className="space-y-2">
                {integrationsView.plugins.map((p) => (
                  <div key={p.plugin_id} className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2">
                    <p className="text-xs text-slate-200">
                      {p.name} <span className="text-slate-500">({p.plugin_id})</span>
                    </p>
                    <p className="text-[10px] text-slate-500">
                      trust={p.trust_level} · {p.allowed ? "allowed" : `blocked (${(p.reasons || []).join(", ") || "policy"})`}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="flex justify-end">
            <button
              type="button"
              disabled={saving}
              onClick={saveCapabilities}
              className="px-5 py-2.5 text-sm font-medium rounded-xl bg-brand text-white hover:bg-brand-dark transition shadow-lg shadow-brand/20 disabled:opacity-40"
            >
              {saving ? "Saving..." : "Save capability policy"}
            </button>
          </div>
        </div>
      )}

      {/* ──────────── Tab: Storage ──────────── */}
      {tab === "storage" && (
        <div className="space-y-4">
          <p className="text-sm text-slate-500">
            Configure where task history, audit logs, and memory-learning artifacts are stored.
            PostgreSQL is recommended for shared/team deployments; SQLite is best for local-first usage.
          </p>

          <div className="card p-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-slate-200">Database backend</p>
                <p className="text-xs text-slate-500">Switch between local SQLite and external PostgreSQL.</p>
              </div>
              <select
                value={dbBackend}
                onChange={(e) => setDbBackend(e.target.value === "postgres" ? "postgres" : "sqlite")}
                className="rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-brand/50 focus:ring-1 focus:ring-brand/30 appearance-none cursor-pointer min-w-[180px]"
              >
                <option value="sqlite">SQLite (local file)</option>
                <option value="postgres">PostgreSQL (DSN)</option>
              </select>
            </div>

            <div className="rounded-lg bg-white/5 px-3 py-2 text-xs text-slate-400">
              Current backend: <span className="text-slate-200">{data.database.backend}</span>
            </div>
          </div>

          <div className="card p-4 space-y-3">
            <p className="text-sm font-medium text-slate-200">SQLite path</p>
            <input
              type="text"
              value={dbLocalPath}
              onChange={(e) => setDbLocalPath(e.target.value)}
              placeholder=".rigovo/local.db"
              className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm text-slate-200 font-mono placeholder:text-slate-600 focus:outline-none focus:border-brand/50 focus:ring-1 focus:ring-brand/30"
            />
            <p className="text-xs text-slate-500">Used when backend is SQLite.</p>
          </div>

          <div className="card p-4 space-y-3">
            <p className="text-sm font-medium text-slate-200">PostgreSQL DSN</p>
            <input
              type="password"
              value={dbUrl}
              onChange={(e) => setDbUrl(e.target.value)}
              placeholder="postgresql://user:pass@host:5432/dbname"
              className="w-full rounded-lg bg-white/5 border border-white/10 px-3 py-2 text-sm text-slate-200 font-mono placeholder:text-slate-600 focus:outline-none focus:border-brand/50 focus:ring-1 focus:ring-brand/30"
            />
            <p className="text-xs text-slate-500">
              Current DSN: {data.database.dsn_configured ? data.database.dsn_masked : "not configured"}
            </p>
            <p className="text-xs text-amber-400/90">
              Backend and DSN updates are saved to config and require engine restart to apply.
            </p>
          </div>

          <div className="flex justify-end">
            <button
              type="button"
              disabled={saving}
              onClick={saveDatabase}
              className="px-5 py-2.5 text-sm font-medium rounded-xl bg-brand text-white hover:bg-brand-dark transition shadow-lg shadow-brand/20 disabled:opacity-40"
            >
              {saving ? "Saving..." : "Save storage settings"}
            </button>
          </div>
        </div>
      )}

      {/* ──────────── Tab: Config (rigovo.yml) ──────────── */}
      {tab === "config" && (
        <div className="space-y-4">
          <div className="card p-4">
            <p className="text-xs font-semibold text-slate-300 mb-2 uppercase tracking-wider">Runtime Guardrails</p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs">
              <div className="rounded-lg bg-white/5 px-3 py-2 text-slate-400">
                Electron sandbox: <span className="text-slate-200">{engineRuntime?.electronSandbox ? "enabled" : "disabled"}</span>
              </div>
              <div className="rounded-lg bg-white/5 px-3 py-2 text-slate-400">
                Worktree mode: <span className="text-slate-200">{engineRuntime?.worktreeMode ?? runtimeCaps?.runtime.worktree_mode ?? "project"}</span>
              </div>
              <div className="rounded-lg bg-white/5 px-3 py-2 text-slate-400">
                File sandbox: <span className="text-slate-200">{runtimeCaps?.runtime.filesystem_sandbox ?? "project_root"}</span>
              </div>
              <div className="rounded-lg bg-white/5 px-3 py-2 text-slate-400">
                Plugin trust floor: <span className="text-slate-200">{runtimeCaps?.plugins.min_trust_level ?? "verified"}</span>
              </div>
              <div className="rounded-lg bg-white/5 px-3 py-2 text-slate-400">
                Parallel agents: <span className="text-slate-200">{runtimeCaps?.orchestration.parallel_agents ? "on" : "off"}</span>
              </div>
              <div className="rounded-lg bg-white/5 px-3 py-2 text-slate-400">
                Consultation: <span className="text-slate-200">{runtimeCaps?.orchestration.consultation_enabled ? "on" : "off"}</span>
              </div>
              <div className="rounded-lg bg-white/5 px-3 py-2 text-slate-400">
                Replan policy: <span className="text-slate-200">{runtimeCaps?.orchestration.replan.enabled ? "enabled" : "disabled"}</span>
              </div>
              <div className="rounded-lg bg-white/5 px-3 py-2 text-slate-400">
                Debate loop: <span className="text-slate-200">{runtimeCaps?.runtime.debate_enabled ? `on (max ${runtimeCaps.runtime.debate_max_rounds})` : "off"}</span>
              </div>
              <div className="rounded-lg bg-white/5 px-3 py-2 text-slate-400">
                DB backend: <span className="text-slate-200">{runtimeCaps?.database?.backend ?? data.database.backend}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between mb-2">
            <p className="text-sm text-slate-500">
              <code className="text-xs bg-white/5 rounded px-1.5 py-0.5">rigovo.yml</code> — override any section to customize your project.
            </p>
            {/* Toggle friendly / raw */}
            <div className="flex gap-1 bg-white/5 rounded-lg p-0.5">
              <button type="button" onClick={() => setYmlView("friendly")}
                className={`px-2.5 py-1 text-xs font-medium rounded-md transition ${
                  ymlView === "friendly" ? "bg-brand text-white" : "text-slate-400 hover:text-slate-200"
                }`}>
                Friendly
              </button>
              <button type="button" onClick={() => setYmlView("raw")}
                className={`px-2.5 py-1 text-xs font-medium rounded-md transition ${
                  ymlView === "raw" ? "bg-brand text-white" : "text-slate-400 hover:text-slate-200"
                }`}>
                Raw YAML
              </button>
            </div>
          </div>

          {ymlView === "friendly" ? (
            /* Friendly view — sections as collapsible cards */
            <div className="space-y-2">
              {parseYmlSections(ymlRaw).filter(({ key }) => !key.startsWith("#")).map(({ key, value }) => (
                <details key={key} className="card group">
                  <summary className="cursor-pointer px-4 py-3 flex items-center gap-2 text-sm font-medium text-slate-200 hover:text-white transition">
                    <span className="text-[10px] text-slate-600 transition group-open:rotate-90">▶</span>
                    <span className="capitalize">{key.replace(/_/g, " ")}</span>
                    <span className="text-[10px] text-slate-600 ml-auto font-mono">{key}:</span>
                  </summary>
                  <div className="px-4 pb-3 border-t border-white/5 pt-3">
                    <pre className="text-xs text-slate-400 font-mono whitespace-pre-wrap overflow-x-auto">{value}</pre>
                  </div>
                </details>
              ))}
            </div>
          ) : (
            /* Raw YAML editor */
            <div className="space-y-3">
              <textarea
                ref={ymlRef}
                value={ymlRaw}
                onChange={(e) => setYmlRaw(e.target.value)}
                spellCheck={false}
                className="w-full h-80 rounded-xl bg-white/5 border border-white/10 px-4 py-3 text-sm text-slate-200 font-mono placeholder:text-slate-600 focus:outline-none focus:border-brand/50 focus:ring-1 focus:ring-brand/30 resize-y"
                placeholder="# rigovo.yml — paste or edit your config here"
              />
              <div className="flex justify-end">
                <button type="button" disabled={saving} onClick={saveYml}
                  className="px-5 py-2.5 text-sm font-medium rounded-xl bg-brand text-white hover:bg-brand-dark transition shadow-lg shadow-brand/20 disabled:opacity-40">
                  {saving ? "Saving..." : "Save config"}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ──────────── Tab: Logs ──────────── */}
      {tab === "logs" && (
        <LogViewer onBack={onBack} />
      )}
    </div>
  );
}
