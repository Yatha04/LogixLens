# LogixLens — Ask the PLC (frontend)

Dark, industrial-modern React UI for the "Ask the PLC" demo: a Machine Dossier,
a deep-linkable Routine view with the **signature SVG ladder renderer + live
power flow**, an interlock Trace view (collapsible AND/OR condition tree with a
root-cause banner), and a streaming Chat panel.

Stack: React 18 · Vite 6 · TypeScript · Tailwind v4 · Vitest.

## Prerequisites

- Node 22 (`nvm use 22`)
- The FastAPI backend from this repo, runnable in **mock mode** (no API key):

```bash
# from repo root
cd /path/to/LogixLens
ASKPLC_MOCK=1 ./l5x-copilot/.venv/bin/python -m uvicorn app.backend.server:app --port 8000
# regenerate the demo L5X if build/PressLine_3.L5X is missing:
cd l5x-copilot && ./.venv/bin/python ../demo_cell/generate_l5x.py
```

## Dev mode (backend + frontend together)

Two terminals:

```bash
# terminal 1 — backend (mock mode, port 8000)
cd /path/to/LogixLens
ASKPLC_MOCK=1 ./l5x-copilot/.venv/bin/python -m uvicorn app.backend.server:app --port 8000

# terminal 2 — frontend (Vite dev server, port 5173)
cd app/frontend
npm install          # first time only
npm run dev          # http://localhost:5173
```

Vite proxies `/api/*` (REST **and** the chat WebSocket) to `http://127.0.0.1:8000`,
so the frontend talks to the backend with no CORS config in dev. (The backend
also enables permissive CORS for `localhost`/`127.0.0.1` origins for a
proxy-less setup.)

One-liner (background backend + foreground dev server):

```bash
cd /path/to/LogixLens && \
  (ASKPLC_MOCK=1 ./l5x-copilot/.venv/bin/python -m uvicorn app.backend.server:app --port 8000 &) && \
  cd app/frontend && npm run dev
```

## Build

```bash
npm run build        # tsc -b (typecheck) + vite build -> dist/
npm run preview      # serve the production build
```

## Tests

```bash
npm test             # unit + component (jsdom): energization logic + <Ladder/> smoke
npm run test:integration   # hits a LIVE backend on :8000 (start it first)
```

- `src/lib/powerflow.test.ts` — the pure energization engine (series, branch OR,
  nested branches, XIO semantics, comparisons, unknown propagation, and the
  `R30_PressCycle` rung 9 acceptance case: **blocked** under `guard_door_open`,
  **conducting** under `healthy`).
- `src/components/Ladder.test.tsx` — renders the SVG and asserts the rung state.
- `src/lib/api.integration.test.ts` — creates a real session and asserts the API
  client parses dossier / routine / rung / trace and streams chat frames.
  Point at a different backend with `ASKPLC_API=http://host:port`.

## Layout

- **Top bar** — controller name/processor, snapshot selector
  (healthy / guard_door_open / no snapshot — switching creates a fresh
  session), audience toggle (Operator / Maintenance / Controls Eng, sent with
  every chat message), mock/live chip, and the chat-socket connection dot.
- **Left sidebar** — controller organizer (programs → routines) + Machine Anatomy
  (components inferred from AOI instances).
- **Center** — one of: Machine Dossier · Routine view (ladder) · Trace view
  (interlock tree with tag-autocomplete trace input backed by `/api/tags`).
- **Right** — collapsible Chat panel: streaming markdown answers, tool
  breadcrumb chips, clickable citation chips that deep-link the ladder view.

## The ladder renderer

`src/components/Ladder.tsx` is a pure component: `(elements, values?, tags?) -> SVG`.
Left/right rails, `─┤ ├─` / `─┤/├─` contacts, `─( )─` / `(L)` / `(U)` coils,
recursive parallel branches, and labeled instruction boxes for timers / counters
/ moves / compares / AOIs. Tag name above each element, its description
(from the `/api/rung` `tags` map) truncated below, live value shown next to
the tag. Energization is delegated to the tested `src/lib/powerflow.ts`
(`energizeChain` / `energizeRung`): conducting wires are bright green
(animated), dead/unknown wire is grey, and the output coil glows when power
reaches it. The **first** blocking element on an otherwise-hot path (per
branch leg) renders red with a pulse; contacts that are closed but sit on a
dead path render dim green.

**Symbols vs boxes:**

- Symbols: `XIC`, `XIO`, `OTE`, `OTL`, `OTU`; one-shots (`ONS`/`OSR`/`OSF`)
  as a compact labelled block on the wire.
- Boxes: timers/counters (`TON/TOF/RTO/CTU/CTD/RES`), move/math
  (`MOV/COP/CPS/BTD/ADD/SUB/MUL/DIV/CPT/CLR/MOD`), comparisons
  (`EQU/NEQ/GRT/GEQ/LES/LEQ/LIM/MEQ` — these gate power), program flow
  (`JSR/JMP/LBL/...`), and AOI calls (`FB_VALVE(...)` etc.). Box operand rows
  append live values as `= v`.

**Limitations (honest):**

- RLL only — ST routines render as numbered code, SFC as step/transition
  lists (matches the parser's coverage).
- Only `XIC`/`XIO`/comparisons gate power; any other condition-shaped
  instruction is treated as pass-through. Timer/counter done bits energize
  via their snapshot values (e.g. `T_InfeedJam.DN`), not by simulating the
  timer; presets authored as `?` in the demo L5X display as `?`.
- Indirect addresses (`data[index]`) are looked up verbatim in the values
  map; unresolved ones render as unknown (grey), never guessed.
