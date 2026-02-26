/* ------------------------------------------------------------------ */
/*  Settings — API keys + per-agent model configuration               */
/*  Users should never need to touch .env or rigovo.yml               */
/* ------------------------------------------------------------------ */
import { useCallback, useEffect, useState } from "react";
import { API_BASE, readJson } from "../api";

/* ---- Types ---- */
interface ProviderInfo {
  configured: boolean;
  masked: string;
  key_env: string;
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
}

interface SettingsProps {
  onBack: () => void;
}

/* ---- Constants ---- */
const PROVIDER_META: Record<string, { label: string; placeholder: string; link: string }> = {
  anthropic: { label: "Anthropic", placeholder: "sk-ant-api03-...", link: "https://console.anthropic.com/settings/keys" },
  openai:    { label: "OpenAI",    placeholder: "sk-...",           link: "https://platform.openai.com/api-keys" },
  groq:      { label: "Groq",      placeholder: "gsk_...",          link: "https://console.groq.com/keys" },
};

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
};

/* ================================================================== */
/*  Component                                                          */
/* ================================================================== */
export default function Settings({ onBack }: SettingsProps) {
  const [data, setData] = useState<SettingsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");
  const [tab, setTab] = useState<"keys" | "agents">("keys");

  /* Editable state */
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [keyEditing, setKeyEditing] = useState<string | null>(null);
  const [agentModels, setAgentModels] = useState<Record<string, string>>({});

  /* ---- Load settings ---- */
  const load = useCallback(async () => {
    setLoading(true);
    const res = await readJson<SettingsData>(`${API_BASE}/v1/settings`);
    if (res) {
      setData(res);
      setAgentModels({ ...res.agent_models });
    }
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  /* ---- Save ---- */
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
        setToast(`Saved. ${d.note || ""}`);
        window.setTimeout(() => setToast(""), 4000);
        void load(); // refresh
      } else {
        setToast("Save failed");
        window.setTimeout(() => setToast(""), 3000);
      }
    } catch {
      setToast("Cannot reach API");
      window.setTimeout(() => setToast(""), 3000);
    }
    setSaving(false);
  };

  const saveKey = (provider: string, value: string) => {
    const envMap: Record<string, string> = {
      anthropic: "anthropic_api_key",
      openai: "openai_api_key",
      groq: "groq_api_key",
    };
    void save({ [envMap[provider]]: value });
    setKeyEditing(null);
    setKeys((prev) => ({ ...prev, [provider]: "" }));
  };

  const saveAgentModels = () => {
    void save({ agent_models: agentModels });
  };

  /* ---- Render ---- */
  if (loading || !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin h-6 w-6 border-2 border-brand border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto py-6 px-4 animate-fadeup">
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
        {(["keys", "agents"] as const).map((t) => (
          <button key={t} type="button" onClick={() => setTab(t)}
            className={`flex-1 py-2 px-3 text-sm font-medium rounded-lg transition ${
              tab === t
                ? "bg-brand text-white shadow-lg shadow-brand/20"
                : "text-slate-400 hover:text-slate-200 hover:bg-white/5"
            }`}>
            {t === "keys" ? "API Keys" : "Agent Models"}
          </button>
        ))}
      </div>

      {/* Toast */}
      {toast && (
        <div className="mb-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 px-4 py-2.5 text-sm text-emerald-400 animate-fadeup">
          {toast}
        </div>
      )}

      {/* ──────────── Tab: API Keys ──────────── */}
      {tab === "keys" && (
        <div className="space-y-4">
          <p className="text-sm text-slate-500 mb-2">
            Your API keys are stored locally in your project's <code className="text-xs bg-white/5 rounded px-1.5 py-0.5">.env</code> file and never sent to Rigovo's servers.
          </p>

          {Object.entries(data.providers).map(([provider, info]) => {
            const meta = PROVIDER_META[provider];
            if (!meta) return null;
            const isEditing = keyEditing === provider;
            return (
              <div key={provider} className="card p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2.5">
                    <div className={`h-2 w-2 rounded-full ${info.configured ? "bg-emerald-500" : "bg-slate-600"}`} />
                    <span className="text-sm font-medium text-slate-200">{meta.label}</span>
                  </div>
                  <a href={meta.link} target="_blank" rel="noreferrer"
                    className="text-xs text-brand-light hover:text-brand-lighter transition">
                    Get API key &#x2197;
                  </a>
                </div>

                {!isEditing ? (
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
                      placeholder={meta.placeholder}
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

          {/* Ollama / local note */}
          <div className="card p-4">
            <div className="flex items-center gap-2.5 mb-1">
              <div className="h-2 w-2 rounded-full bg-blue-500" />
              <span className="text-sm font-medium text-slate-200">Ollama (Local)</span>
            </div>
            <p className="text-xs text-slate-500">
              Run models locally with zero API keys. Install Ollama, pull a model, and set agent models below to use <code className="bg-white/5 rounded px-1 py-0.5">llama3</code> or <code className="bg-white/5 rounded px-1 py-0.5">mixtral</code>.
            </p>
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
                  {/* Role info */}
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

                  {/* Model selector */}
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
            <div className="flex gap-4 text-xs">
              <span className={TIER_COLORS.premium}>&#x25CF; Premium — best reasoning, highest cost</span>
              <span className={TIER_COLORS.standard}>&#x25CF; Standard — good balance</span>
              <span className={TIER_COLORS.budget}>&#x25CF; Budget — fast and cheap</span>
            </div>
          </div>

          {/* Save button */}
          <div className="flex justify-end pt-2">
            <button type="button" disabled={saving} onClick={saveAgentModels}
              className="px-5 py-2.5 text-sm font-medium rounded-xl bg-brand text-white hover:bg-brand-dark transition shadow-lg shadow-brand/20 disabled:opacity-40">
              {saving ? "Saving..." : "Save agent models"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
