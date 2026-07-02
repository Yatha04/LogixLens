import { SNAPSHOTS, useApp } from "../state/store";
import type { Audience } from "../lib/types";
import { cx } from "./ui";
import { Cpu, Activity, Camera } from "lucide-react";

const AUDIENCES: { id: Audience; label: string }[] = [
  { id: "operator", label: "Operator" },
  { id: "maintenance", label: "Maintenance" },
  { id: "controls_engineer", label: "Controls Eng" },
];

export function Topbar() {
  const {
    dossier,
    mock,
    openDossier,
    snapshot,
    switchSnapshot,
    loading,
    audience,
    setAudience,
    conn,
  } = useApp();
  const ctrl = dossier?.controller;
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
        {/* snapshot selector */}
        <label
          className="flex items-center gap-1.5 rounded border border-line bg-surface2 px-2 py-1"
          title="Live-value snapshot used for power flow and interlock evaluation"
        >
          <Camera size={12} className="text-faint" />
          <select
            value={snapshot ?? ""}
            disabled={loading}
            onChange={(e) => switchSnapshot(e.target.value || null)}
            className="bg-transparent font-mono text-[11px] text-ink outline-none disabled:opacity-50"
          >
            {SNAPSHOTS.map((s) => (
              <option key={s.label} value={s.id ?? ""} className="bg-surface text-ink">
                {s.label}
              </option>
            ))}
          </select>
        </label>

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
          title={mock ? "Deterministic mock model (full pipeline, no API key)" : "Live model"}
        >
          {mock ? "mock" : "live"}
        </span>

        {/* chat connection dot */}
        <span className="flex items-center gap-1.5" title={`chat socket: ${conn}`}>
          <span className={cx("h-2 w-2 rounded-full", connColor)} />
        </span>
      </div>
    </header>
  );
}
