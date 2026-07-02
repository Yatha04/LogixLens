/**
 * Regression test for live-mode interlock-tree refresh: the trace panel polls
 * /api/trace in live mode and must re-render when the evaluated tree changes
 * (healthy -> failing chain) — including when the tab reports hidden but is
 * focused (automation / occluded window), the state that froze polling.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import InterlockTree from "./InterlockTree";
import type { TracePayload } from "../lib/types";

vi.mock("../state/store", () => ({
  useApp: () => ({
    sid: "sess1",
    snapshot: null,
    live: true,
    openRoutine: vi.fn(),
    openTrace: vi.fn(),
  }),
}));

vi.mock("../lib/api", () => ({
  getTrace: vi.fn(),
  searchTags: vi.fn().mockResolvedValue({ total: 0, tags: [] }),
}));

import { getTrace } from "../lib/api";

const leaf = (tag: string, satisfied: boolean) => ({
  kind: "LEAF" as const,
  requirement: "needs_true" as const,
  tag,
  full_path: tag,
  cite: null,
  annotation: "",
  satisfied,
  children: [],
});

const HEALTHY: TracePayload = {
  target: "Press_Cycle_Start",
  tree: { ...leaf("Press_Cycle_Start", true), kind: "AND", children: [leaf("Safety_OK", true)] },
  root_satisfied: true,
  failing_paths: [],
  failing_count: 0,
};

const GUARD: TracePayload = {
  target: "Press_Cycle_Start",
  tree: { ...leaf("Press_Cycle_Start", false), kind: "AND", children: [leaf("Safety_OK", false)] },
  root_satisfied: false,
  failing_paths: [
    {
      chain: ["Safety_OK", "GuardDoor_Closed"],
      leaf_tag: "GuardDoor_Closed",
      leaf_annotation: "field input",
      nodes: [
        { tag: "Safety_OK", requirement: "needs_true", cite: null, annotation: "", satisfied: false },
        { tag: "GuardDoor_Closed", requirement: "needs_true", cite: null, annotation: "field input", satisfied: false },
      ],
    },
  ],
  failing_count: 1,
};

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("InterlockTree live polling refresh", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(getTrace).mockReset();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("re-evaluates the tree on poll ticks (healthy -> failing chain)", async () => {
    let faulted = false;
    vi.mocked(getTrace).mockImplementation(async () => (faulted ? GUARD : HEALTHY));

    render(<InterlockTree tag="Press_Cycle_Start" />);
    await flush();
    expect(screen.getByText(/satisfied under the current snapshot/)).toBeInTheDocument();

    faulted = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });
    await flush();

    expect(screen.getByText(/blocked — 1 failing path/)).toBeInTheDocument();
    expect(screen.getByText("GuardDoor_Closed")).toBeInTheDocument();
  });

  it("REGRESSION: still refreshes when the tab reports hidden but is focused", async () => {
    vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    document.hasFocus = vi.fn(() => true);

    let faulted = false;
    vi.mocked(getTrace).mockImplementation(async () => (faulted ? GUARD : HEALTHY));

    render(<InterlockTree tag="Press_Cycle_Start" />);
    await flush();
    expect(screen.getByText(/satisfied under the current snapshot/)).toBeInTheDocument();

    faulted = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1600);
    });
    await flush();
    expect(screen.getByText(/blocked — 1 failing path/)).toBeInTheDocument();
  });
});
