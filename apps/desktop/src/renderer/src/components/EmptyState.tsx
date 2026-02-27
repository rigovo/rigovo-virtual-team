/* ------------------------------------------------------------------ */
/*  EmptyState — premium centered onboarding, Codex-inspired           */
/* ------------------------------------------------------------------ */

interface EmptyStateProps {
  onSelectExample: (text: string) => void;
}

const EXAMPLES = [
  {
    emoji: "\uD83D\uDC1B",
    title: "Build a classic Snake game in this repo.",
    color: "#e8e8e6",
  },
  {
    emoji: "\uD83D\uDCC4",
    title: "Create a one-page $pdf that summarizes this app.",
    color: "#fce4e4",
  },
  {
    emoji: "\u270F\uFE0F",
    title: "Create a plan to refactor the auth module.",
    color: "#fef3cd",
  },
];

export default function EmptyState({ onSelectExample }: EmptyStateProps) {
  return (
    <div className="flex h-full flex-col items-center justify-center animate-fadeup">
      {/* Icon */}
      <div className="mb-5 flex h-12 w-12 items-center justify-center">
        <svg
          width="40"
          height="40"
          viewBox="0 0 40 40"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <circle
            cx="20"
            cy="20"
            r="18"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeDasharray="4 3"
            opacity="0.25"
          />
          <circle cx="20" cy="20" r="3" fill="currentColor" opacity="0.5" />
          <path
            d="M20 12v-2M20 30v-2M28 20h2M10 20h2"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            opacity="0.25"
          />
        </svg>
      </div>

      {/* Heading */}
      <h2
        className="text-2xl font-semibold tracking-tight"
        style={{ color: "var(--ui-text)" }}
      >
        Let&apos;s build
      </h2>

      {/* Dropdown hint */}
      <button
        type="button"
        className="mt-1 flex items-center gap-1 text-base transition-colors"
        style={{ color: "var(--ui-text-muted)" }}
      >
        Documents
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path
            d="M3 4.5l3 3 3-3"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Explore more */}
      <div className="mb-3 self-end px-2">
        <span
          className="text-xs"
          style={{ color: "var(--ui-text-subtle)" }}
        >
          Explore more
        </span>
      </div>

      {/* Suggestion cards — Codex style */}
      <div className="w-full grid grid-cols-3 gap-3 px-2">
        {EXAMPLES.map((ex) => (
          <button
            key={ex.title}
            type="button"
            className="group rounded-2xl border px-4 py-4 text-left transition-all hover:shadow-card"
            style={{
              borderColor: "var(--ui-border)",
              background: "var(--ui-panel)",
            }}
            onClick={() => onSelectExample(ex.title)}
          >
            <div
              className="mb-3 flex h-8 w-8 items-center justify-center rounded-lg text-base"
              style={{ background: ex.color }}
            >
              {ex.emoji}
            </div>
            <span
              className="text-sm leading-snug transition-colors group-hover:text-[var(--ui-text)]"
              style={{ color: "var(--ui-text-secondary)" }}
            >
              {ex.title}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
