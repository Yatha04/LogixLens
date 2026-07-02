/**
 * Regression tests for usePolling — specifically the visibility gate.
 *
 * The live-ladder staleness bug: Chrome reports automation-driven and occluded
 * tabs as `document.hidden === true` even while they're focused and actively
 * watched. Gating ticks on `document.hidden` alone silently disabled ALL live
 * polling in those environments (the ungated initial fire made pages look
 * alive). Polling must only pause when the tab is hidden AND unfocused.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { usePolling, pollPaused } from "./poll";

function setVisibility(hidden: boolean, focused: boolean) {
  vi.spyOn(document, "hidden", "get").mockReturnValue(hidden);
  vi.spyOn(document, "visibilityState", "get").mockReturnValue(
    hidden ? "hidden" : "visible"
  );
  document.hasFocus = vi.fn(() => focused);
}

describe("usePolling visibility gate", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("fires immediately and then on every interval while visible", () => {
    setVisibility(false, true);
    const fn = vi.fn();
    renderHook(() => usePolling(fn, 1000, true));
    expect(fn).toHaveBeenCalledTimes(1); // immediate
    act(() => void vi.advanceTimersByTime(3100));
    expect(fn).toHaveBeenCalledTimes(4);
  });

  it("REGRESSION: keeps polling when the tab reports hidden but has focus (automation / occluded window)", () => {
    // exactly the browser state that froze the live ladder:
    // document.hidden === true, document.hasFocus() === true
    setVisibility(true, true);
    const fn = vi.fn();
    renderHook(() => usePolling(fn, 1000, true));
    act(() => void vi.advanceTimersByTime(3100));
    expect(fn.mock.calls.length).toBeGreaterThanOrEqual(4); // NOT frozen
  });

  it("pauses ticks when the tab is hidden AND unfocused (genuinely backgrounded)", () => {
    setVisibility(true, false);
    const fn = vi.fn();
    renderHook(() => usePolling(fn, 1000, true));
    expect(fn).toHaveBeenCalledTimes(1); // initial fire still happens
    act(() => void vi.advanceTimersByTime(5000));
    expect(fn).toHaveBeenCalledTimes(1); // no ticks while backgrounded
  });

  it("refreshes immediately when the tab becomes visible again", () => {
    setVisibility(true, false);
    const fn = vi.fn();
    renderHook(() => usePolling(fn, 1000, true));
    act(() => void vi.advanceTimersByTime(2500));
    expect(fn).toHaveBeenCalledTimes(1);

    setVisibility(false, true);
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(fn).toHaveBeenCalledTimes(2); // catch-up refresh
    act(() => void vi.advanceTimersByTime(1100));
    expect(fn).toHaveBeenCalledTimes(3); // and the interval resumes
  });

  it("does nothing when disabled, arms when enabled flips true", () => {
    setVisibility(false, true);
    const fn = vi.fn();
    const { rerender } = renderHook(({ en }) => usePolling(fn, 1000, en), {
      initialProps: { en: false },
    });
    act(() => void vi.advanceTimersByTime(3000));
    expect(fn).not.toHaveBeenCalled();

    rerender({ en: true });
    expect(fn).toHaveBeenCalledTimes(1);
    act(() => void vi.advanceTimersByTime(1100));
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("pollPaused only pauses for hidden+unfocused", () => {
    setVisibility(false, true);
    expect(pollPaused()).toBe(false);
    setVisibility(true, true); // automation / occluded
    expect(pollPaused()).toBe(false);
    setVisibility(true, false); // backgrounded
    expect(pollPaused()).toBe(true);
  });
});
