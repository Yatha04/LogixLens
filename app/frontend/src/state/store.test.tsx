import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { AppProvider, useApp, LIVE_SOURCE } from "./store";

vi.mock("../lib/api", () => ({
  createSession: vi.fn(),
  getDossier: vi.fn(),
}));

import { createSession, getDossier } from "../lib/api";

const sessionFor = (over: Record<string, unknown>) => ({
  session_id: "sess-" + Math.random().toString(36).slice(2, 8),
  l5x: "PressLine_3.L5X",
  snapshot: null,
  mock: true,
  summary: {},
  ...over,
});

const wrapper = ({ children }: { children: ReactNode }) => <AppProvider>{children}</AppProvider>;

describe("store live-mode source switching", () => {
  beforeEach(() => {
    vi.mocked(createSession).mockReset();
    vi.mocked(getDossier).mockReset();
    // default boot ("guard_door_open") + any switch resolve to a snapshot session
    vi.mocked(createSession).mockImplementation(async (opts: any) =>
      sessionFor({ live: !!opts?.live, snapshot: opts?.snapshot ?? null }) as any
    );
    vi.mocked(getDossier).mockResolvedValue({} as any);
  });

  it("boots into a static snapshot session (not live)", async () => {
    const { result } = renderHook(() => useApp(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.live).toBe(false);
    expect(result.current.snapshot).toBe("guard_door_open");
    expect(result.current.sourceId).toBe("guard_door_open");
    expect(createSession).toHaveBeenCalledWith({ snapshot: "guard_door_open" });
  });

  it("switches to the live OPC UA source", async () => {
    const { result } = renderHook(() => useApp(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      result.current.switchSource(LIVE_SOURCE);
    });

    await waitFor(() => expect(result.current.live).toBe(true));
    expect(result.current.snapshot).toBeNull();
    expect(result.current.sourceId).toBe(LIVE_SOURCE);
    expect(createSession).toHaveBeenCalledWith({ live: true });
  });

  it("switches back from live to a snapshot", async () => {
    const { result } = renderHook(() => useApp(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => result.current.switchSource(LIVE_SOURCE));
    await waitFor(() => expect(result.current.live).toBe(true));

    await act(async () => result.current.switchSource("healthy"));
    await waitFor(() => expect(result.current.live).toBe(false));
    expect(result.current.snapshot).toBe("healthy");
    expect(createSession).toHaveBeenLastCalledWith({ snapshot: "healthy" });
  });

  it("surfaces a 503 (sim down) as an error, staying not-live", async () => {
    const { result } = renderHook(() => useApp(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    vi.mocked(createSession).mockRejectedValueOnce(
      new Error("/api/session -> 503: OPC UA simulator unreachable")
    );
    await act(async () => result.current.switchSource(LIVE_SOURCE));

    await waitFor(() => expect(result.current.error).toMatch(/unreachable/i));
    expect(result.current.live).toBe(false);
  });
});
