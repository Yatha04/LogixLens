"""
Entry point for the PressLine_3 live simulator.

    ./l5x-copilot/.venv/bin/python -m app.simulator --port 4840 --http-port 8090

Starts, in one asyncio process:
  * the cell state machine (fixed tick, default 10 Hz),
  * an OPC UA server exposing every published tag, and
  * an aiohttp chaos/status API.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging

from aiohttp import web

from .cell import Cell
from .http_api import make_app
from .opcua_server import CellOpcUaServer


async def _run(args) -> None:
    cell = Cell(args.spec)
    endpoint = f"opc.tcp://0.0.0.0:{args.port}/pressline3/"
    opc = CellOpcUaServer(cell, endpoint)
    await opc.start()

    app = make_app(cell)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", args.http_port)
    await site.start()

    print(f"[simulator] OPC UA  : {endpoint}", flush=True)
    print(f"[simulator] chaos API: http://0.0.0.0:{args.http_port} "
          f"(/state, /values, /chaos, /chaos/clear)", flush=True)
    print(f"[simulator] tick     : {args.tick_hz} Hz", flush=True)

    dt = 1.0 / args.tick_hz
    try:
        while True:
            cell.tick(dt)
            await opc.update()
            await asyncio.sleep(dt)
    finally:
        await opc.stop()
        await runner.cleanup()


def main() -> None:
    ap = argparse.ArgumentParser(description="PressLine_3 live cell simulator")
    ap.add_argument("--port", type=int, default=4840, help="OPC UA server port")
    ap.add_argument("--http-port", type=int, default=8090, help="chaos API port")
    ap.add_argument("--spec", default=None, help="path to pressline3.yaml")
    ap.add_argument("--tick-hz", type=float, default=10.0, help="state-machine tick rate")
    ap.add_argument("--log", default="WARNING", help="log level")
    args = ap.parse_args()

    logging.basicConfig(level=getattr(logging, args.log.upper(), logging.WARNING))

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run(args))


if __name__ == "__main__":
    main()
