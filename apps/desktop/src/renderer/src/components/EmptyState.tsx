/* ------------------------------------------------------------------ */
/*  EmptyState — onboarding with CTO-relevant task examples            */
/* ------------------------------------------------------------------ */

interface EmptyStateProps {
  onSelectExample: (text: string) => void;
}

const EXAMPLES = [
  { icon: "\uD83D\uDD12", text: "Add user authentication with JWT and refresh tokens", category: "Feature" },
  { icon: "\uD83D\uDC1B", text: "Fix the N+1 query problem in our orders API", category: "Bug fix" },
  { icon: "\uD83E\uDDEA", text: "Write integration tests for the payment module", category: "Testing" },
  { icon: "\u2699\uFE0F", text: "Set up CI/CD pipeline with staging and production", category: "DevOps" },
];

export default function EmptyState({ onSelectExample }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center max-w-md mx-auto animate-fadeup">
      <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand/10 ring-1 ring-brand/20">
        <span className="text-2xl">R</span>
      </div>
      <h2 className="text-lg font-bold text-slate-100">What should your team work on?</h2>
      <p className="mt-2 text-sm text-slate-500 leading-relaxed">
        Describe a task and Rigovo will classify it, assemble the right agents, and execute with quality gates.
      </p>

      <div className="mt-8 w-full grid grid-cols-2 gap-2">
        {EXAMPLES.map((ex) => (
          <button key={ex.text} type="button"
            className="rounded-2xl border px-4 py-3.5 text-left transition-all hover:border-brand/30 hover:bg-brand/5 group"
            style={{ background: "rgba(39,53,73,0.4)", borderColor: "rgba(255,255,255,0.08)" }}
            onClick={() => onSelectExample(ex.text)}>
            <div className="flex items-center gap-2 mb-1.5">
              <span className="text-sm">{ex.icon}</span>
              <span className="text-[10px] font-semibold text-slate-600 uppercase tracking-wider">{ex.category}</span>
            </div>
            <span className="text-[13px] text-slate-400 leading-snug group-hover:text-slate-200 transition-colors">{ex.text}</span>
          </button>
        ))}
      </div>

      <p className="mt-6 text-[11px] text-slate-700">
        Press <kbd className="px-1.5 py-0.5 rounded bg-white/5 text-slate-500 font-mono text-[10px]">Enter</kbd> to send
        {" \u00B7 "}
        <kbd className="px-1.5 py-0.5 rounded bg-white/5 text-slate-500 font-mono text-[10px]">Shift+Enter</kbd> for new line
      </p>
    </div>
  );
}
