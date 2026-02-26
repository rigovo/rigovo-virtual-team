/* ------------------------------------------------------------------ */
/*  Settings — API keys, per-agent models, config editor, logs         */
/*  Talks to GET/POST /v1/settings on the control-plane backend        */
/* ------------------------------------------------------------------ */
import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, readJson } from "../api";
import LogViewer from "./LogViewer";

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
  ollama_url: string;
  custom_base_url: string;
  yml_raw: string;
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
  const [tab, setTab] = useState<"keys" | "agents" | "config" | "logs">("keys");

  /* Editable state — keys */
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [keyEditing, setKeyEditing] = useState<string | null>(null);

  /* Editable state — agent models */
  const [agentModels, setAgentModels] = useState<Record<string, string>>({});

  /* Editable state — custom endpoint */
  const [customBaseUrl, setCustomBaseUrl] = useState("");
  const [ollamaUrl, setOllamaUrl] = useState("");

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
      setCustomBaseUrl(res.custom_base_url || "");
      setOllamaUrl(res.ollama_url || "http://localhost:11434");
      setYmlRaw(res.yml_raw || "");
    }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

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

  const saveEndpoints = () => {
    const payload: Record<string, unknown> = {};
    if (customBaseUrl !== (data?.custom_base_url || "")) payload.custom_base_url = customBaseUrl;
    if (ollamaUrl !== (data?.ollama_url || "")) payload.ollama_url = ollamaUrl;
    if (Object.keys(payload).length) void save(payload);
    else showToast("No endpoint changes to save.", "success");
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
        {(["keys", "agents", "config", "logs"] as const).map((t) => (
          <button key={t} type="button" onClick={() => setTab(t)}
            className={`flex-1 py-2 px-3 text-sm font-medium rounded-lg transition ${
              tab === t
                ? "bg-brand text-white shadow-lg shadow-brand/20"
                : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
            }`}>
            {t === "keys" ? "API Keys" : t === "agents" ? "Agents" : t === "config" ? "Config" : "Logs"}
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

      {/* ──────────── Tab: Config (rigovo.yml) ──────────── */}
      {tab === "config" && (
        <div className="space-y-4">
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
