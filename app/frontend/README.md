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

- **Left sidebar** — controller organizer (programs → routines) + Machine Anatomy
  (components inferred from AOI instances).
- **Center** — one of: Machine Dossier · Routine view (ladder) · Trace view.
- **Right** — always-visible, collapsible Chat panel with an audience segmented
  control and a snapshot switcher (switching creates a fresh session).

## The ladder renderer

`src/components/Ladder.tsx` is a pure component: `(elements, values?) -> SVG`.
Left/right rails, `─┤ ├─` / `─┤/├─` contacts, `─( )─` / `(L)` / `(U)` coils,
recursive parallel branches, and labeled instruction boxes for timers / counters
/ moves / compares / AOIs. Energization is delegated to the tested
`src/lib/powerflow.ts` (`energizeChain` / `energizeRung`): conducting wires are
bright green (animated), the first blocking contact is red, dead/unknown wire is
grey, and the output coil glows when power reaches it.
