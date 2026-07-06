"""Tests for chat provider resolution and the subscription (Agent SDK) glue."""

import asyncio
import json

import pytest

from app.backend import chat
from app.backend.chat import resolve_provider, is_mock
from app.backend.tools_schema import TOOL_SCHEMAS


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("ASKPLC_MOCK", "ASKPLC_PROVIDER", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_mock_env_wins_over_everything(monkeypatch):
    monkeypatch.setenv("ASKPLC_MOCK", "1")
    monkeypatch.setenv("ASKPLC_PROVIDER", "subscription")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    assert resolve_provider() == "mock"
    assert is_mock() is True


def test_explicit_provider(monkeypatch):
    monkeypatch.setenv("ASKPLC_PROVIDER", "subscription")
    assert resolve_provider() == "subscription"
    monkeypatch.setenv("ASKPLC_PROVIDER", "api")
    assert resolve_provider() == "api"
    monkeypatch.setenv("ASKPLC_PROVIDER", "mock")
    assert resolve_provider() == "mock"


def test_api_key_beats_cli_autodetect(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.setattr(chat.shutil, "which", lambda _: "/usr/local/bin/claude")
    assert resolve_provider() == "api"


def test_cli_autodetect_means_subscription(monkeypatch):
    monkeypatch.setattr(chat.shutil, "which", lambda _: "/usr/local/bin/claude")
    assert resolve_provider() == "subscription"
    assert is_mock() is False


def test_no_key_no_cli_means_mock(monkeypatch):
    monkeypatch.setattr(chat.shutil, "which", lambda _: None)
    assert resolve_provider() == "mock"


def test_sdk_tools_wrap_every_schema_and_dispatch(toolbox):
    """The SDK wrappers must cover all 11 tools and actually dispatch —
    harvesting citations and queueing summary frames like the API loop."""
    cites, seen = [], set()
    q: asyncio.Queue = asyncio.Queue()
    tools = chat._sdk_tools(toolbox, cites, seen, q)
    assert [t.name for t in tools] == [s["name"] for s in TOOL_SCHEMAS]

    trace = next(t for t in tools if t.name == "trace_blockers")
    out = asyncio.run(trace.handler({"target": "Press_Cycle_Start"}))
    payload = json.loads(out["content"][0]["text"])
    assert payload.get("target") == "Press_Cycle_Start"
    assert cites, "citations must be harvested at dispatch time"
    assert not q.empty(), "a tool_result_summary frame must be queued"
    frame = q.get_nowait()
    assert frame["type"] == "tool_result_summary"
    assert frame["tool"] == "trace_blockers"


def test_autodoc_follows_provider_resolution(monkeypatch):
    from app.backend import autodoc
    monkeypatch.setattr(chat.shutil, "which", lambda _: "/usr/local/bin/claude")
    assert autodoc.is_mock() is False  # subscription => real proposals
    monkeypatch.setenv("ASKPLC_MOCK", "1")
    assert autodoc.is_mock() is True


def test_autodoc_parse_batch_text_handles_fences_and_junk():
    from app.backend.autodoc import _parse_batch_text
    good = '```json\n[{"tag":"T1","proposed_description":"guard door switch","confidence":"high"}]\n```'
    out = _parse_batch_text(good)
    assert out["T1"]["confidence"] == "high"
    assert _parse_batch_text("not json at all") == {}
    assert _parse_batch_text('{"tag": "not-a-list"}') == {}


def test_autodoc_dispatches_to_subscription_batch(toolbox, monkeypatch):
    from app.backend import autodoc

    async def fake_subscription(tb, batch, model):
        return {t.name: {"tag": t.name, "proposed_description": "via sdk",
                         "confidence": "medium"} for t in batch}

    async def boom(tb, batch, model):  # the API path must NOT be hit
        raise AssertionError("api path used in subscription mode")

    monkeypatch.setenv("ASKPLC_PROVIDER", "subscription")
    monkeypatch.setattr(autodoc, "_propose_batch_subscription", fake_subscription)
    monkeypatch.setattr(autodoc, "_propose_batch_real", boom)

    rows = asyncio.run(autodoc.generate_autodoc(toolbox))
    assert rows and all(r["proposed_description"] == "via sdk" for r in rows)
    assert all(r["confidence"] == "medium" for r in rows)


def test_run_chat_legacy_mock_arg_still_forces_mock(toolbox):
    async def collect():
        frames = []
        async for f in chat.run_chat(toolbox, "why is the press not cycling?",
                                     mock=True):
            frames.append(f)
        return frames

    frames = asyncio.run(collect())
    kinds = [f["type"] for f in frames]
    assert "done" in kinds and "tool_call" in kinds
    done = next(f for f in frames if f["type"] == "done")
    assert done["text"].startswith("[mock]")
