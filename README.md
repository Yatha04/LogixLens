# LogixLens — Ask the PLC

**A debugger for the factory floor.**

Drop a Rockwell `.L5X` export on it, and it reads the program the way an engineer would:
what the machine is, what drives each output, and — when the machine is down — the
exact interlock that's blocking it, with the rung on screen and citations back to the
program that never let a claim go un-sourced. The diagnosis is a deterministic
backward-chaining static analysis over the parsed ladder logic; the LLM only narrates
what that analysis already proved. Every fact in every answer traces back to a
`program/routine/rung` citation you can click open.

---

## Contents

- [Architecture](#architecture)
- [Quickstart](#quickstart)
- [The money shot](#the-money-shot-why-is-the-machine-down)
- [Validated against 260 real-world programs](#validated-against-260-real-world-programs)
- [Test matrix](#test-matrix)
- [No API key? Use your Claude subscription](#no-api-key-use-your-claude-subscription)
- [MCP — point any agent at it](#mcp--point-any-agent-at-it)
- [Auto-doc mode](#auto-doc-mode-the-leave-behind)
- [Honest limitations](#honest-limitations)
- [Repo layout](#repo-layout)

---

## Architecture

```
                     ┌─────────────────────────────────────────────┐
 .L5X upload ──────► │  LogixLens core (l5x-copilot/src)            │
                     │  parser + cross-reference + condition-tree   │
                     │  diagnosis engine (trace_blockers)           │
                     └──────────────────┬──────────────────────────┘
                                        │ ParsedProject (in-proc)
                     ┌──────────────────▼──────────────────────────┐
                     │  PLCToolbox (app/backend/plc_tools.py)       │
                     │  11 tools: get_project_summary, search_tags, │
                     │  get_tag, get_routine, get_rung, find_writers│
                     │  find_readers, trace_blockers, get_aoi,      │
                     │  explain_context_pack, get_live_values       │
                     └───────┬──────────────────────┬──────────────┘
                             │                      │
              ┌──────────────▼───────┐   ┌──────────▼─────────────┐
              │ FastAPI chat backend  │   │ PLC-MCP stdio server   │
              │ (chat.py tool loop,   │   │ (mcp_server.py — any   │
              │  Claude or mock model)│   │  MCP client, e.g.      │
              │ REST + WebSocket      │   │  Claude Desktop)       │
              └──────────────┬───────┘   └─────────────────────────┘
                             │ WebSocket (streaming) + REST
              ┌──────────────▼──────────────────────────────────┐
              │ React frontend (app/frontend)                    │
              │ Dossier │ Chat │ Interlock tree │ Ladder SVG      │
              │ renderer w/ live power flow │ Auto-Doc            │
              └──────────────▲──────────────────────────────────┘
                             │ OPC UA (asyncua client, PLCToolbox.OpcUaProvider)
              ┌──────────────┴──────────────────────────────────┐
              │ SIMULATED CELL — "PressLine_3" (app/simulator)   │
              │ asyncio state machine + OPC UA server +          │
              │ fault-injection HTTP API (/chaos)                │
              └─────────────────────────────────────────────────┘
```

The parser (`l5x-copilot/`) and the diagnosis engine (`l5x-copilot/src/analysis`) are
pure Python, tested independently of everything above them. `PLCToolbox` is the only
thing every consumer — chat loop, MCP server, REST endpoints, auto-doc — calls into;
the tools it exposes never hallucinate because they're direct reads of the parsed
model, not model output.

## Quickstart

Requires Python 3.11+ and Node 22. Everything Python-side shares one venv at
`l5x-copilot/.venv` (the parser is never installed as a package — it's put on
`sys.path` directly by every entry point).

```bash
git clone https://github.com/Yatha04/LogixLens.git && cd LogixLens
make setup                 # venv + parser/backend/simulator deps + npm install
make demo-l5x               # generate demo_cell/build/PressLine_3.L5X from its YAML spec
```

Three terminals — simulator, backend, frontend:

```bash
make sim                    # OPC UA :4840, chaos/status HTTP :8090
make backend                # FastAPI :8000, mock mode by default (no API key needed)
make frontend                # Vite dev server :5173 (proxies /api to :8000)
```

Open `http://localhost:5173` — then **drag any Rockwell `.L5X` export onto the
window** (or use *Open .L5X* in the top bar) to load your own program: dossier,
ladder rendering, cross-reference, interlock tracing, and auto-doc all work on
uploaded files, statically. Every view is URL-addressable
(`#/routine/<program>/<routine>/r<rung>`), so you can deep-link a colleague to a rung.

To use the real Claude model instead of the deterministic
mock, copy `.env.example` to `.env`, set `ANTHROPIC_API_KEY`, and run
`make backend ASKPLC_MOCK=0`.

Run the live end-to-end gate (spins the simulator up itself, no manual steps):

```bash
make gate4
```

## The money shot: "why is the machine down?"

The backend answers this over REST + WebSocket; here it is with nothing but `curl` and
a session pinned to the `guard_door_open` fault scenario (the same fixture the gate4
live smoke test uses, generated by injecting the fault and snapshotting the resulting
tag values):

```bash
# 1) create a session against the faulted scenario
SID=$(curl -s -X POST localhost:8000/api/session \
  -H 'Content-Type: application/json' -d '{"snapshot":"guard_door_open"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['session_id'])")

# 2) ask why Press_Cycle_Start won't go true
curl -s "localhost:8000/api/trace/$SID/Press_Cycle_Start" | python3 -m json.tool
```

The response's `failing_paths` is the answer, already minimal — one red leaf, not the
whole 20-rung tree that got checked along the way:

```json
{
  "root_satisfied": false,
  "failing_paths": [{
    "chain": ["Safety_OK", "GuardDoor_Closed"],
    "leaf_tag": "GuardDoor_Closed",
    "leaf_annotation": "field input 'GuardDoor_Closed' — no logic writers found; likely a physical input, check the device"
  }]
}
```

The chat loop narrates the same trace in one sentence, and the citations frame it
streams back is scoped to exactly the failing chain — not every rung the backward
trace happened to visit while confirming everything else was fine:

```
> "why is the machine down?"
[mock] Press_Cycle_Start is blocked. Failing chain: Safety_OK -> GuardDoor_Closed.
The blocking condition is GuardDoor_Closed (P900_Safety / R92_SafetyOK rung 1).
Note: field input 'GuardDoor_Closed' — no logic writers found; likely a physical
input, check the device.

citations: [P300_Press/R30_PressCycle:9, P900_Safety/R92_SafetyOK:1]
```

In the UI this renders as the ladder rung with live power flow — green up to the open
`GuardDoor_Closed` contact, grey/dead past it.

## Validated against 260 real-world programs

"Works on our demo file" is not the same claim as "works on yours," so the parser and
diagnosis engine are validated against a corpus of **260 real L5X files** fetched from
public GitHub repositories — 17 full controller projects (a working grain elevator,
FRC robot code, industrial function-block libraries), plus AOI, UDT, and routine
exports, spanning firmware v20 through v37. Current results:

- **100% pass rate** on every pipeline stage: load, full parse, rung parsing, diagnosis
- **2,758 / 2,761 real ladder rungs parse** (99.89% — the 3 misses are
  deliberately-invalid strings from someone's parser-test file, recorded as
  degradations rather than crashes)
- Diagnosis (`build_condition_tree`) runs clean on written tags of **all 17** full
  controller projects

The corpus is a permanent regression gate: `l5x-copilot/tests/test_corpus.py`
parametrizes over every file, so any parser change that breaks a single real-world
program fails the suite. The L5X files themselves are never redistributed (gitignored);
`corpus/manifest.json` records the exact provenance of each, and the fetch scripts
rebuild the corpus reproducibly. See `corpus/README.md`.

## Test matrix

| Suite | Command | Result |
|---|---|---|
| Parser + corpus gate (`l5x-copilot/src`) | `make test-parser` | **432 passed**, 11 skipped |
| Backend (`app/backend`) | `make test-backend` | **68 passed** |
| Simulator (`app/simulator`) | `make test-simulator` | **23 passed** |
| Frontend unit (`app/frontend`) | `npm test -- --run` | **57 passed** |
| Frontend integration (live backend) | `npm run test:integration` | **8 passed** |
| Gold Q&A eval, real model (Claude subscription, no API key) | `python -m app.backend.eval.run_eval_cli` | **13/13 PASS** |
| Real-corpus Q&A eval — 3 real machines | `run_eval_cli --questions .../corpus_questions.yaml` | **11/11 PASS** |
| Gate 1 — static diagnosis regression | `make gate1` | PASS |
| Gate 4 — live OPC UA end-to-end | `make gate4` | PASS |

`make test` runs parser + backend + simulator + frontend unit in one shot; `make gates`
runs both gate scripts (gate4 starts and tears down its own simulator subprocess, so it
needs no other services running).

## No API key? Use your Claude subscription

The web chat's tool loop calls the Anthropic API (pay-per-token). If you have a
Claude Pro/Max subscription instead, you get the same brain for free by flipping the
architecture around: run LogixLens as an **MCP server** and let Claude Code or Claude
Desktop be the chat window. Claude then calls the exact same 11 `PLCToolbox` tools —
parse, cross-reference, `trace_blockers`, live values — and your subscription pays for
the reasoning.

With Claude Code (from the repo root):

```bash
claude mcp add logixlens -- ./l5x-copilot/.venv/bin/python -m app.backend.mcp_server \
  --l5x demo_cell/build/PressLine_3.L5X --snapshot guard_door_open
```

then just ask, in a `claude` session: *"why is the machine down?"* — point `--l5x` at
any L5X export to interrogate your own program.

With Claude Desktop, add the same command to `claude_desktop_config.json` (use
absolute paths):

```json
{
  "mcpServers": {
    "logixlens": {
      "command": "/abs/path/LogixLens/l5x-copilot/.venv/bin/python",
      "args": ["-m", "app.backend.mcp_server", "--l5x", "/abs/path/Your.L5X"],
      "cwd": "/abs/path/LogixLens"
    }
  }
}
```

Everything else — the web UI's dossier, interlock tree, ladder power-flow renderer,
and the deterministic `/api/trace` diagnosis — needs no model at all and runs fully
offline (`ASKPLC_MOCK=1`, the default).

## MCP — point any agent at it

`app/backend/mcp_server.py` is a thin FastMCP stdio adapter over the same
`PLCToolbox` the chat backend uses — 11 tools, zero duplicated logic:

```bash
./l5x-copilot/.venv/bin/python -m app.backend.mcp_server --snapshot guard_door_open
```

Point any MCP client at it (Claude Desktop, another agent framework, your own script)
by adding it as a stdio server with that command. Verify it end-to-end without a GUI
client:

```bash
./l5x-copilot/.venv/bin/python -m app.backend.mcp_smoketest
```

This is the same tool surface the web chat uses — the diagnosis engine is
infrastructure, not a feature bolted onto one UI.

## Auto-doc mode (the leave-behind)

Tag documentation is billable-hours drudgery for integrators; the real automotive
donor file this demo cell is modeled after ships at ~46% doc coverage. Auto-doc turns
every undocumented tag into a reviewable, cited proposal:

```bash
curl -s -X POST "localhost:8000/api/autodoc/$SID" -H 'Content-Type: application/json' -d '{}'
curl -s "localhost:8000/api/autodoc/$SID/export.csv"
```

Real mode batches ~30 tags per Anthropic API call, each tag carrying its data type,
scope, and cited rung snippets from where it's read/written (reused straight from
`PLCToolbox.get_tag` / `get_rung` — no separate analysis path). Mock mode
(`ASKPLC_MOCK=1`) derives a deterministic proposal from the tag name
(CamelCase/underscore split) plus the first usage instruction, always
`confidence: "low"` — same pipeline end to end, no network call. In the UI it's
reachable from the Dossier's **Doc Coverage** stat card: a table of undocumented tags,
a **Generate** button that fills in proposed descriptions with confidence badges, and
**Export CSV**.

## Honest limitations

- **RLL-only tracing.** The condition-tree builder walks parsed ladder logic. ST lines
  are captured verbatim but not AST-parsed — a `trace_blockers` leaf that bottoms out
  in an ST routine is flagged, not silently guessed at.
- **ST/FBD detection is string-level.** The parser records ST program text; it doesn't
  build an expression tree for it, so ST-side writers show up as a flagged citation,
  not a traced condition.
- **Indirect addressing is unresolvable statically** (`array[index]`, computed tag
  references) — the engine flags these explicitly rather than guessing a value.
- **Rockwell/Allen-Bradley only.** The parser is built against the L5X schema; Siemens,
  Beckhoff, and CODESYS are unexplored surface, not "almost done."
- **The demo cell is synthetic.** `PressLine_3` is a schema-plausible generated file
  (real customer L5X files are proprietary and can't ship). The parser and diagnosis
  engine, however, are validated against 260 real public programs — see the corpus
  section above.
- **The answer-quality eval is evidence-based, not exhaustive.** Both eval sets
  (13 gold questions on the demo cell, 11 troubleshooting questions on three real
  corpus machines — a grain-treater pump skid, a water-treatment plant, an ALD
  vacuum tool) assert grounded evidence: the right tool called, the true writer
  routine named, fabricated tags refused. All pass on the real model, but 24
  questions is a scoreboard, not a guarantee.
- **"Isn't this just RSLogix cross-reference?"** RSLogix needs a license, a laptop at
  the panel, and someone who reads ladder. This needs a browser and a sentence — and an
  MCP endpoint any agent (not just a human at a keyboard) can query.

## Repo layout

```
l5x-copilot/            The parser + diagnosis engine (pure Python, zero app deps)
  src/parser/            L5X loader, tag/module/routine/UDT/AOI extractors,
                          rung parser, member-level cross-reference
  src/analysis/           condition_tree.py — build_condition_tree / evaluate_tree /
                          failing_paths (the backward-chaining diagnosis core)
  tests/                  432 tests: unit suites against the generated PressLine_3.L5X
                          + the 260-file real-world corpus regression gate

corpus/                  Real-world validation corpus (fetch scripts, harness,
                          manifest with per-file provenance; L5X files gitignored)

demo_cell/               PressLine_3 — the demo program + simulator's shared source
  pressline3.yaml         single source of truth: stations, devices, interlocks, logic
  generate_l5x.py         YAML -> build/PressLine_3.L5X (gitignored; regenerate it)
  verify_scenario.py      asserts the money-shot interlock chain survives regeneration
  gate1_diagnosis_smoke.py  static-analysis regression gate

app/backend/            FastAPI chat backend + MCP server + eval harness
  plc_tools.py            PLCToolbox — the 11 tools, live-value providers
  server.py                REST + WebSocket endpoints
  chat.py                   the streaming Claude tool-use loop (+ deterministic mock)
  prompts.py                 system prompt / audience registers
  autodoc.py                  auto-documentation proposal pipeline
  mcp_server.py                 FastMCP stdio adapter over PLCToolbox
  eval/                          gold Q&A harness (run_eval.py, gold_questions.yaml)
  tests/                          57 tests (mock mode; no API key needed)

app/simulator/           PressLine_3 live cell: asyncio state machine + OPC UA + chaos API
  cell.py                  the state machine (consumes pressline3.yaml)
  opcua_server.py            OPC UA variable server
  http_api.py                  /state /values /chaos /chaos/clear /health
  gate4_live_smoke.py            live end-to-end regression gate (starts its own sim)
  tests/                          23 tests

app/frontend/             React 18 + Vite + TypeScript + Tailwind v4 UI
  src/components/          DossierView, RoutineView, TraceView (InterlockTree),
                            Ladder (the SVG power-flow renderer), AutoDocView, ChatPanel
  src/lib/                   api.ts (typed client), powerflow.ts (energization engine)
  README.md                   frontend-specific dev/test instructions
```
