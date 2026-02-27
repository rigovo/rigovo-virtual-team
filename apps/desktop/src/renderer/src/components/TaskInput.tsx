/* ------------------------------------------------------------------ */
/*  TaskInput — premium fixed input dock, Codex-inspired               */
/* ------------------------------------------------------------------ */
import {
  FormEvent,
  useRef,
  useEffect,
  forwardRef,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";

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
}

type SlashCommand = {
  id: string;
  description: string;
};

const SLASH_COMMANDS: SlashCommand[] = [
  { id: "new-thread", description: "Start a fresh thread" },
  { id: "settings", description: "Open settings" },
  { id: "skills", description: "Open skills page" },
  { id: "automations", description: "Open automations page" },
  { id: "documents", description: "Open documents page" },
  { id: "language", description: "Open language page" },
  { id: "open-folder", description: "Open project folder picker" },
  { id: "help", description: "Show available slash commands" },
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
      onAddFiles,
      mentionFiles,
    },
    ref,
  ) => {
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const [activeIdx, setActiveIdx] = useState(0);

    useImperativeHandle(ref, () => ({
      focus: () => textareaRef.current?.focus(),
    }));

    /* auto-resize textarea */
    useEffect(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 130) + "px";
    }, [value]);

    const isError =
      message.toLowerCase().startsWith("fail") ||
      message.toLowerCase().startsWith("cannot");
    const isSuccess = message.toLowerCase().includes("created");

    const selectionStart =
      textareaRef.current?.selectionStart ?? value.length;
    const beforeCaret = value.slice(0, selectionStart);
    const triggerMatch = beforeCaret.match(/(?:^|\s)([@/])([^\s]*)$/);
    const trigger = triggerMatch?.[1] ?? null;
    const query = triggerMatch?.[2] ?? "";
    const triggerToken = triggerMatch ? `${trigger}${query}` : "";

    const fileSuggestions = useMemo(() => {
      if (trigger !== "@") return [];
      const q = query.toLowerCase();
      return mentionFiles.filter((f) => f.toLowerCase().includes(q)).slice(0, 8);
    }, [trigger, query, mentionFiles]);

    const commandSuggestions = useMemo(() => {
      if (trigger !== "/") return [];
      const q = query.toLowerCase();
      return SLASH_COMMANDS.filter((c) =>
        c.id.toLowerCase().includes(q),
      ).slice(0, 8);
    }, [trigger, query]);

    const hasSuggestions =
      fileSuggestions.length > 0 || commandSuggestions.length > 0;

    useEffect(() => {
      setActiveIdx(0);
    }, [trigger, query]);

    function replaceActiveToken(replacement: string): void {
      const currentValue = value;
      const caretPos =
        textareaRef.current?.selectionStart ?? currentValue.length;
      const left = currentValue.slice(0, caretPos);
      const right = currentValue.slice(caretPos);
      const nextLeft = left.replace(
        new RegExp(
          `${triggerToken.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`,
        ),
        replacement,
      );
      const next = `${nextLeft}${right}`;
      onChange(next);
      window.requestAnimationFrame(() => {
        const el = textareaRef.current;
        if (!el) return;
        const pos = nextLeft.length;
        el.focus();
        el.setSelectionRange(pos, pos);
      });
    }

    function executeSubmit(e: FormEvent): void {
      if (onExecuteCommand(value.trim())) {
        onChange("");
        return;
      }
      onSubmit(e);
    }

    function pickSuggestion(): void {
      if (trigger === "@") {
        const picked = fileSuggestions[activeIdx];
        if (picked) replaceActiveToken(`@${picked} `);
        return;
      }
      if (trigger === "/") {
        const picked = commandSuggestions[activeIdx];
        if (picked) replaceActiveToken(`/${picked.id} `);
      }
    }

    return (
      <div className="input-dock">
        {/* Error / success banner */}
        {message && isError && (
          <div className="feedback-banner error mb-2 flex items-center justify-between animate-fadeup text-xs">
            <span>{message}</span>
            <button
              type="button"
              onClick={onDismissMessage}
              className="ml-3 text-xs font-medium opacity-50 hover:opacity-80"
            >
              &#10005;
            </button>
          </div>
        )}
        {message && isSuccess && (
          <div className="feedback-banner success mb-2 animate-fadeup text-xs">
            {message}
          </div>
        )}

        {/* Input form */}
        <form
          onSubmit={(e) => executeSubmit(e)}
          className={`input-bar px-4 py-3${isSuccess ? " !border-emerald-400/20" : ""}`}
        >
          <textarea
            ref={textareaRef}
            rows={1}
            className="w-full resize-none bg-transparent text-sm outline-none leading-snug"
            style={{
              color: "var(--ui-text)",
              caretColor: "var(--ui-text)",
            }}
            placeholder="Ask Codex anything, @ to add files, / for commands"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (
                (e.key === "ArrowDown" || e.key === "ArrowUp") &&
                hasSuggestions
              ) {
                e.preventDefault();
                const listSize =
                  trigger === "@"
                    ? fileSuggestions.length
                    : commandSuggestions.length;
                setActiveIdx((prev) => {
                  if (e.key === "ArrowDown") return (prev + 1) % listSize;
                  return (prev - 1 + listSize) % listSize;
                });
                return;
              }

              if (
                (e.key === "Tab" || e.key === "Enter") &&
                hasSuggestions
              ) {
                if (e.key === "Enter" && e.shiftKey) return;
                e.preventDefault();
                pickSuggestion();
                return;
              }

              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                executeSubmit(e as unknown as FormEvent);
              }
            }}
            disabled={creating}
          />

          {/* File suggestions */}
          {trigger === "@" && fileSuggestions.length > 0 && (
            <div className="composer-suggest">
              {fileSuggestions.map((file, idx) => (
                <button
                  key={file}
                  type="button"
                  className={`composer-suggest-item${idx === activeIdx ? " active" : ""}`}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    replaceActiveToken(`@${file} `);
                  }}
                >
                  <span className="composer-suggest-title">@{file}</span>
                  <span className="composer-suggest-copy">
                    Attach file reference
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* Command suggestions */}
          {trigger === "/" && commandSuggestions.length > 0 && (
            <div className="composer-suggest">
              {commandSuggestions.map((cmd, idx) => (
                <button
                  key={cmd.id}
                  type="button"
                  className={`composer-suggest-item${idx === activeIdx ? " active" : ""}`}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    replaceActiveToken(`/${cmd.id} `);
                  }}
                >
                  <span className="composer-suggest-title">/{cmd.id}</span>
                  <span className="composer-suggest-copy">
                    {cmd.description}
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* Toolbar */}
          <div className="composer-toolbar">
            <div className="composer-toolbar-left">
              <button
                type="button"
                className="composer-icon-btn"
                onClick={onAddFiles}
                aria-label="Add files"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <path
                    d="M7 3v8M3 7h8"
                    stroke="currentColor"
                    strokeWidth="1.4"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
              <button
                type="button"
                className="composer-select-btn"
                onClick={onOpenSettings}
              >
                {modelLabel}
                <svg
                  width="10"
                  height="10"
                  viewBox="0 0 10 10"
                  fill="none"
                  className="ml-1 opacity-40"
                >
                  <path
                    d="M2.5 3.5l2.5 3 2.5-3"
                    stroke="currentColor"
                    strokeWidth="1.2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
              <button
                type="button"
                className="composer-select-btn"
                onClick={onOpenSettings}
              >
                {effortLabel}
                <svg
                  width="10"
                  height="10"
                  viewBox="0 0 10 10"
                  fill="none"
                  className="ml-1 opacity-40"
                >
                  <path
                    d="M2.5 3.5l2.5 3 2.5-3"
                    stroke="currentColor"
                    strokeWidth="1.2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </div>
            <div className="composer-toolbar-right">
              {apiReachable === false && (
                <span
                  className="inline-flex items-center gap-1 text-xs"
                  style={{ color: "var(--ui-text-subtle)" }}
                  title="API unreachable"
                >
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full animate-pulse"
                    style={{ background: "#ef4444" }}
                  />
                  Offline
                </span>
              )}
              {/* Mic button */}
              <button
                type="button"
                className="composer-icon-btn"
                aria-label="Voice input"
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <rect x="5" y="1.5" width="4" height="7" rx="2" stroke="currentColor" strokeWidth="1.2" />
                  <path d="M3 7a4 4 0 008 0M7 11v2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                </svg>
              </button>
              {/* Send button */}
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
                    <path
                      d="M2 12V8.5l9-1.5-9-1.5V2l12 5-12 5z"
                      fill="white"
                    />
                  </svg>
                )}
              </button>
            </div>
          </div>
        </form>

        {/* Meta row */}
        <div className="composer-meta-row">
          <div className="composer-meta-group">
            <span className="composer-meta-item strong">{runtimeLabel}</span>
            <span className="composer-meta-item">{permissionsLabel}</span>
          </div>
          <div className="composer-meta-group">
            <span className="composer-meta-item">{modelLabel}</span>
            <span className="composer-meta-item">{effortLabel}</span>
          </div>
        </div>
      </div>
    );
  },
);

TaskInput.displayName = "TaskInput";
export default TaskInput;
