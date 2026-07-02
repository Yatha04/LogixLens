"""
http_api.py -- the chaos / status HTTP API for the live cell (aiohttp).

Endpoints (all JSON):
    GET  /state         -> machine state summary + key tag values
    GET  /values        -> the full published tag map (live dashboard feed)
    POST /chaos         -> body {"fault": NAME}; inject a fault, return /state
    POST /chaos/clear   -> clear the fault + run the reset handshake, return /state
    GET  /health        -> {"ok": true} (liveness)

Handlers run in the same asyncio loop as the tick loop, so they mutate the Cell
directly with no locking.
"""

from __future__ import annotations

from aiohttp import web

from .cell import CHAOS_FAULTS, Cell


def make_app(cell: Cell) -> web.Application:
    app = web.Application()

    async def state(_req):
        return web.json_response(cell.state_summary())

    async def values(_req):
        return web.json_response(cell.values())

    async def health(_req):
        return web.json_response({"ok": True})

    async def chaos(req):
        try:
            body = await req.json()
        except Exception:
            return web.json_response(
                {"error": "invalid JSON body", "faults": CHAOS_FAULTS}, status=400)
        fault = (body or {}).get("fault")
        if fault not in CHAOS_FAULTS:
            return web.json_response(
                {"error": f"unknown or missing fault {fault!r}",
                 "faults": CHAOS_FAULTS}, status=400)
        cell.inject(fault)
        return web.json_response(cell.state_summary())

    async def chaos_clear(_req):
        cell.clear_chaos()
        return web.json_response(cell.state_summary())

    app.router.add_get("/state", state)
    app.router.add_get("/values", values)
    app.router.add_get("/health", health)
    app.router.add_post("/chaos", chaos)
    app.router.add_post("/chaos/clear", chaos_clear)
    return app
