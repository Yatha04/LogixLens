/**
 * Regression test for the live-mode ladder refresh: after a fault is injected
 * in the running cell, the polled /api/rung values MUST flip the rendered rung
 * state (CONDUCTING -> BLOCKED) within one poll tick. Mocks getRung to return
 * healthy values first, then guard-door-open values on later calls.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { RoutineView } from "./RoutineView";
import { RUNG9_ELEMENTS, RUNG9_HEALTHY_VALUES, RUNG9_GUARD_VALUES } from "../lib/fixtures";
import type { RungPayload } from "../lib/types";

vi.mock("../state/store", () => ({
  useApp: () => ({ sid: "sess1", snapshot: null, live: true, openTrace: vi.fn() }),
}));

vi.mock("../lib/api", () => ({
  getRoutine: vi.fn(),
  getRung: vi.fn(),
}));

import { getRoutine, getRung } from "../lib/api";

const ROUTINE = {
  program: "P300_Press",
  routine: "R30_PressCycle",
  type: "RLL",
  description: "",
  rungs: [{ number: 9, text: "XIC(Safety_OK)OTE(Press_Cycle_Start);", comment: "" }],
  total_rungs: 1,
};

const rungWith = (values: Record<string, boolean>): RungPayload => ({
  program: "P300_Press",
  routine: "R30_PressCycle",
  number: 9,
  text: "XIC(Safety_OK)OTE(Press_Cycle_Start);",
  comment: "",
  elements: RUNG9_ELEMENTS,
  tags: {},
  values,
});

async function flush() {
  // let pending promise chains (fetch mocks) settle inside act
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("RoutineView live polling refresh", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(getRoutine).mockReset().mockResolvedValue(ROUTINE as never);
    vi.mocked(getRung).mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("flips the rung from CONDUCTING to BLOCKED when polled values change", async () => {
    // healthy on the first read(s), guard-door-open afterwards
    let faulted = false;
    vi.mocked(getRung).mockImplementation(async () =>
      rungWith(faulted ? (RUNG9_GUARD_VALUES as never) : (RUNG9_HEALTHY_VALUES as never))
    );

    render(<RoutineView view={{ program: "P300_Press", routine: "R30_PressCycle" }} />);
    await flush(); // routine + initial rung fetch
    await flush();

    expect(screen.getByText("CONDUCTING")).toBeInTheDocument();
    expect(screen.getByTestId("ladder").getAttribute("data-rung-state")).toBe("conducting");

    // fault injected in the cell; next poll tick must repaint the ladder
    faulted = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });
    await flush();

    expect(screen.getByText("BLOCKED")).toBeInTheDocument();
    expect(screen.getByTestId("ladder").getAttribute("data-rung-state")).toBe("blocked");
  });

  it("REGRESSION: still refreshes when the tab reports hidden but is focused (automation / occluded window)", async () => {
    // The exact browser state of the original bug: Chrome flags automated /
    // occluded tabs as document.hidden=true while they keep focus. The ladder
    // froze on its initial values because every poll tick was gated on hidden.
    vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    document.hasFocus = vi.fn(() => true);

    let faulted = false;
    vi.mocked(getRung).mockImplementation(async () =>
      rungWith(faulted ? (RUNG9_GUARD_VALUES as never) : (RUNG9_HEALTHY_VALUES as never))
    );

    render(<RoutineView view={{ program: "P300_Press", routine: "R30_PressCycle" }} />);
    await flush();
    await flush();
    expect(screen.getByTestId("ladder").getAttribute("data-rung-state")).toBe("conducting");

    faulted = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });
    await flush();
    expect(screen.getByTestId("ladder").getAttribute("data-rung-state")).toBe("blocked");
  });

  it("keeps polling on subsequent ticks (fault -> clear -> conducting again)", async () => {
    let phase: "healthy" | "guard" = "healthy";
    vi.mocked(getRung).mockImplementation(async () =>
      rungWith(phase === "guard" ? (RUNG9_GUARD_VALUES as never) : (RUNG9_HEALTHY_VALUES as never))
    );

    render(<RoutineView view={{ program: "P300_Press", routine: "R30_PressCycle" }} />);
    await flush();
    await flush();
    expect(screen.getByTestId("ladder").getAttribute("data-rung-state")).toBe("conducting");

    phase = "guard";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });
    await flush();
    expect(screen.getByTestId("ladder").getAttribute("data-rung-state")).toBe("blocked");

    phase = "healthy";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });
    await flush();
    expect(screen.getByTestId("ladder").getAttribute("data-rung-state")).toBe("conducting");
  });
});
