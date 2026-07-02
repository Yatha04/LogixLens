import { useEffect, useRef } from "react";

/**
 * Should a poll tick be skipped right now?
 *
 * Only when the tab is hidden AND the document doesn't have focus — i.e. the
 * user has genuinely backgrounded it (switched tab, minimized the window).
 *
 * `document.hidden` alone is NOT a safe gate: Chrome reports occluded windows
 * and automation-driven tabs (screenshot/CDP sessions) as `hidden` even while
 * they are focused and actively watched — gating on it silently froze all live
 * polling in exactly those environments while the initial (ungated) fetch made
 * the page look alive. `hasFocus()` stays true in those cases, so requiring
 * BOTH signals pauses background tabs without ever starving a watched one.
 * (Chrome additionally throttles hidden-tab timers natively, so a genuinely
 * backgrounded tab never hammers the backend regardless.)
 */
export function pollPaused(): boolean {
  return document.hidden && !document.hasFocus();
}

/**
 * Run `fn` once immediately, then every `intervalMs`, while `enabled`.
 *
 * Ticks are skipped while the tab is genuinely backgrounded (see
 * `pollPaused`); when the tab becomes visible again an immediate refresh
 * fires so the UI catches up without waiting out the interval.
 *
 * `fn` is kept in a ref so callers can pass an inline async function without
 * resetting the interval every render.
 */
export function usePolling(fn: () => void, intervalMs: number, enabled: boolean) {
  const saved = useRef(fn);
  saved.current = fn;

  useEffect(() => {
    if (!enabled) return;

    const tick = () => {
      if (!pollPaused()) saved.current();
    };

    const onVisibility = () => {
      // immediate catch-up refresh the moment the tab is foregrounded
      if (!document.hidden) saved.current();
    };

    saved.current(); // fire immediately
    const timer = window.setInterval(tick, intervalMs);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [intervalMs, enabled]);
}
