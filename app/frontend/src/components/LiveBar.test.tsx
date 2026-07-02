import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { LiveBar } from "./LiveBar";
import type { LiveStatus } from "../lib/types";

vi.mock("../state/store", async (orig) => {
  const actual = await orig<typeof import("../state/store")>();
  return { ...actual, useApp: () => ({ sid: "sess1", live: true }) };
});

vi.mock("../lib/api", () => ({
  getLiveStatus: vi.fn(),
  injectChaos: vi.fn(),
  clearChaos: vi.fn(),
}));

import { getLiveStatus, injectChaos, clearChaos } from "../lib/api";

const RUNNING: LiveStatus = {
  state: "RUNNING",
  cycling: true,
  active_fault: null,
  elapsed_s: 5,
  good_parts: 3,
  reject_parts: 1,
  press_step: 10,
  key_values: { Safety_OK: true, Hyd_Pressure: 1805 },
  faults: [],
};

const GUARD: LiveStatus = {
  ...RUNNING,
  state: "FAULTED",
  cycling: false,
  active_fault: "guard_door_open",
  key_values: { Safety_OK: false, GuardDoor_Closed: false, Hyd_Pressure: 1805 },
};

describe("<LiveBar /> smoke", () => {
  beforeEach(() => {
    vi.mocked(getLiveStatus).mockReset().mockResolvedValue(RUNNING);
    vi.mocked(injectChaos).mockReset().mockResolvedValue(GUARD);
    vi.mocked(clearChaos).mockReset().mockResolvedValue(RUNNING);
  });

  it("renders the status strip from polled /status", async () => {
    render(<LiveBar />);
    await waitFor(() => expect(screen.getByText("RUNNING")).toBeInTheDocument());
    expect(screen.getByText("cycling")).toBeInTheDocument();
    expect(screen.getByText(/fault: none/)).toBeInTheDocument();
    expect(getLiveStatus).toHaveBeenCalledWith("sess1");
  });

  it("injects a fault and reflects the returned status", async () => {
    render(<LiveBar />);
    await waitFor(() => expect(screen.getByText("RUNNING")).toBeInTheDocument());

    fireEvent.click(screen.getByTitle("Inject guard_door_open"));

    await waitFor(() => expect(screen.getByText("FAULTED")).toBeInTheDocument());
    expect(injectChaos).toHaveBeenCalledWith("sess1", "guard_door_open");
    expect(screen.getByText(/fault: guard_door_open/)).toBeInTheDocument();
  });

  it("clears the fault via Clear / Reset", async () => {
    vi.mocked(getLiveStatus).mockResolvedValue(GUARD);
    render(<LiveBar />);
    await waitFor(() => expect(screen.getByText("FAULTED")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Clear / Reset"));

    await waitFor(() => expect(clearChaos).toHaveBeenCalledWith("sess1"));
    await waitFor(() => expect(screen.getByText("RUNNING")).toBeInTheDocument());
  });
});
