"""
opcua_server.py -- expose a :class:`~app.simulator.cell.Cell` over OPC UA.

Every published tag becomes a Variable node under a ``PressLine_3`` folder. The
NodeId uses a **string identifier equal to the tag name** in a dedicated
namespace (``urn:logixlens:pressline3``) -- so a client reads ``Safety_OK`` at
``ns=<idx>;s=Safety_OK``. Types are Boolean / Int32 / Float to match the L5X
tag data types.
"""

from __future__ import annotations

import logging
from typing import Dict

from asyncua import Server, ua

from .cell import (
    ALL_TAGS, NAMESPACE_URI, ROOT_FOLDER, Cell, tag_type,
)

logging.getLogger("asyncua").setLevel(logging.WARNING)

_VARIANT = {
    "bool": ua.VariantType.Boolean,
    "int": ua.VariantType.Int32,
    "float": ua.VariantType.Float,
}


def _coerce(name: str, value):
    t = tag_type(name)
    if t == "bool":
        return bool(value)
    if t == "int":
        return int(value)
    return float(value)


class CellOpcUaServer:
    """Wraps a Cell and mirrors its tag values onto OPC UA variable nodes."""

    def __init__(self, cell: Cell, endpoint: str):
        self.cell = cell
        self.endpoint = endpoint
        self.server = Server()
        self.idx = 0
        self._nodes: Dict[str, object] = {}

    async def start(self) -> None:
        await self.server.init()
        self.server.set_endpoint(self.endpoint)
        self.server.set_server_name("PressLine_3 Cell Simulator")
        self.idx = await self.server.register_namespace(NAMESPACE_URI)

        objects = self.server.nodes.objects
        folder = await objects.add_folder(
            ua.NodeId(ROOT_FOLDER, self.idx), ROOT_FOLDER)

        for name in ALL_TAGS:
            t = tag_type(name)
            val = _coerce(name, self.cell.get(name))
            node = await folder.add_variable(
                ua.NodeId(name, self.idx), name,
                ua.Variant(val, _VARIANT[t]),
            )
            self._nodes[name] = node
        await self.server.start()

    async def update(self) -> None:
        """Push the current cell values onto every node (called each tick)."""
        for name, node in self._nodes.items():
            t = tag_type(name)
            val = _coerce(name, self.cell.get(name))
            await node.write_value(ua.DataValue(ua.Variant(val, _VARIANT[t])))

    async def stop(self) -> None:
        try:
            await self.server.stop()
        except Exception:  # pragma: no cover - best-effort shutdown
            pass
