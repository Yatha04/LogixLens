"""PressLine_3 live cell simulator (Stage 4 of "Ask the PLC").

Run as a process:
    ./l5x-copilot/.venv/bin/python -m app.simulator --port 4840 --http-port 8090
"""

from .cell import Cell, CHAOS_FAULTS, ALL_TAGS, NAMESPACE_URI, ROOT_FOLDER

__all__ = ["Cell", "CHAOS_FAULTS", "ALL_TAGS", "NAMESPACE_URI", "ROOT_FOLDER"]
