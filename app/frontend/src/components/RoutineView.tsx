import { useEffect, useRef, useState } from "react";
import { useApp } from "../state/store";
import { getRoutine, getRung } from "../lib/api";
import type { RoutinePayload, RungPayload } from "../lib/types";
import { Ladder } from "./Ladder";
import { cx, RoutineTypeTag } from "./ui";
import { energizeRung } from "../lib/powerflow";
import { usePolling } from "../lib/poll";
import { Code2, Hash } from "lucide-react";

interface RoutineViewProps {
  view: { program: string; routine: string; highlightRung?: number };
}

const STATE_LABEL: Record<string, { text: string; cls: string }> = {
  conducting: { text: "CONDUCTING", cls: "text-live border-live/40 bg-live/10" },
  blocked: { text: "BLOCKED", cls: "text-blocked border-blocked/40 bg-blocked/10" },
  indeterminate: { text: "INDETERMINATE", cls: "text-idle border-line2 bg-surface2" },
  unknown: { text: "STATIC", cls: "text-faint border-line2" },
};

export function RoutineView({ view }: RoutineViewProps) {
  const { sid, snapshot, live, openTrace } = useApp();
  const [routine, setRoutine] = useState<RoutinePayload | null>(null);
  const [rungs, setRungs] = useState<Record<number, RungPayload>>({});
  const [showRaw, setShowRaw] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sid) return;
    let alive = true;
    setRoutine(null);
    setRungs({});
    setError(null);
    (async () => {
      try {
        const r = await getRoutine(sid, view.program, view.routine);
        if (!alive) return;
        setRoutine(r);
        if (r.type === "RLL" && r.rungs) {
          const entries = await Promise.all(
            r.rungs.map((rg) =>
              getRung(sid, view.program, view.routine, rg.number, snapshot).then(
                (p) => [rg.number, p] as const
              )
            )
          );
          if (alive) setRungs(Object.fromEntries(entries));
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      alive = false;
    };
  }, [sid, view.program, view.routine, snapshot]);

  // Live mode: re-read the ladder ~1.5s so power flow tracks the running cell.
  // Values update in place (the rung blocks stay mounted, keyed by number), so
  // no flicker — only contact/coil states change as the machine changes.
  usePolling(
    () => {
      if (!sid || routine?.type !== "RLL" || !routine.rungs) return;
      Promise.all(
        routine.rungs.map((rg) =>
          getRung(sid, view.program, view.routine, rg.number).then(
            (p) => [rg.number, p] as const
          )
        )
      )
        .then((entries) => setRungs(Object.fromEntries(entries)))
        .catch(() => { /* transient poll error — keep last-good values */ });
    },
    1500,
    !!(live && sid && routine?.type === "RLL")
  );

  if (error) return <div className="p-6 text-blocked">{error}</div>;
  if (!routine) return <div className="p-6 text-muted animate-power">loading routine…</div>;

  return (
    <div className="mx-auto max-w-5xl p-5">
      <header className="mb-4 flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2">
            <RoutineTypeTag type={routine.type} />
            <h1 className="font-mono text-xl font-bold text-ink">{routine.routine}</h1>
          </div>
          <p className="mt-0.5 text-sm text-muted">
            {view.program} {routine.description ? `· ${routine.description}` : ""}
          </p>
        </div>
        {routine.type === "RLL" && (
          <button
            onClick={() => setShowRaw((s) => !s)}
            className={cx(
              "flex items-center gap-1.5 rounded border px-2.5 py-1 text-xs",
              showRaw ? "border-accent text-accent" : "border-line2 text-muted hover:text-ink"
            )}
          >
            <Code2 size={13} /> raw text
          </button>
        )}
      </header>

      {routine.type === "RLL" &&
        routine.rungs?.map((rg) => (
          <RungBlock
            key={rg.number}
            number={rg.number}
            comment={rg.comment}
            payload={rungs[rg.number]}
            showRaw={showRaw}
            highlight={view.highlightRung === rg.number}
            onTagClick={openTrace}
          />
        ))}

      {routine.type === "ST" && (
        <pre className="overflow-x-auto rounded-lg border border-line bg-surface p-4 font-mono text-xs leading-relaxed text-ink">
          {routine.lines?.map((l) => `${String(l.number).padStart(3, " ")}  ${l.text}`).join("\n")}
        </pre>
      )}

      {routine.type === "SFC" && routine.sfc && (
        <div className="grid grid-cols-2 gap-4">
          <SfcList title="Steps" items={routine.sfc.steps} />
          <SfcList title="Transitions" items={routine.sfc.transitions} />
        </div>
      )}
    </div>
  );
}

function RungBlock({
  number,
  comment,
  payload,
  showRaw,
  highlight,
  onTagClick,
}: {
  number: number;
  comment: string;
  payload?: RungPayload;
  showRaw: boolean;
  highlight: boolean;
  onTagClick: (tag: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (highlight && ref.current) {
      ref.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlight]);

  const state = payload ? energizeRung(payload.elements, payload.values).state : "unknown";
  const badge = STATE_LABEL[state];

  return (
    <div
      ref={ref}
      className={cx(
        "mb-3 rounded-lg border bg-surface transition-shadow",
        highlight ? "border-accent shadow-[0_0_0_1px_var(--color-accent)]" : "border-line"
      )}
    >
      <div className="flex items-center gap-2 border-b border-line px-3 py-1.5">
        <span className="flex items-center gap-1 font-mono text-xs text-faint">
          <Hash size={11} />
          {number}
        </span>
        <span
          className={cx("rounded border px-1.5 py-0.5 font-mono text-[9px] tracking-wider", badge.cls)}
        >
          {badge.text}
        </span>
        {comment && <span className="truncate text-xs text-muted" title={comment}>{comment}</span>}
      </div>
      <div className="p-2">
        {payload ? (
          <Ladder
            elements={payload.elements}
            values={payload.values}
            tags={payload.tags}
            onTagClick={onTagClick}
          />
        ) : (
          <div className="p-6 text-center text-xs text-faint">rendering…</div>
        )}
        {showRaw && payload && (
          <pre className="mt-1 overflow-x-auto border-t border-line px-2 pt-2 font-mono text-[11px] text-muted">
            {payload.text}
          </pre>
        )}
      </div>
    </div>
  );
}

function SfcList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-3">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>
      <ul className="space-y-1 font-mono text-xs text-ink">
        {items.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ul>
    </div>
  );
}
