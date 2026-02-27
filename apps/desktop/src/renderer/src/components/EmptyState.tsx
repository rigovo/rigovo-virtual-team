interface EmptyStateProps {
  onSelectExample: (text: string) => void;
}

const EXAMPLES = [
  {
    icon: "⚡",
    title: "Review and fix all failing tests in this repo.",
    iconBg: "rgba(99,102,241,0.10)",
  },
  {
    icon: "🔒",
    title: "Audit the auth module for security issues and fix them.",
    iconBg: "rgba(217,119,6,0.10)",
  },
  {
    icon: "📐",
    title: "Refactor the API layer to follow REST best practices.",
    iconBg: "rgba(22,163,74,0.10)",
  },
];

export default function EmptyState({ onSelectExample }: EmptyStateProps) {
  return (
    <div className="flex h-full flex-col items-center justify-center animate-fadeup">
      {/* Logo mark */}
      <div
        className="mb-3 flex h-10 w-10 items-center justify-center rounded-2xl"
        style={{ background: "rgba(99,102,241,0.10)" }}
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
          <circle cx="10" cy="10" r="3.5" fill="var(--accent)" opacity="0.85" />
          <path d="M10 3v2.5M10 14.5V17M3 10h2.5M14.5 10H17" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" opacity="0.5" />
        </svg>
      </div>

      <h2
        className="text-[17px] font-semibold tracking-tight"
        style={{ color: "var(--t1)" }}
      >
        Rigovo
      </h2>
      <p
        className="mt-1.5 max-w-xs text-center text-sm leading-relaxed"
        style={{ color: "var(--t3)" }}
      >
        Your AI team. Describe any engineering task — agents plan, build, and ship it for you.
      </p>

      <div className="flex-1" style={{ minHeight: 24 }} />

      {/* Suggestion cards */}
      <div
        className="mb-2.5 self-start text-xs font-semibold tracking-widest uppercase"
        style={{ color: "var(--t4)" }}
      >
        Try an example
      </div>

      <div className="w-full grid grid-cols-3 gap-2.5">
        {EXAMPLES.map((ex) => (
          <button
            key={ex.title}
            type="button"
            className="group text-left transition-all"
            style={{
              border: "1px solid var(--border)",
              borderRadius: "var(--r-xl)",
              background: "var(--overlay)",
              padding: "14px 16px",
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLElement).style.borderColor = "rgba(99,102,241,0.30)";
              (e.currentTarget as HTMLElement).style.boxShadow = "0 2px 8px rgba(99,102,241,0.08)";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLElement).style.borderColor = "var(--border)";
              (e.currentTarget as HTMLElement).style.boxShadow = "none";
            }}
            onClick={() => onSelectExample(ex.title)}
          >
            <div
              className="mb-3 flex h-7 w-7 items-center justify-center rounded-lg text-sm"
              style={{ background: ex.iconBg }}
            >
              {ex.icon}
            </div>
            <span
              className="text-[13px] leading-snug"
              style={{ color: "var(--t2)" }}
            >
              {ex.title}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
