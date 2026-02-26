/* ------------------------------------------------------------------ */
/*  TaskInput — fixed input dock at bottom of main panel              */
/* ------------------------------------------------------------------ */
import { FormEvent, useRef, useEffect, forwardRef, useImperativeHandle } from "react";

export interface TaskInputHandle {
  focus: () => void;
}

interface TaskInputProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: (e: FormEvent) => void;
  creating: boolean;
  message: string;
  onDismissMessage: () => void;
  apiReachable: boolean | null;
}

const TaskInput = forwardRef<TaskInputHandle, TaskInputProps>(
  ({ value, onChange, onSubmit, creating, message, onDismissMessage, apiReachable }, ref) => {
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    useImperativeHandle(ref, () => ({
      focus: () => textareaRef.current?.focus()
    }));

    /* auto-resize textarea — single line by default, max 3 lines */
    useEffect(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 130) + "px";
    }, [value]);

    const isError = message.toLowerCase().startsWith("fail") || message.toLowerCase().startsWith("cannot");
    const isSuccess = message.toLowerCase().includes("created");

    return (
      <div className="input-dock">
        {/* Error / success banner — inline above input */}
        {message && isError && (
          <div className="feedback-banner error mb-2 flex items-center justify-between animate-fadeup text-xs">
            <span>{message}</span>
            <button type="button" onClick={onDismissMessage}
              className="ml-3 text-rose-400 hover:text-rose-300 text-xs font-bold">
              ✕
            </button>
          </div>
        )}
        {message && isSuccess && (
          <div className="feedback-banner success mb-2 animate-fadeup text-xs">
            {message}
          </div>
        )}

        <form onSubmit={onSubmit}
          className={`input-bar flex items-end gap-2 px-4 py-2.5 ${
            isSuccess ? "!border-emerald-500/30" : ""
          }`}>

          {/* API status dot */}
          {apiReachable === false && (
            <div className="flex-shrink-0 mb-1.5" title="API unreachable">
              <span className="inline-block h-2 w-2 rounded-full bg-rose-400 animate-pulse" />
            </div>
          )}

          <textarea
            ref={textareaRef}
            rows={1}
            className="flex-1 resize-none bg-transparent text-sm text-slate-200 outline-none placeholder:text-slate-500 leading-snug"
            placeholder="Describe a task for your agents..."
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSubmit(e as unknown as FormEvent);
              }
            }}
            disabled={creating}
          />

          <button type="submit" disabled={creating || !value.trim()} className="send-btn flex-shrink-0" aria-label="Send">
            {creating ? (
              <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
            ) : (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M3 13V9l10-1-10-1V3l14 5-14 5z" fill="white"/>
              </svg>
            )}
          </button>
        </form>
      </div>
    );
  }
);

TaskInput.displayName = "TaskInput";
export default TaskInput;
