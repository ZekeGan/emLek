"""T10: paging gives the right total, no repeats, no gaps, and stable cursors."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from emlek.core import search, service
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller

Saver = Callable[..., dict[str, Any]]


@pytest.fixture
def filled(db: Database, save_at: Saver) -> Database:
    for i in range(57):
        day = f"2026-{1 + i % 12:02d}-{1 + i % 28:02d}"
        save_at(
            f"記録 {i} 共通のことば",
            created_at=f"2026-02-{1 + i % 27:02d}T{i % 24:02d}:00:00.000Z",
            event_time=day if i % 9 else None,
        )
    return db


def _walk(db: Database, caller: Caller, **kwargs: Any) -> tuple[list[str], int]:
    seen: list[str] = []
    cursor = None
    total = -1
    for _ in range(100):
        page = search.search(db, caller, cursor=cursor, limit=10, **kwargs)
        if total == -1:
            total = page["total"]
        assert page["total"] == total
        seen.extend(r["ref"] for r in page["results"])
        cursor = page["next_cursor"]
        if cursor is None:
            return seen, total
    raise AssertionError("cursor never ended")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"query": "共通のことば"},
        {"query": "共通のことば", "order": "event_time", "direction": "asc"},
        {"query": "共通のことば", "order": "event_time", "direction": "desc"},
        {"query": "共通のことば", "order": "created_at", "direction": "asc"},
        {"query": "共通のことば", "order": "created_at", "direction": "desc"},
        {"query": "記録"},
        {"order": "event_time"},
        {},
    ],
)
def test_pages_cover_everything_once(
    filled: Database, caller: Caller, kwargs: dict[str, Any]
) -> None:
    seen, total = _walk(filled, caller, **kwargs)
    assert total == 57 and len(seen) == 57 and len(set(seen)) == 57
    whole = search.search(filled, caller, limit=100, **kwargs)
    assert [r["ref"] for r in whole["results"]] == seen  # same order as one big page


def test_cursor_survives_new_records(filled: Database, caller: Caller, save_at: Saver) -> None:
    kwargs = {"query": "共通のことば", "order": "created_at", "direction": "asc"}
    first = search.search(filled, caller, limit=20, **kwargs)
    before = {r["ref"] for r in first["results"]}
    for i in range(5):
        save_at(f"途中で増えた 共通のことば {i}", created_at="2026-12-31T00:00:00.000Z")
    for i in range(3):
        save_at(f"古い日付で増えた 共通のことば {i}", created_at="2000-01-01T00:00:00.000Z")
    seen = set(before)
    cursor = first["next_cursor"]
    while cursor:
        page = search.search(filled, caller, limit=20, cursor=cursor, **kwargs)
        refs = [r["ref"] for r in page["results"]]
        assert not seen & set(refs)
        seen.update(refs)
        cursor = page["next_cursor"]
    original = {f"r{i}" for i in range(1, 58)}
    assert original <= seen  # nothing that existed when paging began is skipped


def test_cursor_validation(filled: Database, caller: Caller) -> None:
    query = "共通のことば"  # three or more characters, so the index ranks by relevance
    cursor = search.search(filled, caller, query=query, limit=5)["next_cursor"]
    assert cursor
    assert search.search(filled, caller, query=query, cursor=cursor)["results"]
    for kwargs in (
        {"cursor": "garbage"},
        {"cursor": cursor, "order": "created_at"},
        {"cursor": cursor, "order": "event_time", "direction": "asc"},
    ):
        with pytest.raises(EmlekError) as info:
            search.search(filled, caller, query=query, **kwargs)
        assert info.value.code is ErrorCode.INVALID_INPUT


def test_limit_bounds(db: Database, caller: Caller) -> None:
    for bad in (0, 101, -1):
        with pytest.raises(EmlekError):
            search.search(db, caller, limit=bad)
    assert search.search(db, caller, limit=100)["total"] == 0


def test_kinds_filter(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="共通語 原文", kind="original")
    service.save(db, caller, body="共通語 まとめ", kind="ai_summary")
    service.save(db, caller, body="共通語 推測", kind="inference")
    assert search.search(db, caller, query="共通語")["total"] == 3
    only = search.search(db, caller, query="共通語", kinds=["ai_summary", "inference"])
    assert {r["kind"] for r in only["results"]} == {"ai_summary", "inference"}
    with pytest.raises(EmlekError):
        search.search(db, caller, kinds=["note"])
    with pytest.raises(EmlekError):
        search.search(db, caller, kinds=[])


def test_hidden_records_need_asking_for(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="隠す記録")
    service.save(db, caller, body="見える記録")
    db.conn.execute("UPDATE records SET hidden = 1, hidden_at = 'now' WHERE id = 1")
    assert search.search(db, caller, query="記録")["total"] == 1
    shown = search.search(db, caller, query="記録", include_hidden=True)
    assert shown["total"] == 2 and any(r["hidden"] for r in shown["results"])


def test_sensitivity_cap_withholds_and_counts(db: Database, caller: Caller) -> None:
    for text in ("普通の記録", "個人情報の記録", "秘密の記録"):
        service.save(db, caller, body=text)
    db.conn.execute("UPDATE records SET sensitivity = 'medium' WHERE id = 2")
    db.conn.execute("UPDATE records SET sensitivity = 'high' WHERE id = 3")
    everything = search.search(db, caller, query="記録")
    assert everything["total"] == 3 and everything["withheld"] == 0
    capped = search.search(db, caller, query="記録", max_sensitivity="medium")
    assert capped["total"] == 2 and capped["withheld"] == 1
    assert "秘密" not in str(capped["results"])
    none_only = search.search(db, caller, query="記録", max_sensitivity="none")
    assert none_only["total"] == 1 and none_only["withheld"] == 2
    with pytest.raises(EmlekError):
        search.search(db, caller, max_sensitivity="secret")


def test_old_versions_match_only_when_asked(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="最初の版 ふるいことば")
    db.conn.execute(
        "INSERT INTO revisions (record_id, version_no, body, body_norm, kind, created_at)"
        " VALUES (1, 2, '改訂版 あたらしいことば', '改訂版 あたらしいことば', 'original', 'x')"
    )
    assert search.search(db, caller, query="ふるいことば")["total"] == 0
    old = search.search(db, caller, query="ふるいことば", all_versions=True)
    assert old["total"] == 1 and old["results"][0]["matched_version"] == 1
    assert old["results"][0]["latest_version"] == 2
    new = search.search(db, caller, query="あたらしいことば")
    assert new["results"][0]["matched_version"] == 2


def test_readonly_channel_may_search(db: Database, caller: Caller) -> None:
    from emlek.core.permissions import Channel

    service.save(db, caller, body="読める記録")
    result = search.search(db, Caller(Channel.MCP_READONLY), query="読める")
    assert result["total"] == 1
