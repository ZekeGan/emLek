"""T40: what a model sees after a write is short: the reference, the marker, and anything that is
not a default. The core and the CLI keep their full results; only the MCP reply is trimmed."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from emlek.core import auto, notice
from emlek.core.db import Database
from emlek.core.permissions import Caller, Channel
from emlek.mcp_server.server import _slim_write, build_server

PERSON = Caller(Channel.CLI, interactive=True, pin_verified=True)


def _payload(reply: Any) -> dict[str, Any]:
    text = "".join(getattr(block, "text", "") for block in reply.content)
    found: dict[str, Any] = json.loads(text[text.index("{") :])["result"]
    return found


def test_the_trimmed_reply_keeps_only_what_is_not_a_default() -> None:
    full = {
        "record_id": 1,
        "ref": "r1",
        "version": 1,
        "revision_ref": "r1.v1",
        "created_at": "2026-11-03T00:00:00.000Z",
        "links_added": 0,
        "sensitivity": "none",
        "sensitivity_hint": {"level": "none", "categories": []},
        "tags": [],
        "tags_pending": [],
    }
    assert _slim_write(full) == {"revision_ref": "r1.v1"}
    loud = {
        **full,
        "sensitivity": "high",
        "sensitivity_hint": {"level": "high", "categories": ["x"]},
    }
    assert "sensitivity" not in _slim_write(loud) and "sensitivity_hint" not in _slim_write(loud)
    pending = {**full, "tags_pending": [{"name": "a", "similar": ["b"]}], "links_added": 2}
    shown = _slim_write(pending)
    assert shown["tags_pending"] and shown["links_added"] == 2


def test_save_and_amend_over_mcp_are_short_and_amend_shows_the_current_tags(
    data_dir: Path, db: Database
) -> None:
    auto.set_enabled(db, PERSON, on=True)
    auto.set_mode(db, PERSON, name="生活點滴", mode="auto")
    notice.acknowledge(db.conn)
    db.close()

    async def scenario() -> None:
        server = build_server(data_dir, read_only=False)
        saved = _payload(
            await server.call_tool(
                "save", {"body": "今天吃了拉麵", "source": "auto:生活點滴", "tags": ["拉麵"]}
            )
        )
        assert set(saved) == {"revision_ref", "marker", "tags"}
        assert saved["marker"] == "◆ emLek｜r1.✔️" and saved["tags"] == ["拉麵"]
        amended = _payload(
            await server.call_tool("amend", {"ref": "r1", "body": "今天吃了拉麵，在祇園"})
        )
        assert amended["revision_ref"] == "r1.v2" and amended["tags"] == ["拉麵"]  # still there
        assert "created_at" not in amended and "record_id" not in amended

    asyncio.run(scenario())


def test_the_event_time_format_is_explained_to_the_model(data_dir: Path) -> None:
    async def scenario() -> None:
        tools = {t.name: t for t in await build_server(data_dir, read_only=False).list_tools()}
        for name in ("save", "amend"):
            spec = tools[name].input_schema["properties"]["event_time"]
            assert "2026-11-03" in spec["description"] and "時區" in spec["description"]
            assert spec["type"] == "string" and "anyOf" not in spec

    asyncio.run(scenario())


def test_the_opening_text_counts_a_past_experience_as_something_to_save() -> None:
    from emlek.mcp_server.server import INSTRUCTIONS

    assert "含過去的事" in INSTRUCTIONS and "普通問答" in INSTRUCTIONS
    assert "內部分類不需轉述" in INSTRUCTIONS and "marker" in INSTRUCTIONS
    assert "呼叫工具前" in INSTRUCTIONS and "不要宣告操作" in INSTRUCTIONS
    assert "回想或自動存入時" in INSTRUCTIONS
    assert "最高風險" in INSTRUCTIONS and "不存也不問" in INSTRUCTIONS
