import { SOURCES, LIVE_SOURCE, useApp } from "../state/store";
import type { Audience } from "../lib/types";
import { cx } from "./ui";
import { UploadButton } from "./Upload";
import { Cpu, Activity, Camera, Radio, FileCode2 } from "lucide-react";

const AUDIENCES: { id: Audience; label: string }[] = [
  { id: "operator", label: "Operator" },
  { id: "maintenance", label: "Maintenance" },
  { id: "controls_engineer", label: "Controls Eng" },
];

export function Topbar() {
  const {
    dossier,
    session,
    mock,
    openDossier,
    sourceId,
    switchSource,
    live,
    loading,
    loadDemo,
    audience,
    setAudience,
    conn,
  } = useApp();
  const ctrl = dossier?.controller;
  const uploaded = !!session?.uploaded;
  const connColor =
    conn === "connected"
      ? "bg-live shadow-[0_0_6px_var(--color-live)]"
      : conn === "connecting"
        ? "bg-warn animate-power"
        : "bg-blocked";

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-line bg-surface px-4">
      <div className="flex items-center gap-3">
        <button onClick={openDossier} className="flex items-center gap-2 group">
          <div className="grid h-6 w-6 place-items-center rounded bg-accent/15 text-accent">
            <Activity size={15} />
          </div>
          <span className="font-semibold tracking-tight text-ink group-hover:text-accent">
            LogixLens
          </span>
          <span className="rounded bg-surface2 px-1.5 py-0.5 text-[10px] uppercase tracking-widest text-muted">
            Ask&nbsp;the&nbsp;PLC
          </span>
        </button>
        <UploadButton />
        {uploaded && (
          <span
            className="flex items-center gap-1.5 rounded border border-line bg-surface2 px-2 py-1 font-mono text-[11px] text-ink"
            title={session?.l5x}
          >
            <FileCode2 size={12} className="text-accent" />
            {session?.filename}
            <button
              onClick={loadDemo}
              className="ml-1 text-[10px] uppercase tracking-wider text-faint hover:text-accent"
              title="Return to the PressLine_3 demo cell"
            >
              demo
            </button>
          </span>
        )}
      </div>

      <div className="flex items-center gap-4 text-xs">
        {ctrl && (
          <div className="flex items-center gap-2 text-muted">
            <Cpu size={14} className="text-faint" />
            <span className="font-mono text-ink">{ctrl.name}</span>
            <span className="text-faint">·</span>
            <span className="font-mono">{ctrl.processor_type}</span>
            <span className="text-faint">·</span>
            <span className="font-mono">
              v{ctrl.major_revision}.{ctrl.minor_revision}
            </span>
          </div>
        )}
        {/* value-source selector: static snapshots + the live OPC UA cell.
            Snapshots and the simulator belong to the demo cell — for an
            uploaded program the analysis is static, so hide the selector. */}
        {uploaded ? (
          <span
            className="flex items-center gap-1.5 rounded border border-line bg-surface2 px-2 py-1 font-mono text-[11px] text-muted"
            title="Uploaded programs are analyzed statically (no live values attached)"
          >
            <Camera size={12} className="text-faint" /> static analysis
          </span>
        ) : (
        <label
          className={cx(
            "flex items-center gap-1.5 rounded border px-2 py-1",
            live ? "border-live/50 bg-live/10" : "border-line bg-surface2"
          )}
          title="Value source for power flow and interlock evaluation (static snapshot or the live OPC UA cell)"
        >
          {live ? (
            <Radio size={12} className="text-live" />
          ) : (
            <Camera size={12} className="text-faint" />
          )}
          <select
            value={sourceId}
            disabled={loading}
            onChange={(e) => switchSource(e.target.value)}
            className="bg-transparent font-mono text-[11px] text-ink outline-none disabled:opacity-50"
          >
            {SOURCES.map((s) => (
              <option key={s.id || "none"} value={s.id} className="bg-surface text-ink">
                {s.id === LIVE_SOURCE ? "● " : ""}
                {s.label}
              </option>
            ))}
          </select>
        </label>
        )}

        {/* audience toggle */}
        <div
          className="flex overflow-hidden rounded border border-line"
          title="Answer register — same facts, three phrasings"
        >
          {AUDIENCES.map((a) => (
            <button
              key={a.id}
              onClick={() => setAudience(a.id)}
              className={cx(
                "px-2 py-1 text-[10px] uppercase tracking-wider transition-colors",
                audience === a.id
                  ? "bg-accent/15 text-accent"
                  : "bg-surface2 text-faint hover:text-muted"
              )}
            >
              {a.label}
            </button>
          ))}
        </div>

        <span
          className={cx(
            "rounded border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider",
            mock ? "border-warn/40 text-warn" : "border-accent-dim text-accent"
          )}
          title={
            mock
              ? "Deterministic mock model (full pipeline, no model call)"
              : session?.provider === "subscription"
                ? "Real Claude via your local Claude Code login (no API billing)"
                : "Real Claude via the Anthropic API"
          }
        >
          {mock ? "mock" : session?.provider === "subscription" ? "claude · sub" : "claude"}
        </span>

        {/* chat connection dot */}
        <span className="flex items-center gap-1.5" title={`chat socket: ${conn}`}>
          <span className={cx("h-2 w-2 rounded-full", connColor)} />
        </span>
      </div>
    </header>
  );
}
