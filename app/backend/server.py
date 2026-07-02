"""
server.py – FastAPI chat backend for Ask the PLC.

Endpoints
---------
POST /api/session                       create a session (L5X + optional snapshot); returns id + summary
WS   /api/chat/{session_id}             streaming chat; client sends {message, audience}
GET  /api/dossier/{session_id}          project summary + aoi_instances + health stats
GET  /api/routine/{session_id}/{program}/{routine}   direct routine read for the UI
GET  /api/trace/{session_id}/{tag}?snapshot=NAME     interlock trace, optionally live-evaluated
GET  /api/rung/{session_id}/{program}/{routine}/{number}?snapshot=NAME
                                        nested rung parse structure (+ values) for the ladder renderer

Run:
    ./.venv/bin/python -m uvicorn app.backend.server:app --port 8000
Mock mode (no API key needed):
    ASKPLC_MOCK=1 ./.venv/bin/python -m uvicorn app.backend.server:app --port 8000
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Dict, Optional

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except Exception:  # pragma: no cover
    pass

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .plc_tools import (
    PLCToolbox,
    StaticSnapshotProvider,
    DEFAULT_L5X,
    SNAPSHOT_DIR,
)
from .chat import run_chat
from .rung_json import rung_payload

app = FastAPI(title="Ask the PLC", version="0.2.0")

# Allow the Vite dev server (and any local origin) to hit the REST API directly.
# WebSocket chat and the dev proxy don't need this, but it keeps a standalone
# `vite dev` origin working when the proxy is bypassed.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# session_id -> {"toolbox", "l5x", "snapshot"}
_SESSIONS: Dict[str, Dict] = {}
# (l5x, snapshot) -> PLCToolbox  (parse cache)
_TOOLBOX_CACHE: Dict[tuple, PLCToolbox] = {}


def _snapshot_path(name: Optional[str]) -> Optional[Path]:
    if not name:
        return None
    p = Path(name)
    if p.exists():
        return p
    for cand in (SNAPSHOT_DIR / name, SNAPSHOT_DIR / f"{name}.json"):
        if cand.exists():
            return cand
    return None


def _get_toolbox(l5x: str, snapshot: Optional[str]) -> PLCToolbox:
    key = (l5x, snapshot or "")
    if key not in _TOOLBOX_CACHE:
        prov = None
        sp = _snapshot_path(snapshot)
        if sp is not None:
            prov = StaticSnapshotProvider(sp)
        _TOOLBOX_CACHE[key] = PLCToolbox(l5x, live_provider=prov)
    return _TOOLBOX_CACHE[key]


def _session(session_id: str) -> Dict:
    s = _SESSIONS.get(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"session '{session_id}' not found")
    return s


# ──────────────────────────────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────────────────────────────

class SessionRequest(BaseModel):
    l5x: Optional[str] = None
    snapshot: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────
# REST endpoints
# ──────────────────────────────────────────────────────────────────────

@app.post("/api/session")
def create_session(req: SessionRequest):
    l5x = req.l5x or str(DEFAULT_L5X)
    if not Path(l5x).exists():
        raise HTTPException(status_code=400, detail=f"L5X file not found: {l5x}")
    toolbox = _get_toolbox(l5x, req.snapshot)
    session_id = uuid.uuid4().hex[:12]
    _SESSIONS[session_id] = {"toolbox": toolbox, "l5x": l5x, "snapshot": req.snapshot}
    return {
        "session_id": session_id,
        "l5x": l5x,
        "snapshot": req.snapshot,
        "mock": os.environ.get("ASKPLC_MOCK") == "1",
        "summary": toolbox.get_project_summary(),
    }


@app.get("/api/dossier/{session_id}")
def get_dossier(session_id: str):
    tb: PLCToolbox = _session(session_id)["toolbox"]
    summary = tb.get_project_summary()
    return {
        "session_id": session_id,
        "controller": summary["controller"],
        "counts": summary["counts"],
        "documentation": summary["documentation"],
        "aoi_instances": summary["aoi_instances"],
        "programs": summary["programs"],
        "modules": summary["modules"],
        "aois": summary["aois"],
    }


@app.get("/api/routine/{session_id}/{program}/{routine}")
def get_routine(session_id: str, program: str, routine: str):
    tb: PLCToolbox = _session(session_id)["toolbox"]
    result = tb.get_routine(program, routine)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/tags/{session_id}")
def search_tags(session_id: str, q: str = "", limit: int = 20):
    """Small read-only tag search for the frontend trace-input autocomplete."""
    tb: PLCToolbox = _session(session_id)["toolbox"]
    return tb.search_tags(q, limit=limit)


@app.get("/api/rung/{session_id}/{program}/{routine}/{number}")
def get_rung_render(session_id: str, program: str, routine: str, number: int,
                    snapshot: Optional[str] = None):
    """Full nested parse structure of one rung for the ladder renderer,
    plus (when a snapshot is given or attached to the session) a values map
    for every tag operand in the rung."""
    sess = _session(session_id)
    tb: PLCToolbox = sess["toolbox"]
    values = None
    snap = snapshot or sess.get("snapshot")
    if snap:
        sp = _snapshot_path(snap)
        if sp is None:
            raise HTTPException(status_code=404, detail=f"snapshot '{snap}' not found")
        values = StaticSnapshotProvider(sp).get_values()
    result = rung_payload(tb, program, routine, number, snapshot_values=values)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/trace/{session_id}/{tag}")
def get_trace(session_id: str, tag: str, snapshot: Optional[str] = None):
    sess = _session(session_id)
    tb: PLCToolbox = sess["toolbox"]
    live_values = None
    snap = snapshot or sess.get("snapshot")
    if snap:
        sp = _snapshot_path(snap)
        if sp is not None:
            live_values = StaticSnapshotProvider(sp).get_values()
    return tb.trace_blockers(tag, live_values=live_values)


# ──────────────────────────────────────────────────────────────────────
# WebSocket chat
# ──────────────────────────────────────────────────────────────────────

@app.websocket("/api/chat/{session_id}")
async def chat_ws(websocket: WebSocket, session_id: str):
    await websocket.accept()
    sess = _SESSIONS.get(session_id)
    if sess is None:
        await websocket.send_json({"type": "error", "message": f"session '{session_id}' not found"})
        await websocket.close()
        return
    toolbox: PLCToolbox = sess["toolbox"]
    try:
        while True:
            payload = await websocket.receive_json()
            message = payload.get("message", "")
            audience = payload.get("audience", "maintenance")
            if not message:
                await websocket.send_json({"type": "error", "message": "empty message"})
                continue
            try:
                async for frame in run_chat(toolbox, message, audience):
                    await websocket.send_json(frame)
            except Exception as e:  # pragma: no cover - surfaces model/tool errors
                await websocket.send_json({"type": "error", "message": str(e)})
    except WebSocketDisconnect:
        return
