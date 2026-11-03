"""T38: a reader capped at a sensitivity level learns nothing from records above it: not through
a looser cap asked for over MCP, not through near-duplicate tag names, not through counts."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from emlek.core import search, service, versions
from emlek.core.db import Database
from emlek.core.errors import EmlekError
from emlek.core.permissions import Caller, Channel
from emlek.mcp_server import server

PERSON = Caller(Channel.CLI, interactive=True, pin_verified=True)
READER = Caller(Channel.MCP_READONLY)


@pytest.mark.parametrize(
    ("asked", "expected"),
    [(None, "medium"), ("high", "medium"), ("medium", "medium"), ("none", "none")],
)
def test_the_ai_can_ask_for_a_stricter_cap_but_never_a_looser_one(
    asked: Any, expected: str
) -> None:
    assert server._lower_cap(asked, "medium") == expected


def test_an_unknown_level_still_reaches_the_search_and_is_rejected(db: Database) -> None:
    with pytest.raises(EmlekError):
        search.search(db, READER, query="x", max_sensitivity=server._lower_cap("secret", "medium"))


def test_read_only_mcp_cannot_lift_its_own_cap(data_dir: Path, db: Database) -> None:
    service.save(db, PERSON, body="普通 共通語")
    secret = service.save(db, PERSON, body="秘密のメモ 共通語")["ref"]
    service.set_sensitivity(db, PERSON, ref=secret, level="high")
    db.close()

    async def scenario() -> None:
        from mcp import Client, StdioServerParameters

        args = ["-m", "emlek", "--data-dir", str(data_dir), "mcp", "--read-only"]
        async with Client(StdioServerParameters(command=sys.executable, args=args)) as client:
            for asked in ("high", "medium"):
                reply = await client.call_tool(
                    "search", {"query": "共通語", "max_sensitivity": asked}
                )
                block: Any = reply.content[0]
                text: str = block.text
                assert "秘密のメモ" not in text
                found = json.loads(text[text.index("{") :])["result"]
                assert found["total"] == 1 and found["withheld"] == 1

    asyncio.run(scenario())


def test_similar_tag_names_never_come_from_hidden_or_capped_records(db: Database) -> None:
    hidden = service.save(db, PERSON, body="a 共通語", tags=["隠旅行計画"])["ref"]
    secret = service.save(db, PERSON, body="b 共通語", tags=["秘旅行計画"])["ref"]
    service.save(db, PERSON, body="c 共通語", tags=["公旅行計画"])
    versions.hide(db, PERSON, ref=hidden)
    service.set_sensitivity(db, PERSON, ref=secret, level="high")
    answer = search.search(
        db, READER, query="なにもない言葉", tags=["旅行計画"], max_sensitivity="medium"
    )
    shown = json.dumps(answer, ensure_ascii=False)
    assert "隠旅" not in shown and "秘旅" not in shown
    plain = search.search(db, READER, query="旅行計画", max_sensitivity="medium")
    assert "隠旅" not in json.dumps(plain, ensure_ascii=False)
    assert "秘旅" not in json.dumps(plain, ensure_ascii=False)


def test_counts_leave_out_records_above_the_cap(db: Database) -> None:
    service.save(db, PERSON, body="共通語 公開", tags=["旅"], event_time="2026-01-01")
    loud = service.save(db, PERSON, body="共通語 秘密")["ref"]
    service.set_sensitivity(db, PERSON, ref=loud, level="high")
    capped = search.search(
        db, READER, query="共通語", tags=["旅"], date_from="2026-01-01", max_sensitivity="medium"
    )
    assert capped["total"] == 1 and capped["undated"] == 0
    assert capped["tag_coverage"] == {"tagged": 1, "untagged": 0}
    when = "2026-01-01"
    medium = search.search(db, READER, query="共通語", date_from=when, max_sensitivity="medium")
    high = search.search(db, PERSON, query="共通語", date_from=when, max_sensitivity="high")
    assert medium["undated"] == 0 and high["undated"] == 1
