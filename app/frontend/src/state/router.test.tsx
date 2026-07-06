/**
 * router.test.tsx — hash routing + upload flow.
 *
 * The view is mirrored into location.hash (deep links, back/forward);
 * upload() swaps the whole app to the uploaded file's session.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { AppProvider, useApp, viewToHash, hashToView } from "./store";

vi.mock("../lib/api", () => ({
  createSession: vi.fn(),
  getDossier: vi.fn(),
  uploadL5x: vi.fn(),
}));

import { createSession, getDossier, uploadL5x } from "../lib/api";

const session = (over: Record<string, unknown> = {}) => ({
  session_id: "sess-" + Math.random().toString(36).slice(2, 8),
  l5x: "PressLine_3.L5X",
  snapshot: null,
  mock: true,
  summary: {},
  ...over,
});

const wrapper = ({ children }: { children: ReactNode }) => <AppProvider>{children}</AppProvider>;

beforeEach(() => {
  window.location.hash = "";
  vi.mocked(createSession).mockReset().mockImplementation(async () => session() as any);
  vi.mocked(getDossier).mockReset().mockResolvedValue({ controller: { name: "PressLine_3" } } as any);
  vi.mocked(uploadL5x).mockReset();
});

describe("hash <-> view mapping", () => {
  it("round-trips every view kind", () => {
    const views = [
      { kind: "dossier" },
      { kind: "routine", program: "P300_Press", routine: "R30_PressCycle" },
      { kind: "routine", program: "P300_Press", routine: "R30_PressCycle", highlightRung: 9 },
      { kind: "trace", tag: "Press_Cycle_Start" },
      { kind: "autodoc" },
    ] as const;
    for (const v of views) {
      expect(hashToView(viewToHash(v as any))).toEqual(v);
    }
  });

  it("handles names needing URI encoding", () => {
    const v = { kind: "routine", program: "Prog With Space", routine: "R/1" } as const;
    expect(hashToView(viewToHash(v as any))).toEqual(v);
  });

  it("falls back to dossier on junk hashes", () => {
    for (const h of ["", "#", "#/", "#/bogus", "#/routine/only-one-part", "#/trace"]) {
      expect(hashToView(h)).toEqual({ kind: "dossier" });
    }
  });
});

describe("navigation mirrors into the URL", () => {
  it("openRoutine sets view synchronously and pushes the hash", async () => {
    const { result } = renderHook(() => useApp(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => result.current.openRoutine("P300_Press", "R30_PressCycle", 9));
    expect(result.current.view).toEqual({
      kind: "routine", program: "P300_Press", routine: "R30_PressCycle", highlightRung: 9,
    });
    expect(window.location.hash).toBe("#/routine/P300_Press/R30_PressCycle/r9");
  });

  it("a hashchange (back/forward) drives the view", async () => {
    const { result } = renderHook(() => useApp(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      window.location.hash = "#/trace/Safety_OK";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    await waitFor(() =>
      expect(result.current.view).toEqual({ kind: "trace", tag: "Safety_OK" })
    );
  });

  it("initial view comes from the hash (deep link)", async () => {
    window.location.hash = "#/autodoc";
    const { result } = renderHook(() => useApp(), { wrapper });
    expect(result.current.view).toEqual({ kind: "autodoc" });
  });
});

describe("upload flow", () => {
  it("switches the app to the uploaded file's session", async () => {
    const { result } = renderHook(() => useApp(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    vi.mocked(uploadL5x).mockResolvedValue(
      session({ uploaded: true, filename: "Pumps.L5X", l5x: "/uploads/x_Pumps.L5X" }) as any
    );
    vi.mocked(getDossier).mockResolvedValue({ controller: { name: "NWGG_Treater_Dayton" } } as any);

    await act(() => result.current.upload(new File(["<x/>"], "Pumps.L5X")));

    expect(result.current.session?.uploaded).toBe(true);
    expect(result.current.session?.filename).toBe("Pumps.L5X");
    expect(result.current.live).toBe(false);
    expect(result.current.snapshot).toBe(null);
    expect(result.current.view).toEqual({ kind: "dossier" });
    expect(result.current.uploadError).toBe(null);
  });

  it("a bad file sets uploadError and keeps the current session", async () => {
    const { result } = renderHook(() => useApp(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    const before = result.current.session?.session_id;

    vi.mocked(uploadL5x).mockRejectedValue(new Error("Could not parse 'broken.L5X'"));
    await act(() => result.current.upload(new File(["junk"], "broken.L5X")));

    expect(result.current.uploadError).toContain("broken.L5X");
    expect(result.current.session?.session_id).toBe(before);
    act(() => result.current.clearUploadError());
    expect(result.current.uploadError).toBe(null);
  });

  it("source switching keeps an uploaded file loaded", async () => {
    const { result } = renderHook(() => useApp(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    vi.mocked(uploadL5x).mockResolvedValue(
      session({ uploaded: true, filename: "Pumps.L5X", l5x: "/uploads/x_Pumps.L5X" }) as any
    );
    await act(() => result.current.upload(new File(["<x/>"], "Pumps.L5X")));

    vi.mocked(createSession).mockClear();
    act(() => result.current.switchSource(""));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(vi.mocked(createSession)).toHaveBeenCalledWith(
      expect.objectContaining({ l5x: "/uploads/x_Pumps.L5X" })
    );
  });
});
