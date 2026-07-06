"""
server.py – FastAPI chat backend for Ask the PLC.

Endpoints
---------
POST /api/session                       create a session (L5X + optional snapshot, or {live:true}); returns id + summary
WS   /api/chat/{session_id}             streaming chat; client sends {message, audience}
GET  /api/dossier/{session_id}          project summary + aoi_instances + health stats
GET  /api/routine/{session_id}/{program}/{routine}   direct routine read for the UI
GET  /api/trace/{session_id}/{tag}?snapshot=NAME     interlock trace, optionally live-evaluated
GET  /api/rung/{session_id}/{program}/{routine}/{number}?snapshot=NAME
                                        nested rung parse structure (+ values) for the ladder renderer
GET  /api/live/{session_id}/status      proxy the simulator /state (machine state + key values)
POST /api/live/{session_id}/chaos       proxy the simulator /chaos {"fault": NAME}
POST /api/live/{session_id}/chaos/clear proxy the simulator /chaos/clear (clear + reset handshake)
POST /api/autodoc/{session_id}          propose descriptions for undocumented tags (optional {tags:[...]} scope)
GET  /api/autodoc/{session_id}/export.csv   CSV of the reviewed autodoc table (tag, current, proposed, confidence)

Run:
    ./.venv/bin/python -m uvicorn app.backend.server:app --port 8000
Mock mode (no API key needed):
    ASKPLC_MOCK=1 ./.venv/bin/python -m uvicorn app.backend.server:app --port 8000
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except Exception:  # pragma: no cover
    pass

from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Response,
    UploadFile, File,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .plc_tools import (
    PLCToolbox,
    StaticSnapshotProvider,
    OpcUaProvider,
    DEFAULT_L5X,
    SNAPSHOT_DIR,
)
from .chat import run_chat
from .rung_json import rung_payload
from .autodoc import generate_autodoc, to_csv, is_mock as autodoc_is_mock

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

# session_id -> {"toolbox", "l5x", "snapshot", "live", "provider", "sim_http"}
_SESSIONS: Dict[str, Dict] = {}
# (l5x, snapshot) -> PLCToolbox  (parse cache; static/snapshot sessions only)
_TOOLBOX_CACHE: Dict[tuple, PLCToolbox] = {}
# session_id -> {tag_name: proposal_row}  (accumulates across /api/autodoc calls)
_AUTODOC_STATE: Dict[str, Dict[str, Dict]] = {}

# Uploaded L5X files land here (gitignored), content-addressed so re-uploads
# of the same file reuse the same path and hit the toolbox parse cache.
UPLOAD_DIR = Path(
    os.environ.get("ASKPLC_UPLOAD_DIR")
    or Path(__file__).resolve().parents[2] / "uploads"
)
MAX_UPLOAD_BYTES = 64 * 1024 * 1024

# Defaults for a locally-run PressLine_3 simulator (OPC UA :4840, chaos :8090).
# Overridable via env for non-standard deployments / parallel test stacks.
DEFAULT_OPCUA_URL = os.environ.get(
    "ASKPLC_OPCUA_URL", "opc.tcp://127.0.0.1:4840/pressline3/")
DEFAULT_SIM_HTTP_URL = os.environ.get("ASKPLC_SIM_HTTP_URL") or None
_DEFAULT_SIM_HTTP_PORT = 8090


def _derive_sim_http(opcua_url: str, override: Optional[str]) -> str:
    """Chaos/status HTTP base for the sim. Explicit override wins; otherwise
    the env default, otherwise the OPC UA host + the sim's default HTTP port."""
    if override:
        return override.rstrip("/")
    if DEFAULT_SIM_HTTP_URL:
        return DEFAULT_SIM_HTTP_URL.rstrip("/")
    host = urlparse(opcua_url).hostname or "127.0.0.1"
    return f"http://{host}:{_DEFAULT_SIM_HTTP_PORT}"


def _close_live_providers() -> None:
    """Close every open OPC UA provider (one live session at a time — a new
    live session replaces the old one, per the demo's single-cell model)."""
    for sess in _SESSIONS.values():
        prov = sess.get("provider")
        if prov is not None:
            try:
                prov.close()
            except Exception:  # pragma: no cover - best-effort teardown
                pass
            sess["provider"] = None


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
    # Live mode: back the session with an OPC UA connection to the running
    # PressLine_3 simulator instead of a static snapshot.
    live: bool = False
    opcua_url: Optional[str] = None
    sim_http_url: Optional[str] = None


class ChaosRequest(BaseModel):
    fault: str


class AutodocRequest(BaseModel):
    tags: Optional[List[str]] = None


# ──────────────────────────────────────────────────────────────────────
# REST endpoints
# ──────────────────────────────────────────────────────────────────────

@app.post("/api/session")
def create_session(req: SessionRequest):
    l5x = req.l5x or str(DEFAULT_L5X)
    if not Path(l5x).exists():
        raise HTTPException(status_code=400, detail=f"L5X file not found: {l5x}")

    session_id = uuid.uuid4().hex[:12]

    if req.live:
        # One live cell at a time: retire any previous OPC UA connection first.
        _close_live_providers()
        opcua_url = req.opcua_url or DEFAULT_OPCUA_URL
        provider = OpcUaProvider(opcua_url)
        if not provider.available():
            note = provider.note or "connection failed"
            provider.close()
            raise HTTPException(
                status_code=503,
                detail=f"OPC UA simulator unreachable at {opcua_url}: {note}. "
                       f"Start it with `make sim`.",
            )
        toolbox = PLCToolbox(l5x, live_provider=provider)
        sim_http = _derive_sim_http(opcua_url, req.sim_http_url)
        _SESSIONS[session_id] = {
            "toolbox": toolbox, "l5x": l5x, "snapshot": None,
            "live": True, "provider": provider,
            "opcua_url": opcua_url, "sim_http": sim_http,
        }
        return {
            "session_id": session_id,
            "l5x": l5x,
            "snapshot": None,
            "live": True,
            "opcua_url": opcua_url,
            "mock": os.environ.get("ASKPLC_MOCK") == "1",
            "summary": toolbox.get_project_summary(),
        }

    toolbox = _get_toolbox(l5x, req.snapshot)
    _SESSIONS[session_id] = {
        "toolbox": toolbox, "l5x": l5x, "snapshot": req.snapshot,
        "live": False, "provider": None,
    }
    return {
        "session_id": session_id,
        "l5x": l5x,
        "snapshot": req.snapshot,
        "live": False,
        "mock": os.environ.get("ASKPLC_MOCK") == "1",
        "summary": toolbox.get_project_summary(),
    }


@app.post("/api/upload")
async def upload_l5x(file: UploadFile = File(...)):
    """Upload an L5X export and get a ready session for it.

    The file is content-addressed into UPLOAD_DIR, parsed immediately (a file
    the parser rejects is deleted and reported as a 400 with the parse error),
    and a static session is created — same response shape as /api/session.
    """
    name = Path(file.filename or "upload.L5X").name
    if not name.lower().endswith((".l5x", ".xml")):
        raise HTTPException(
            status_code=400,
            detail=f"'{name}' is not an .L5X export (expected .L5X or .xml)")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")
    if not data.strip():
        raise HTTPException(status_code=400, detail="File is empty")

    digest = hashlib.sha256(data).hexdigest()[:16]
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / f"{digest}_{safe}"
    if not dest.exists():
        dest.write_bytes(data)

    try:
        toolbox = _get_toolbox(str(dest), None)
    except Exception as exc:
        _TOOLBOX_CACHE.pop((str(dest), ""), None)
        dest.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400, detail=f"Could not parse '{name}': {exc}")

    session_id = uuid.uuid4().hex[:12]
    _SESSIONS[session_id] = {
        "toolbox": toolbox, "l5x": str(dest), "snapshot": None,
        "live": False, "provider": None, "filename": name,
    }
    return {
        "session_id": session_id,
        "l5x": str(dest),
        "filename": name,
        "snapshot": None,
        "live": False,
        "uploaded": True,
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
    # An explicit ?snapshot= always wins; otherwise a live session reads fresh
    # values off its OPC UA provider, and a snapshot session uses its snapshot.
    snap = snapshot or sess.get("snapshot")
    if snap:
        sp = _snapshot_path(snap)
        if sp is None:
            raise HTTPException(status_code=404, detail=f"snapshot '{snap}' not found")
        values = StaticSnapshotProvider(sp).get_values()
    elif sess.get("live") and tb.live_provider is not None and tb.live_provider.available():
        values = tb.live_provider.get_values()
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
# Live cell — status + chaos proxy (one origin for the browser)
# ──────────────────────────────────────────────────────────────────────

def _live_session(session_id: str) -> Dict:
    sess = _session(session_id)
    if not sess.get("live") or not sess.get("sim_http"):
        raise HTTPException(status_code=400,
                            detail=f"session '{session_id}' is not a live session")
    return sess


async def _proxy_sim(sim_http: str, method: str, path: str, json_body=None) -> Dict:
    url = f"{sim_http}{path}"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.request(method, url, json=json_body)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"simulator chaos/status API unreachable at {sim_http}: {exc}",
        )
    if resp.status_code >= 400:
        # surface the sim's own error (e.g. unknown fault) as a 400
        try:
            detail = resp.json()
        except Exception:
            detail = {"error": resp.text}
        raise HTTPException(status_code=resp.status_code, detail=detail)
    return resp.json()


@app.get("/api/live/{session_id}/status")
async def live_status(session_id: str):
    """Proxy the simulator's /state (machine state, cycling, active fault,
    good/reject counts, key tag values) so the UI polls a single origin."""
    sess = _live_session(session_id)
    return await _proxy_sim(sess["sim_http"], "GET", "/state")


@app.post("/api/live/{session_id}/chaos")
async def live_chaos(session_id: str, req: ChaosRequest):
    """Inject a fault into the live cell (proxy to the simulator /chaos)."""
    sess = _live_session(session_id)
    return await _proxy_sim(sess["sim_http"], "POST", "/chaos", {"fault": req.fault})


@app.post("/api/live/{session_id}/chaos/clear")
async def live_chaos_clear(session_id: str):
    """Clear the active fault + run the reset handshake (proxy /chaos/clear)."""
    sess = _live_session(session_id)
    return await _proxy_sim(sess["sim_http"], "POST", "/chaos/clear")


@app.post("/api/autodoc/{session_id}")
async def post_autodoc(session_id: str, req: Optional[AutodocRequest] = None):
    """Propose descriptions for undocumented tags (Deliverable: auto-doc mode).

    Body ``{"tags": [...]}`` optionally scopes generation to a subset of
    undocumented tags (e.g. one batch page at a time); omitted/empty means
    "every undocumented tag". Proposals are merged into the session's
    reviewed table, retrievable via ``export.csv``.
    """
    sess = _session(session_id)
    tb: PLCToolbox = sess["toolbox"]
    tags = req.tags if req is not None else None
    proposals = await generate_autodoc(tb, tags=tags)
    store = _AUTODOC_STATE.setdefault(session_id, {})
    for p in proposals:
        store[p["tag"]] = p
    return {
        "session_id": session_id,
        "mode": "mock" if autodoc_is_mock() else "real",
        "total": len(proposals),
        "proposals": proposals,
    }


@app.get("/api/autodoc/{session_id}/export.csv")
def get_autodoc_csv(session_id: str):
    """CSV of the reviewed autodoc table so far (tag, current, proposed, confidence)."""
    _session(session_id)  # 404s if the session doesn't exist
    rows = list(_AUTODOC_STATE.get(session_id, {}).values())
    return Response(
        content=to_csv(rows),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="autodoc_{session_id}.csv"'},
    )


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
