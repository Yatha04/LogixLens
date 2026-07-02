/**
 * InterlockTree.tsx — collapsible condition tree from /api/trace: what it
 * would take for a tag to go true. Satisfied nodes green, unsatisfied red,
 * unknown grey; AND/OR badges; FLAG nodes amber with the honesty annotation;
 * failing paths auto-expanded; every cite clickable into the ladder view.
 * Includes a Trace input with tag autocomplete (backed by /api/tags).
 */

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Crosshair,
  Loader2,
  Repeat,
  X,
} from "lucide-react";
import { getTrace, searchTags, type TagHit } from "../lib/api";
import type { Cite, ConditionNode, TracePayload } from "../lib/types";
import { useApp } from "../state/store";
import { usePolling } from "../lib/poll";

// ── small bits ───────────────────────────────────────────────────────────

function SatIcon({ satisfied }: { satisfied: boolean | null }) {
  if (satisfied === true) return <Check size={13} className="shrink-0 text-live" />;
  if (satisfied === false) return <X size={13} className="shrink-0 text-blocked" />;
  return <CircleHelp size={13} className="shrink-0 text-faint" />;
}

export function CiteChip({ cite, onClick }: { cite: Cite; onClick: (c: Cite) => void }) {
  return (
    <button
      onClick={() => onClick(cite)}
      title={`Open ${cite.program}/${cite.routine} rung ${cite.rung_number} in the ladder view`}
      className="ml-1 inline-flex items-center gap-1 rounded border border-line bg-surface2 px-1.5 py-[1px] font-mono text-[10px] text-accent transition-colors hover:border-accent/60 hover:bg-accent/10"
    >
      {cite.program}/{cite.routine}:{cite.rung_number}
    </button>
  );
}

function requirementLabel(node: ConditionNode): string {
  if (node.requirement === "needs_true") return "must be TRUE";
  if (node.requirement === "needs_false") return "must be FALSE";
  if (node.requirement === "comparison" && node.comparison) {
    const c = node.comparison as { op?: string; operands?: { value: string }[] };
    if (c.op) return `${c.op}(${(c.operands ?? []).map((o) => o.value).join(", ")})`;
    return "comparison";
  }
  return "";
}

// ── tree node ────────────────────────────────────────────────────────────

function TreeNode({
  node,
  depth,
  onCite,
  onTrace,
}: {
  node: ConditionNode;
  depth: number;
  onCite: (c: Cite) => void;
  onTrace: (tag: string) => void;
}) {
  // failing / unknown paths open by default; satisfied subtrees collapsed
  const [open, setOpen] = useState(node.satisfied !== true || depth < 1);
  const hasKids = node.children.length > 0;
  const isGroup = node.kind === "AND" || node.kind === "OR";
  const failing = node.satisfied === false;

  const rowColor = failing ? "text-blocked" : node.satisfied === true ? "text-live" : "text-muted";

  return (
    <div className={depth > 0 ? "border-l border-line/70 pl-3" : ""}>
      <div
        className={`group flex items-start gap-1.5 rounded px-1 py-[3px] text-[12px] leading-tight ${
          failing ? "bg-blocked/[0.07]" : ""
        }`}
      >
        {hasKids ? (
          <button onClick={() => setOpen(!open)} className="mt-[1px] text-faint hover:text-ink">
            {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          </button>
        ) : (
          <span className="w-[13px]" />
        )}
        <span className="mt-[1px]">
          <SatIcon satisfied={node.satisfied} />
        </span>

        {isGroup && (
          <span
            className={`rounded px-1 py-[1px] font-mono text-[9px] font-bold tracking-wider ${
              node.kind === "AND"
                ? "bg-line/70 text-ink/80"
                : "bg-accent/15 text-accent"
            }`}
          >
            {node.kind}
          </span>
        )}

        {node.kind === "FLAG" && (
          <span className="flex items-center gap-1 rounded bg-warn/15 px-1 py-[1px] text-[9px] font-bold tracking-wider text-warn">
            <AlertTriangle size={10} /> FLAG
          </span>
        )}
        {node.kind === "LATCH" && (
          <span className="flex items-center gap-1 rounded bg-line/70 px-1 py-[1px] text-[9px] font-bold tracking-wider text-ink/70">
            <Repeat size={10} /> LATCH
          </span>
        )}

        <span className="min-w-0">
          {node.tag && (
            <button
              onClick={() => onTrace(node.tag!)}
              title={`Trace ${node.tag}`}
              className={`font-mono text-[12px] ${rowColor} underline-offset-2 hover:underline`}
            >
              {node.full_path ?? node.tag}
            </button>
          )}
          {requirementLabel(node) && (
            <span className="ml-1.5 text-[10px] text-faint">{requirementLabel(node)}</span>
          )}
          {node.cite && <CiteChip cite={node.cite} onClick={onCite} />}
          {node.annotation && (
            <div
              className={`mt-0.5 max-w-[46ch] text-[10.5px] leading-snug ${
                node.kind === "FLAG" ? "text-warn/90" : "text-faint"
              }`}
            >
              {node.annotation}
            </div>
          )}
        </span>
      </div>

      {open && hasKids && (
        <div className="ml-2 mt-0.5 flex flex-col gap-0.5">
          {node.children.map((c, i) => (
            <TreeNode key={i} node={c} depth={depth + 1} onCite={onCite} onTrace={onTrace} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── trace input with autocomplete ────────────────────────────────────────

function TraceInput({ initial, onTrace }: { initial: string; onTrace: (tag: string) => void }) {
  const { sid } = useApp();
  const [text, setText] = useState(initial);
  const [hits, setHits] = useState<TagHit[]>([]);
  const [openList, setOpenList] = useState(false);
  const [hi, setHi] = useState(0);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => setText(initial), [initial]);

  const query = (q: string) => {
    setText(q);
    window.clearTimeout(timer.current);
    if (!sid || q.trim().length < 2) {
      setHits([]);
      setOpenList(false);
      return;
    }
    timer.current = window.setTimeout(async () => {
      try {
        const res = await searchTags(sid, q.trim(), 8);
        setHits(res.tags);
        setOpenList(res.tags.length > 0);
        setHi(0);
      } catch {
        setHits([]);
      }
    }, 140);
  };

  const commit = (tag: string) => {
    setOpenList(false);
    if (tag.trim()) onTrace(tag.trim());
  };

  return (
    <div className="relative">
      <div className="flex items-center gap-2 rounded border border-line bg-surface2 px-2 py-1.5 focus-within:border-accent/60">
        <Crosshair size={13} className="text-faint" />
        <input
          value={text}
          onChange={(e) => query(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit(openList && hits[hi] ? hits[hi].name : text);
            else if (e.key === "ArrowDown" && openList) setHi((h) => Math.min(h + 1, hits.length - 1));
            else if (e.key === "ArrowUp" && openList) setHi((h) => Math.max(h - 1, 0));
            else if (e.key === "Escape") setOpenList(false);
          }}
          onBlur={() => window.setTimeout(() => setOpenList(false), 150)}
          placeholder="Trace any tag… (e.g. Press_Cycle_Start)"
          spellCheck={false}
          className="w-full bg-transparent font-mono text-[12px] text-ink outline-none placeholder:text-faint"
        />
      </div>
      {openList && (
        <div className="absolute left-0 right-0 top-full z-20 mt-1 overflow-hidden rounded border border-line bg-surface shadow-xl shadow-black/50">
          {hits.map((h, i) => (
            <button
              key={h.name}
              onMouseDown={(e) => {
                e.preventDefault();
                commit(h.name);
              }}
              className={`flex w-full items-baseline gap-2 px-2 py-1.5 text-left ${
                i === hi ? "bg-accent/10" : "hover:bg-surface2"
              }`}
            >
              <span className="font-mono text-[12px] text-ink">{h.name}</span>
              <span className="font-mono text-[9px] text-faint">{h.data_type}</span>
              {h.description && (
                <span className="truncate text-[10px] text-muted">{h.description}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ── the panel ────────────────────────────────────────────────────────────

export default function InterlockTree({ tag }: { tag: string }) {
  const { sid, snapshot, live, openRoutine, openTrace } = useApp();
  const [trace, setTrace] = useState<TracePayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sid) return;
    let cancelled = false;
    setTrace(null);
    setError(null);
    getTrace(sid, tag, snapshot)
      .then((t) => !cancelled && setTrace(t))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [sid, tag, snapshot]);

  // Live mode: re-trace ~1.5s so the interlock tree re-evaluates against the
  // running cell. setTrace updates the existing tree in place (never back to
  // null), so the panel doesn't flash a loader on each poll.
  usePolling(
    () => {
      if (!sid) return;
      getTrace(sid, tag, snapshot)
        .then((t) => setTrace(t))
        .catch(() => { /* transient poll error — keep last-good trace */ });
    },
    1500,
    !!(live && sid)
  );

  const onCite = (c: Cite) => openRoutine(c.program, c.routine, c.rung_number);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-line px-3 py-2.5">
        <TraceInput initial={tag} onTrace={openTrace} />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {error && (
          <div className="flex items-center gap-2 rounded border border-blocked/40 bg-blocked/10 p-3 text-sm text-blocked">
            <AlertTriangle size={16} /> {error}
          </div>
        )}
        {!trace && !error && (
          <div className="flex items-center gap-2 p-3 text-sm text-muted">
            <Loader2 size={16} className="animate-spin" /> tracing {tag}…
          </div>
        )}

        {trace && (
          <div className="fade-up">
            {/* verdict banner */}
            <div
              className={`mb-3 flex items-center gap-2 rounded border px-3 py-2 text-[12px] ${
                trace.root_satisfied === false
                  ? "border-blocked/50 bg-blocked/10 text-blocked"
                  : trace.root_satisfied === true
                    ? "border-live/40 bg-live/10 text-live"
                    : "border-line bg-surface2 text-muted"
              }`}
            >
              <SatIcon satisfied={trace.root_satisfied ?? null} />
              <span className="font-mono font-semibold">{trace.target}</span>
              {trace.root_satisfied === false && (
                <span>
                  blocked — {trace.failing_count} failing path{trace.failing_count === 1 ? "" : "s"}
                </span>
              )}
              {trace.root_satisfied === true && <span>satisfied under the current snapshot</span>}
              {(trace.root_satisfied === null || trace.root_satisfied === undefined) && (
                <span>static trace — select a snapshot to evaluate live</span>
              )}
            </div>

            {/* failing chains, when live */}
            {trace.failing_paths && trace.failing_paths.length > 0 && (
              <div className="mb-3 rounded border border-blocked/30 bg-surface2/70 p-2.5">
                <div className="mb-1 text-[10px] uppercase tracking-wider text-faint">
                  failing chain{trace.failing_paths.length === 1 ? "" : "s"}
                </div>
                {trace.failing_paths.map((p, i) => (
                  <div key={i} className="flex flex-wrap items-center gap-1 py-0.5 font-mono text-[11.5px]">
                    {p.chain.map((t, j) => (
                      <span key={j} className="flex items-center gap-1">
                        {j > 0 && <span className="text-faint">→</span>}
                        <button
                          onClick={() => openTrace(t)}
                          className={
                            j === p.chain.length - 1
                              ? "font-semibold text-blocked hover:underline"
                              : "text-ink/80 hover:underline"
                          }
                        >
                          {t}
                        </button>
                      </span>
                    ))}
                    {p.nodes[p.nodes.length - 1]?.cite && (
                      <CiteChip cite={p.nodes[p.nodes.length - 1].cite!} onClick={onCite} />
                    )}
                  </div>
                ))}
              </div>
            )}

            <TreeNode node={trace.tree} depth={0} onCite={onCite} onTrace={openTrace} />
          </div>
        )}
      </div>
    </div>
  );
}
