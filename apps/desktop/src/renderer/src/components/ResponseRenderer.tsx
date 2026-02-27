import { Fragment } from "react";

interface ResponseRendererProps {
  output: string;
  maxHeightClass?: string;
}

type Segment =
  | { type: "text"; value: string }
  | { type: "code"; language: string; value: string };

function splitSegments(output: string): Segment[] {
  const segments: Segment[] = [];
  const fence = /```([\w+-]*)\n([\s\S]*?)```/g;
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = fence.exec(output)) !== null) {
    if (match.index > cursor) {
      segments.push({ type: "text", value: output.slice(cursor, match.index) });
    }
    segments.push({
      type: "code",
      language: (match[1] || "text").trim(),
      value: match[2] || "",
    });
    cursor = match.index + match[0].length;
  }

  if (cursor < output.length) {
    segments.push({ type: "text", value: output.slice(cursor) });
  }

  return segments;
}

function inlineCode(text: string): Array<string | JSX.Element> {
  const parts = text.split(/(`[^`]+`)/g);
  return parts.map((part, idx) => {
    if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
      return (
        <code key={idx} className="rounded bg-white/10 px-1 py-0.5 text-[12px] text-slate-200">
          {part.slice(1, -1)}
        </code>
      );
    }
    return part;
  });
}

function renderParagraph(text: string, key: string) {
  const lines = text.split("\n").filter((line) => line.trim().length > 0);
  if (!lines.length) return null;

  if (lines.every((line) => /^\s*[-*]\s+/.test(line))) {
    return (
      <ul key={key} className="list-disc space-y-1 pl-5 text-[13px] leading-relaxed text-slate-300">
        {lines.map((line, idx) => (
          <li key={`${key}-li-${idx}`}>{inlineCode(line.replace(/^\s*[-*]\s+/, ""))}</li>
        ))}
      </ul>
    );
  }

  if (lines.every((line) => /^\s*\d+\.\s+/.test(line))) {
    return (
      <ol key={key} className="list-decimal space-y-1 pl-5 text-[13px] leading-relaxed text-slate-300">
        {lines.map((line, idx) => (
          <li key={`${key}-li-${idx}`}>{inlineCode(line.replace(/^\s*\d+\.\s+/, ""))}</li>
        ))}
      </ol>
    );
  }

  if (lines.length === 1 && /^#{1,4}\s+/.test(lines[0])) {
    const line = lines[0];
    const level = (line.match(/^#+/)?.[0].length ?? 1);
    const content = line.replace(/^#{1,4}\s+/, "");
    const cls =
      level <= 1
        ? "text-[15px] font-semibold text-slate-100"
        : level === 2
          ? "text-[14px] font-semibold text-slate-200"
          : "text-[13px] font-semibold text-slate-300";
    return (
      <p key={key} className={cls}>
        {inlineCode(content)}
      </p>
    );
  }

  return (
    <p key={key} className="text-[13px] leading-relaxed text-slate-300">
      {lines.map((line, idx) => (
        <Fragment key={`${key}-line-${idx}`}>
          {inlineCode(line)}
          {idx < lines.length - 1 ? <br /> : null}
        </Fragment>
      ))}
    </p>
  );
}

function renderText(text: string, key: string) {
  const trimmed = text.trim();
  if (!trimmed) return null;

  try {
    if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
      const pretty = JSON.stringify(JSON.parse(trimmed), null, 2);
      return (
        <div key={key} className="overflow-x-auto rounded-xl border border-white/10 bg-black/20 p-3">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">JSON</p>
          <pre className="whitespace-pre-wrap text-[12px] leading-relaxed text-slate-300">{pretty}</pre>
        </div>
      );
    }
  } catch {
    // Not valid JSON; render as text.
  }

  const paragraphs = text
    .split(/\n\s*\n/g)
    .map((p) => p.trim())
    .filter(Boolean);

  return (
    <div key={key} className="space-y-2.5">
      {paragraphs.map((paragraph, idx) => renderParagraph(paragraph, `${key}-${idx}`))}
    </div>
  );
}

export default function ResponseRenderer({ output, maxHeightClass = "max-h-72" }: ResponseRendererProps) {
  const segments = splitSegments(output);

  return (
    <div className={`space-y-3 overflow-y-auto ${maxHeightClass}`}>
      {segments.map((segment, idx) => {
        if (segment.type === "code") {
          return (
            <div key={`code-${idx}`} className="overflow-x-auto rounded-xl border border-white/10 bg-black/20 p-3">
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                {segment.language || "code"}
              </p>
              <pre className="whitespace-pre-wrap text-[12px] leading-relaxed text-slate-300">{segment.value}</pre>
            </div>
          );
        }
        return renderText(segment.value, `text-${idx}`);
      })}
    </div>
  );
}
