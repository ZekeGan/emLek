"""Prompt delivery contracts and recovery of writes that already committed."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from emlek.core import auto, notice, service
from emlek.core.db import Database
from emlek.core.errors import EmlekError
from emlek.core.permissions import Caller, Channel
from emlek.mcp_server.rules import WRITE_CORE, document, prompt_for
from emlek.mcp_server.server import (
    RULES_VERSION,
    _instructions,
    _reply_hints,
    _slim_write,
    build_server,
)

AI = Caller(Channel.MCP)
PERSON = Caller(Channel.CLI, interactive=True, pin_verified=True)


def test_write_success_does_not_expose_internal_sensitivity_labels(db: Database) -> None:
    notice.acknowledge(db.conn)
    saved = service.save(db, AI, body="合成朋友的電話是 0912-345-678。")
    assert saved["sensitivity"] == "medium"
    shown = _slim_write(saved)
    assert shown["revision_ref"] and shown["marker"]
    assert "sensitivity" not in shown and "sensitivity_hint" not in shown


def test_terms_carry_only_the_text_to_show(db: Database) -> None:
    with pytest.raises(EmlekError) as raised:
        notice.start(db, AI)
    data = raised.value.data
    assert data["ask_user"] == notice.TERMS
    assert "on_decline" not in data  # W07: models paraphrased it into the terms reply


def test_search_closing_hints_only_where_answers_drift() -> None:
    empty = _reply_hints({"total": 0, "hints": ["沒有找到。"]}, read_only=False)
    assert empty["hints"][0] == "沒有找到。" and "不邀請保存" in empty["hints"][-1]
    stale = {"total": 1, "returned_count": 1, "content_count": 0, "hints": []}
    withheld = _reply_hints(stale, read_only=True)
    assert "不建議重新寫入" in withheld["hints"][0] and "唯讀" in withheld["hints"][-1]
    found = {"total": 1, "returned_count": 1, "content_count": 1, "hints": []}
    assert _reply_hints(found, read_only=True) is found
    paged = {"total": 0, "next_cursor": "c", "hints": []}
    assert _reply_hints(paged, read_only=False) is paged


def payload(reply: Any) -> dict[str, Any]:
    text = "".join(getattr(block, "text", "") for block in reply.content)
    return json.loads(text[text.index("{") :])["result"]  # type: ignore[no-any-return]


def test_pending_tags_recover_without_another_note(data_dir: Path, db: Database) -> None:
    notice.acknowledge(db.conn)
    service.save(db, AI, body="既有城市", tags=["京都"])

    async def scenario() -> None:
        server = build_server(data_dir, read_only=False)
        saved = payload(await server.call_tool("save", {"body": "今天散步", "tags": ["京都市"]}))
        assert saved["tags_pending"]
        assert saved["tag_update_ref"] == "r2"
        assert "set_tags" in saved["tag_update_hint"]
        assert "allow_new" in saved["tag_update_hint"]
        pending = payload(
            await server.call_tool("set_tags", {"ref": saved["tag_update_ref"], "add": ["京都市"]})
        )
        assert pending["tags_pending"] and pending["tags"] == []
        assert "added" not in pending and "removed" not in pending
        repaired = payload(
            await server.call_tool("set_tags", {"ref": saved["tag_update_ref"], "add": ["京都"]})
        )
        assert repaired == {
            "ref": "r2",
            "added": ["京都"],
            "tags": [{"name": "京都", "type": "topic", "added_by": "ai"}],
        }

    asyncio.run(scenario())
    assert db.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 2
    assert db.conn.execute("SELECT count(*) FROM revisions").fetchone()[0] == 2


def test_start_reports_disabled_policy_without_enabling_it(db: Database) -> None:
    notice.acknowledge(db.conn)
    auto.set_enabled(db, PERSON, on=False)
    result = notice.start(db, AI)
    assert result["started"] is True and result["auto_enabled"] is False
    assert "關閉" in result["message"]
    assert not auto.enabled(db.conn)


def test_profiles_and_live_policy(data_dir: Path, db: Database) -> None:
    rules = (Path(__file__).resolve().parents[2] / "docs/AGENT_RULES.md").read_text(
        encoding="utf-8"
    )
    assert f"規則版本：`{RULES_VERSION}`" in rules
    assert rules == document()
    assert WRITE_CORE not in prompt_for(read_only=True)
    assert WRITE_CORE in prompt_for(read_only=False)
    readonly = _instructions(db.path, "medium", can_write=False)
    assert "唯讀" in readonly and "invalidated" in readonly and "查詢" in readonly
    assert "呼叫 start" not in readonly and "set_tags" not in readonly

    async def scenario() -> None:
        server = build_server(data_dir, read_only=False)
        notice.acknowledge(db.conn)
        auto.set_enabled(db, PERSON, on=False)
        policy = payload(await server.call_tool("auto_policy", {}))
        assert policy["started"] is True and policy["enabled"] is False
        assert policy["reference_time"] and policy["timezone"]
        tools = {t.name: t for t in await server.list_tools()}
        for name in ("save", "amend"):
            props = tools[name].input_schema["properties"]
            assert "逐字保留" in props["body"]["description"]
            assert not {"confirm_token", "notice_token"} & props.keys()
            schema = json.dumps(tools[name].input_schema)
            assert '"ref"' in schema and '"relation"' in schema
            assert "supersedes" in schema and "description" in schema
            if name == "save":
                assert props["kind"]["enum"] == list(service.KINDS)
            for spec in tools[name].input_schema["$defs"].values():
                assert spec["additionalProperties"] is False
        assert "invalidated" in (tools["get"].description or "")
        assert "by_year" in (tools["search"].description or "")

    asyncio.run(scenario())
