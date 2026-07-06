/**
 * Backend integration test — exercises the REAL FastAPI backend over HTTP and
 * asserts the frontend API client parses every response shape it depends on.
 *
 * Requires the backend running in mock mode on :8000:
 *   cd /Users/.../LogixLens && ASKPLC_MOCK=1 \
 *     ./l5x-copilot/.venv/bin/python -m uvicorn app.backend.server:app --port 8000
 *
 * Run:  npm run test:integration
 */
import { describe, it, expect, beforeAll } from "vitest";
import {
  setApiBase,
  createSession,
  getDossier,
  getRoutine,
  getRung,
  getTrace,
} from "./api";
import { energizeRung } from "./powerflow";

const BASE = process.env.ASKPLC_API ?? "http://127.0.0.1:8000";

beforeAll(async () => {
  setApiBase(BASE);
  // Fail fast with a helpful message if the backend isn't up.
  try {
    await fetch(`${BASE}/openapi.json`);
  } catch {
    throw new Error(
      `Backend not reachable at ${BASE}. Start it with ASKPLC_MOCK=1 uvicorn app.backend.server:app --port 8000`
    );
  }
});

describe("backend integration (mock mode)", () => {
  it("creates a session and parses the summary", async () => {
    const s = await createSession({ snapshot: "guard_door_open" });
    expect(s.session_id).toBeTruthy();
    expect(s.mock).toBe(true);
    expect(s.summary.controller.name).toBe("PressLine_3");
    expect(Object.keys(s.summary.aoi_instances)).toContain("FB_VALVE");
  });

  it("fetches and parses the dossier", async () => {
    const { session_id } = await createSession();
    const d = await getDossier(session_id);
    expect(d.counts.tags).toBeGreaterThan(0);
    expect(d.documentation.coverage_pct).toBeGreaterThan(0);
    expect(d.programs.length).toBeGreaterThan(0);
    expect(d.programs[0].routines.length).toBeGreaterThan(0);
  });

  it("fetches and parses a routine's rungs", async () => {
    const { session_id } = await createSession();
    const r = await getRoutine(session_id, "P300_Press", "R30_PressCycle");
    expect(r.type).toBe("RLL");
    expect(r.rungs && r.rungs.length).toBeGreaterThan(9);
    expect(r.rungs![9].text).toContain("OTE(Press_Cycle_Start)");
  });

  it("fetches rung 9 with values and energizes it correctly per snapshot", async () => {
    const { session_id } = await createSession();
    const blocked = await getRung(session_id, "P300_Press", "R30_PressCycle", 9, "guard_door_open");
    expect(blocked.elements.length).toBeGreaterThan(0);
    expect(blocked.values).toBeDefined();
    expect(blocked.values!["Safety_OK"]).toBe(false);
    expect(energizeRung(blocked.elements, blocked.values).state).toBe("blocked");

    const healthy = await getRung(session_id, "P300_Press", "R30_PressCycle", 9, "healthy");
    expect(healthy.values!["Safety_OK"]).toBe(true);
    expect(energizeRung(healthy.elements, healthy.values).state).toBe("conducting");
  });

  it("fetches and parses a live-evaluated trace with a failing path", async () => {
    const { session_id } = await createSession({ snapshot: "guard_door_open" });
    const t = await getTrace(session_id, "Press_Cycle_Start");
    expect(t.root_satisfied).toBe(false);
    expect(t.failing_paths && t.failing_paths.length).toBeGreaterThan(0);
    expect(t.failing_paths![0].chain).toEqual(["Safety_OK", "GuardDoor_Closed"]);
    expect(t.tree.kind).toBeDefined();
  });

  it("returns a nested Branch for the master 3-wire seal-in rung", async () => {
    // MainProgram/R02_CycleControl rung 0:
    // [XIC(Master_Start_PB),XIC(System_Running)]XIC(Master_Stop_PB)XIC(Safety_OK)OTE(System_Running)
    const { session_id } = await createSession();
    const rung = await getRung(session_id, "MainProgram", "R02_CycleControl", 0, "healthy");
    const branch = rung.elements[0];
    expect(branch.type).toBe("branch");
    if (branch.type !== "branch") throw new Error("expected branch");
    expect(branch.legs).toHaveLength(2);
    const legTags = branch.legs.map((leg) => {
      const el = leg[0];
      return el.type === "instruction" ? el.operands[0]?.value : undefined;
    });
    expect(legTags).toEqual(["Master_Start_PB", "System_Running"]);
    // Master_Stop_PB is an NC panel input: healthy means the contact reads
    // TRUE (button not pressed), and the snapshot says so explicitly. With
    // System_Running sealed in, the whole rung conducts. Master_Start_PB is
    // deliberately absent — unknown OR true must resolve true (unknowns are
    // absorbed, never guessed).
    expect(rung.values).toBeDefined();
    expect(rung.values!["Master_Stop_PB"]).toBe(true);
    expect(rung.values!["Master_Start_PB"]).toBeUndefined();
    expect(energizeRung(rung.elements, rung.values).state).toBe("conducting");
    // tag descriptions ride along for the renderer's sub-labels
    expect(Object.keys(rung.tags)).toContain("System_Running");
  });

  it("tag search backs the trace-input autocomplete", async () => {
    const { session_id } = await createSession();
    const res = await fetch(`${BASE}/api/tags/${session_id}?q=guarddoor&limit=5`);
    expect(res.ok).toBe(true);
    const body = (await res.json()) as { total: number; tags: { name: string }[] };
    expect(body.tags.some((t) => t.name === "GuardDoor_Closed")).toBe(true);
  });

  it("streams a diagnosis over the chat WebSocket (frames -> done)", async () => {
    const { session_id } = await createSession({ snapshot: "guard_door_open" });
    const wsUrl = `${BASE.replace(/^http/, "ws")}/api/chat/${session_id}`;
    const frames: Record<string, unknown>[] = [];

    await new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(wsUrl);
      const timeout = setTimeout(() => {
        ws.close();
        reject(new Error("chat WS timed out"));
      }, 15_000);
      ws.onopen = () =>
        ws.send(JSON.stringify({ message: "why is the press not cycling?", audience: "maintenance" }));
      ws.onerror = (e) => {
        clearTimeout(timeout);
        reject(new Error(`chat WS error: ${String(e)}`));
      };
      ws.onmessage = (ev) => {
        const frame = JSON.parse(String(ev.data));
        frames.push(frame);
        if (frame.type === "done" || frame.type === "error") {
          clearTimeout(timeout);
          ws.close();
          resolve();
        }
      };
    });

    const types = frames.map((f) => f.type);
    expect(types).toContain("tool_call");
    expect(types).toContain("tool_result_summary");
    expect(types).toContain("text_delta");
    expect(types[types.length - 1]).toBe("done");
    const text = frames
      .filter((f) => f.type === "text_delta")
      .map((f) => f.text)
      .join("");
    expect(text).toContain("GuardDoor_Closed");
    const cites = frames.find((f) => f.type === "citations") as
      | { citations: { routine: string }[] }
      | undefined;
    expect(cites && cites.citations.some((c) => c.routine === "R92_SafetyOK")).toBe(true);
  });
});
