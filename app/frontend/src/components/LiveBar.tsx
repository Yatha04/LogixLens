/**
 * LiveBar — the live-mode control surface, shown under the Topbar only when the
 * session is backed by the OPC UA simulator.
 *
 *   • status strip: machine-state badge, cycling indicator, active fault,
 *     good/reject counters + hydraulic pressure — polled ~1s (paused only when
 *     the tab is genuinely backgrounded, see lib/poll.ts; values update in
 *     place, no remount / flicker).
 *   • CHAOS panel: one button per fault (the demo's fault-injection control)
 *     plus Clear / Reset, proxied through the backend to the sim's chaos API.
 */
import { useState } from "react";
import { AlertTriangle, Radio, Zap } from "lucide-react";
import { useApp } from "../state/store";
import { getLiveStatus, injectChaos, clearChaos } from "../lib/api";
import { CHAOS_FAULTS, type ChaosFault, type LiveStatus } from "../lib/types";
import { usePolling } from "../lib/poll";
import { cx } from "./ui";

const STATE_TONE: Record<string, string> = {
  RUNNING: "border-live/50 bg-live/10 text-live",
  STARTING: "border-warn/50 bg-warn/10 text-warn",
  FAULTED: "border-blocked/50 bg-blocked/10 text-blocked",
  STOPPED: "border-line2 bg-surface2 text-muted",
};

const FAULT_LABEL: Record<ChaosFault, string> = {
  guard_door_open: "Guard Door",
  light_curtain_break: "Light Curtain",
  estop: "E-Stop",
  infeed_jam: "Infeed Jam",
  press_overtemp: "Overtemp",
  drive_fault: "Drive Fault",
  hydraulic_low: "Hyd Low",
};

export function LiveBar() {
  const { sid, live } = useApp();
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  usePolling(
    () => {
      if (!sid) return;
      getLiveStatus(sid)
        .then((s) => {
          setStatus(s);
          setErr(null);
        })
        .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
    },
    1000,
    !!(live && sid)
  );

  if (!live) return null;

  const fault = status?.active_fault ?? null;

  const act = async (fn: () => Promise<LiveStatus>) => {
    if (!sid) return;
    setBusy(true);
    try {
      setStatus(await fn());
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const stateBadge = status ? STATE_TONE[status.state] ?? STATE_TONE.STOPPED : STATE_TONE.STOPPED;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-surface px-4 py-2 text-xs">
      {/* ── status strip ─────────────────────────────────────────────── */}
      <div className="flex items-center gap-2">
        <Radio size={13} className="text-live" />
        <span className="text-[10px] font-semibold uppercase tracking-widest text-live">Live</span>
      </div>

      <span
        className={cx(
          "rounded border px-2 py-0.5 font-mono text-[10px] font-bold uppercase tracking-wider",
          stateBadge
        )}
      >
        {status?.state ?? "…"}
      </span>

      <span className="flex items-center gap-1.5 text-muted" title="Press is actively cycling">
        <span
          className={cx(
            "h-2 w-2 rounded-full",
            status?.cycling ? "bg-live shadow-[0_0_6px_var(--color-live)] animate-pulse" : "bg-idle"
          )}
        />
        <span className="font-mono">{status?.cycling ? "cycling" : "idle"}</span>
      </span>

      <span
        className={cx(
          "flex items-center gap-1 font-mono",
          fault ? "text-blocked" : "text-faint"
        )}
      >
        {fault ? <AlertTriangle size={12} /> : null}
        fault: {fault ?? "none"}
      </span>

      <span className="font-mono text-muted" title="Good / reject part counters">
        <span className="text-live">{status?.good_parts ?? 0}</span>
        <span className="text-faint"> good · </span>
        <span className="text-warn">{status?.reject_parts ?? 0}</span>
        <span className="text-faint"> reject</span>
      </span>

      {status?.key_values?.Hyd_Pressure !== undefined && (
        <span className="font-mono text-muted" title="Hydraulic pressure (PSI)">
          {Number(status.key_values.Hyd_Pressure).toFixed(0)} psi
        </span>
      )}

      {/* ── CHAOS panel ──────────────────────────────────────────────── */}
      <div className="ml-auto flex flex-wrap items-center gap-1.5">
        <span className="flex items-center gap-1 text-[10px] uppercase tracking-widest text-faint">
          <Zap size={11} /> chaos
        </span>
        {CHAOS_FAULTS.map((f) => (
          <button
            key={f}
            disabled={busy}
            onClick={() => act(() => injectChaos(sid!, f))}
            title={`Inject ${f}`}
            className={cx(
              "rounded border px-2 py-0.5 font-mono text-[10px] transition-colors disabled:opacity-40",
              fault === f
                ? "border-blocked bg-blocked/15 text-blocked"
                : "border-line2 text-muted hover:border-blocked/60 hover:text-blocked"
            )}
          >
            {FAULT_LABEL[f]}
          </button>
        ))}
        <button
          disabled={busy}
          onClick={() => act(() => clearChaos(sid!))}
          title="Clear the active fault and run the reset handshake"
          className="rounded border border-live/50 bg-live/10 px-2 py-0.5 font-mono text-[10px] text-live transition-colors hover:bg-live/20 disabled:opacity-40"
        >
          Clear / Reset
        </button>
      </div>

      {err && (
        <span className="w-full font-mono text-[10px] text-blocked" role="alert">
          {err}
        </span>
      )}
    </div>
  );
}
