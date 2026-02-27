import {
  FormEvent,
  useRef,
  useEffect,
  forwardRef,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import type { Tier } from "../types";

export interface TaskInputHandle {
  focus: () => void;
}

interface TaskInputProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (e: FormEvent) => void;
  onExecuteCommand: (input: string) => boolean;
  creating: boolean;
  message: string;
  onDismissMessage: () => void;
  apiReachable: boolean | null;
  runtimeLabel: string;
  permissionsLabel: string;
  modelLabel: string;
  effortLabel: string;
  onOpenSettings: () => void;
  onAddFiles: () => void;
  mentionFiles: string[];
  taskTier?: Tier;
  onTierChange?: (tier: Tier) => void;
}

type SlashCommand = { id: string; description: string };

const SLASH_COMMANDS: SlashCommand[] = [
  { id: "new-thread",   description: "Start a fresh thread" },
  { id: "settings",    description: "Open settings" },
  { id: "skills",      description: "Open skills page" },
  { id: "automations", description: "Open automations page" },
  { id: "open-folder", description: "Open project folder picker" },
  { id: "help",        description: "Show available slash commands" },
];

const TIER_OPTIONS: Array<{ value: Tier; label: string; desc: string; icon: string }> = [
  { value: "auto",    label: "Auto",    icon: "⚡", desc: "Agent acts without waiting for approval" },
  { value: "notify",  label: "Notify",  icon: "🔔", desc: "Agent notifies you but keeps working" },
  { value: "approve", label: "Approve", icon: "✋", desc: "Agent waits for approval before risky actions" },
];

const TaskInput = forwardRef<TaskInputHandle, TaskInputProps>(
  (
    {
      value,
      onChange,
      onSubmit,
      onExecuteCommand,
      creating,
      message,
      onDismissMessage,
      apiReachable,
      runtimeLabel,
      permissionsLabel,
      modelLabel,
      effortLabel,
      onOpenSettings,
      mentionFiles,
      taskTier = "auto",
      onTierChange,
    },
    ref,
  ) => {
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const [activeSlashIdx, setActiveSlashIdx] = useState(0);
    const [activeAtIdx, setActiveAtIdx]       = useState(0);
    const [tierOpen, setTierOpen]             = useState(false);
    const tierRef = useRef<HTMLDivElement>(null);

    useImperativeHandle(ref, () => ({
      focus: () => textareaRef.current?.focus(),
    }));

    /* auto-resize */
    useEffect(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 130) + "px";
    }, [value]);

    /* Close tier popover on outside click */
    useEffect(() => {
      if (!tierOpen) return;
      const handler = (e: MouseEvent) => {
        if (tierRef.current && !tierRef.current.contains(e.target as Node)) {
          setTierOpen(false);
        }
      };
      window.addEventListener("mousedown", handler);
      return () => window.removeEventListener("mousedown", handler);
    }, [tierOpen]);

    /* ── Token detection — match at end of current value ── */
    const beforeCaret = value;

    /* Slash commands: /query */
    const slashMatch   = beforeCaret.match(/(?:^|\s)(\/)([\w-]*)$/);
    const slashQuery   = slashMatch?.[2] ?? null;
    const slashToken   = slashMatch ? `/${slashMatch[2]}` : "";

    /* @ file mentions: @query */
    const atMatch  = beforeCaret.match(/(?:^|\s|,)(@)([\w.\-/\\]*)$/);
    const atQuery  = atMatch?.[2] ?? null;
    const atToken  = atMatch ? `@${atMatch[2]}` : "";

    const commandSuggestions = useMemo(() => {
      if (slashQuery === null) return [];
      const q = slashQuery.toLowerCase();
      return SLASH_COMMANDS.filter((c) => c.id.startsWith(q)).slice(0, 6);
    }, [slashQuery]);

    const fileSuggestions = useMemo(() => {
      if (atQuery === null || mentionFiles.length === 0) return [];
      const q = atQuery.toLowerCase();
      return mentionFiles
        .filter((f) => f.toLowerCase().includes(q))
        .slice(0, 8);
    }, [atQuery, mentionFiles]);

    const hasSlashSuggestions = commandSuggestions.length > 0;
    const hasAtSuggestions    = fileSuggestions.length > 0;
    const hasSuggestions      = hasSlashSuggestions || hasAtSuggestions;

    useEffect(() => { setActiveSlashIdx(0); }, [slashQuery]);
    useEffect(() => { setActiveAtIdx(0); }, [atQuery]);

    function replaceToken(token: string, replacement: string): void {
      const escapedToken = token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const next = value.replace(new RegExp(`${escapedToken}$`), replacement);
      onChange(next);
      window.requestAnimationFrame(() => {
        const el = textareaRef.current;
        if (!el) return;
        el.focus();
        el.setSelectionRange(next.length, next.length);
      });
    }

    function pickSlash(): void {
      const picked = commandSuggestions[activeSlashIdx];
      if (picked) replaceToken(slashToken, `/${picked.id} `);
    }

    function pickAt(): void {
      const picked = fileSuggestions[activeAtIdx];
      if (picked) {
        // Insert full relative path so the engine can locate the file
        replaceToken(atToken, `@${picked} `);
      }
    }

    function executeSubmit(e: FormEvent): void {
      if (onExecuteCommand(value.trim())) {
        onChange("");
        return;
      }
      onSubmit(e);
    }

    const isError =
      message.toLowerCase().startsWith("fail") ||
      message.toLowerCase().startsWith("cannot");

    const activeTier = TIER_OPTIONS.find((t) => t.value === taskTier) ?? TIER_OPTIONS[0];

    return (
      <div className="input-dock">
        {/* Message banner */}
        {message && (
          <div className={`feedback mb-2 animate-fadeup flex items-center justify-between text-xs ${isError ? "feedback-error" : "feedback-success"}`}>
            <span>{message}</span>
            <button
              type="button"
              onClick={onDismissMessage}
              className="ml-3 opacity-50 hover:opacity-80"
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>
        )}

        {/* Input form */}
        <form onSubmit={(e) => executeSubmit(e)} className="input-bar px-4 py-3">
          <textarea
            ref={textareaRef}
            rows={1}
            className="w-full resize-none bg-transparent text-sm outline-none leading-snug"
            style={{ color: "var(--t1)", caretColor: "var(--t1)" }}
            placeholder="Describe a task, or / for commands, @ for files"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if ((e.key === "ArrowDown" || e.key === "ArrowUp") && hasSuggestions) {
                e.preventDefault();
                if (hasSlashSuggestions) {
                  setActiveSlashIdx((prev) =>
                    e.key === "ArrowDown"
                      ? (prev + 1) % commandSuggestions.length
                      : (prev - 1 + commandSuggestions.length) % commandSuggestions.length,
                  );
                } else if (hasAtSuggestions) {
                  setActiveAtIdx((prev) =>
                    e.key === "ArrowDown"
                      ? (prev + 1) % fileSuggestions.length
                      : (prev - 1 + fileSuggestions.length) % fileSuggestions.length,
                  );
                }
                return;
              }
              if ((e.key === "Tab" || e.key === "Enter") && hasSuggestions) {
                if (e.key === "Enter" && e.shiftKey) return;
                e.preventDefault();
                if (hasSlashSuggestions) pickSlash();
                else if (hasAtSuggestions) pickAt();
                return;
              }
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                executeSubmit(e as unknown as FormEvent);
              }
            }}
            disabled={creating}
          />

          {/* Slash command suggestions */}
          {hasSlashSuggestions && (
            <div className="composer-suggest">
              {commandSuggestions.map((cmd, idx) => (
                <button
                  key={cmd.id}
                  type="button"
                  className={`composer-suggest-item${idx === activeSlashIdx ? " active" : ""}`}
                  onMouseDown={(e) => { e.preventDefault(); replaceToken(slashToken, `/${cmd.id} `); }}
                >
                  <span className="composer-suggest-title">/{cmd.id}</span>
                  <span className="composer-suggest-copy">{cmd.description}</span>
                </button>
              ))}
            </div>
          )}

          {/* @ file mention suggestions */}
          {hasAtSuggestions && (
            <div className="composer-suggest">
              {fileSuggestions.map((file, idx) => {
                const basename = file.split("/").pop() ?? file;
                const dir = file.includes("/") ? file.slice(0, file.lastIndexOf("/")) : "";
                return (
                  <button
                    key={file}
                    type="button"
                    className={`composer-suggest-item${idx === activeAtIdx ? " active" : ""}`}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      replaceToken(atToken, `@${file} `);
                    }}
                  >
                    <span className="composer-suggest-title">@{basename}</span>
                    {dir && <span className="composer-suggest-copy">{dir}</span>}
                  </button>
                );
              })}
            </div>
          )}

          {/* Toolbar */}
          <div className="composer-toolbar">
            <div className="composer-toolbar-left">
              <button
                type="button"
                className="composer-select-btn"
                onClick={onOpenSettings}
                aria-label="Model settings"
              >
                {modelLabel}
                <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="ml-1 opacity-40">
                  <path d="M2.5 3.5l2.5 3 2.5-3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>

              {/* Tier / permission dropdown */}
              <div className="relative" ref={tierRef}>
                <button
                  type="button"
                  className="composer-select-btn"
                  onClick={() => setTierOpen((v) => !v)}
                  aria-label="Permission tier"
                  aria-expanded={tierOpen}
                >
                  <span className="mr-1">{activeTier.icon}</span>
                  {activeTier.label}
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none" className="ml-1 opacity-40">
                    <path d="M2.5 3.5l2.5 3 2.5-3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>

                {tierOpen && (
                  <div className="tier-popover">
                    {TIER_OPTIONS.map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        className={`tier-option${taskTier === opt.value ? " active" : ""}`}
                        onClick={() => { onTierChange?.(opt.value); setTierOpen(false); }}
                      >
                        <span className="tier-option-label">
                          <span className="mr-1.5">{opt.icon}</span>{opt.label}
                        </span>
                        <span className="tier-option-desc">{opt.desc}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="composer-toolbar-right">
              {apiReachable === false && (
                <span className="inline-flex items-center gap-1 text-xs" style={{ color: "var(--t4)" }} title="API unreachable">
                  <span className="inline-block h-1.5 w-1.5 rounded-full animate-pulse" style={{ background: "var(--s-failed)" }} />
                  Offline
                </span>
              )}
              <button
                type="submit"
                disabled={creating || !value.trim()}
                className="send-btn flex-shrink-0"
                aria-label="Send"
              >
                {creating ? (
                  <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                ) : (
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                    <path d="M2 12V8.5l9-1.5-9-1.5V2l12 5-12 5z" fill="white" />
                  </svg>
                )}
              </button>
            </div>
          </div>
        </form>

        {/* Context meta row — subtle status bar */}
        <div className="composer-meta-row">
          <div className="composer-meta-group">
            <span className="composer-meta-item strong">{runtimeLabel}</span>
            <span className="composer-meta-sep">·</span>
            <span className="composer-meta-item">{permissionsLabel}</span>
          </div>
          <div className="composer-meta-group">
            <span className="composer-meta-item">{effortLabel}</span>
            <span className="composer-meta-sep">·</span>
            <span className="composer-meta-item">{modelLabel}</span>
          </div>
        </div>
      </div>
    );
  },
);

TaskInput.displayName = "TaskInput";
export default TaskInput;
