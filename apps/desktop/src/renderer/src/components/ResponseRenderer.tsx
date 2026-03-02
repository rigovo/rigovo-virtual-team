import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import type { Components } from "react-markdown";

interface ResponseRendererProps {
  output: string;
  maxHeightClass?: string;
}

/**
 * Custom component overrides that match the existing Rigovo design language.
 *
 * react-markdown renders markdown AST nodes via these component functions.
 * Every element is styled with the same CSS-variable palette and Tailwind
 * classes the old hand-rolled renderer used, so the visual change is
 * seamless, but now we get full CommonMark + GFM (tables, strikethrough,
 * task lists, autolinks) for free.
 */
const markdownComponents: Components = {
  /* ─── Headings ─── */
  h1: ({ children }) => (
    <h1 className="text-[15px] font-semibold leading-snug text-[var(--ui-text)]">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-[14px] font-semibold leading-snug text-[var(--ui-text)]">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-[13px] font-semibold leading-snug text-[var(--ui-text-secondary)]">{children}</h3>
  ),
  h4: ({ children }) => (
    <h4 className="text-[13px] font-medium text-[var(--ui-text-secondary)]">{children}</h4>
  ),

  /* ─── Paragraphs & inline ─── */
  p: ({ children }) => (
    <p className="text-[13px] leading-relaxed text-[var(--ui-text-secondary)]">{children}</p>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-[var(--ui-text)]">{children}</strong>
  ),
  em: ({ children }) => <em>{children}</em>,
  del: ({ children }) => <del className="opacity-60">{children}</del>,

  /* ─── Lists ─── */
  ul: ({ children }) => (
    <ul className="list-disc space-y-1 pl-5 text-[13px] leading-relaxed text-[var(--ui-text-secondary)]">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="list-decimal space-y-1 pl-5 text-[13px] leading-relaxed text-[var(--ui-text-secondary)]">
      {children}
    </ol>
  ),
  li: ({ children }) => <li>{children}</li>,

  /* ─── Code ─── */
  code: ({ className, children, ...props }) => {
    // Detect fenced code blocks: react-markdown sets className="language-xxx"
    const match = /language-(\w+)/.exec(className || "");
    const isBlock = match || (typeof children === "string" && children.includes("\n"));

    if (isBlock) {
      return (
        <div className="overflow-x-auto rounded-xl border border-[var(--ui-border)] bg-[rgba(0,0,0,0.02)] p-3">
          {match && (
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-[var(--ui-text-muted)]">
              {match[1]}
            </p>
          )}
          <pre className="whitespace-pre-wrap text-[12px] leading-relaxed text-[var(--ui-text-secondary)]">
            <code {...props}>{children}</code>
          </pre>
        </div>
      );
    }

    // Inline code
    return (
      <code
        className="rounded bg-[rgba(0,0,0,0.05)] px-1 py-0.5 text-[12px] text-[var(--ui-text)]"
        {...props}
      >
        {children}
      </code>
    );
  },

  // Override <pre> so react-markdown's default wrapper doesn't nest
  pre: ({ children }) => <>{children}</>,

  /* ─── Tables (GFM) ─── */
  table: ({ children }) => (
    <div className="overflow-x-auto rounded-lg border border-[var(--ui-border)]">
      <table className="w-full border-collapse text-[12px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="bg-[rgba(0,0,0,0.03)]">{children}</thead>
  ),
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => (
    <tr className="border-b border-[var(--ui-border)]">{children}</tr>
  ),
  th: ({ children }) => (
    <th className="px-3 py-1.5 text-left text-[11px] font-semibold uppercase tracking-wider text-[var(--ui-text-muted)]">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="px-3 py-1.5 text-[var(--ui-text-secondary)]">{children}</td>
  ),

  /* ─── Block-level elements ─── */
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-[var(--ui-border)] pl-3 text-[13px] italic text-[var(--ui-text-muted)]">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="border-t border-[var(--ui-border)]" />,

  /* ─── Links ─── */
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-[var(--accent)] underline decoration-[var(--accent)]/30 hover:decoration-[var(--accent)]"
    >
      {children}
    </a>
  ),

  /* ─── Images ─── */
  img: ({ src, alt }) => (
    <img
      src={src}
      alt={alt || ""}
      className="max-w-full rounded-lg border border-[var(--ui-border)]"
      loading="lazy"
    />
  ),
};

export default function ResponseRenderer({ output, maxHeightClass = "max-h-72" }: ResponseRendererProps) {
  if (!output || !output.trim()) return null;

  return (
    <div className={`rr-markdown space-y-2.5 overflow-y-auto ${maxHeightClass}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, rehypeSanitize]}
        components={markdownComponents}
      >
        {output}
      </ReactMarkdown>
    </div>
  );
}
