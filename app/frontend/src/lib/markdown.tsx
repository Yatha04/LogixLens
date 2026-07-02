/**
 * markdown.tsx — a deliberately tiny markdown renderer for chat answers.
 * Supports the subset the model actually emits: headings, bold/italic,
 * inline code, fenced code blocks, and bullet / numbered lists. No external
 * dependency, no HTML injection (everything renders as React text nodes).
 */

import type { ReactNode } from "react";

function renderInline(text: string, keyBase: string): ReactNode[] {
  // tokenize `code`, **bold**, *italic*
  const out: ReactNode[] = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("`")) {
      out.push(
        <code
          key={`${keyBase}-${k++}`}
          className="rounded bg-surface2 px-1 py-[1px] font-mono text-[0.92em] text-accent"
        >
          {tok.slice(1, -1)}
        </code>,
      );
    } else if (tok.startsWith("**")) {
      out.push(
        <strong key={`${keyBase}-${k++}`} className="font-semibold text-ink">
          {tok.slice(2, -2)}
        </strong>,
      );
    } else {
      out.push(
        <em key={`${keyBase}-${k++}`}>{tok.slice(1, -1)}</em>,
      );
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function renderMarkdown(text: string): ReactNode {
  const blocks: ReactNode[] = [];
  const lines = text.split("\n");
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    // fenced code block
    if (line.trimStart().startsWith("```")) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trimStart().startsWith("```")) {
        buf.push(lines[i]);
        i++;
      }
      i++; // closing fence
      blocks.push(
        <pre
          key={key++}
          className="my-1.5 overflow-x-auto rounded border border-line bg-surface2 p-2 font-mono text-[11px] leading-relaxed text-ink/90"
        >
          {buf.join("\n")}
        </pre>,
      );
      continue;
    }

    // heading
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      blocks.push(
        <div key={key++} className="mt-2 mb-0.5 text-[0.95em] font-semibold text-ink">
          {renderInline(h[2], `h${key}`)}
        </div>,
      );
      i++;
      continue;
    }

    // list block (bullet or numbered)
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const items: ReactNode[] = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        const item = lines[i].replace(/^\s*([-*]|\d+\.)\s+/, "");
        items.push(
          <li key={items.length} className="my-0.5">
            {renderInline(item, `li${key}-${items.length}`)}
          </li>,
        );
        i++;
      }
      blocks.push(
        <ul key={key++} className="my-1 list-disc pl-5 marker:text-faint">
          {items}
        </ul>,
      );
      continue;
    }

    // blank line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // paragraph: greedily absorb consecutive plain lines
    const para: string[] = [line];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !/^\s*([-*]|\d+\.)\s+/.test(lines[i]) &&
      !/^#{1,4}\s+/.test(lines[i]) &&
      !lines[i].trimStart().startsWith("```")
    ) {
      para.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={key++} className="my-1 leading-relaxed">
        {renderInline(para.join(" "), `p${key}`)}
      </p>,
    );
  }

  return <>{blocks}</>;
}
