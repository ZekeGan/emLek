"""T26: a big result set carries a summary; reading a long body is done in pieces."""

from __future__ import annotations

import sqlite3
from collections import Counter

import pytest

from emlek.core import search, service
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller


def _fill(db: Database, caller: Caller, count: int, months: int, word: str = "共通語") -> None:
    for i in range(count):
        month = i % months
        year, mon = 2024 + month // 12, 1 + month % 12
        service.save(
            db, caller, body=f"{word} {i}", event_time=f"{year}-{mon:02d}-{1 + i % 27:02d}"
        )


def test_no_summary_at_or_below_the_threshold(db: Database, caller: Caller) -> None:
    _fill(db, caller, search.AGGREGATE_THRESHOLD, 5)
    assert "summary" not in search.search(db, caller, query="共通語")
    service.save(db, caller, body="共通語 もう一つ", event_time="2024-01-01")
    assert "summary" in search.search(db, caller, query="共通語")


def test_summary_matches_a_direct_count(db: Database, caller: Caller) -> None:
    _fill(db, caller, 120, 30)  # 30 months -> falls back to years
    result = search.search(db, caller, query="共通語", limit=5)
    summary = result["summary"]
    assert len(result["results"]) == 5  # the page itself is unchanged
    assert summary["total"] == 120 == result["total"]
    assert summary["basis"] == "keyword" and "漏掉" in summary["note"]
    rows = db.conn.execute("SELECT event_time FROM revisions").fetchall()
    assert summary["by_year"] == dict(sorted(Counter(r[0][:4] for r in rows).items()))
    assert "by_month" not in summary
    assert (summary["first"], summary["last"]) == (min(r[0] for r in rows), max(r[0] for r in rows))


def test_summary_by_month_for_a_short_span(db: Database, caller: Caller) -> None:
    _fill(db, caller, 90, 6)
    summary = search.search(db, caller, query="共通語")["summary"]
    assert set(summary["by_month"]) == {f"2024-{m:02d}" for m in range(1, 7)}
    assert sum(summary["by_month"].values()) == 90 and summary["undated"] == 0


def test_undated_records_are_counted_apart(db: Database, caller: Caller) -> None:
    _fill(db, caller, 60, 3)
    for i in range(7):
        service.save(db, caller, body=f"共通語 日付なし {i}")
    summary = search.search(db, caller, query="共通語")["summary"]
    assert summary["undated"] == 7 and sum(summary["by_month"].values()) == 60
    assert summary["total"] == 67


def test_summary_can_follow_the_stored_date(db: Database, caller: Caller) -> None:
    _fill(db, caller, 60, 3)
    summary = search.search(db, caller, query="共通語", date_field="created_at")["summary"]
    assert summary["date_field"] == "created_at" and sum(summary["by_month"].values()) == 60


def test_get_cuts_long_bodies_and_offset_reads_the_rest(db: Database, caller: Caller) -> None:
    text = "".join(chr(0x3042 + i % 80) for i in range(20_000))
    ref = str(service.save(db, caller, body=text)["ref"])
    whole = service.get(db, caller, ref=ref)
    assert whole["body"] == text and whole["truncated"] is False  # core callers see everything

    parts: list[str] = []
    offset = 0
    while True:
        piece = service.get(db, caller, ref=ref, offset=offset, max_chars=8000)
        parts.append(piece["body"])
        assert piece["body_chars"] == 20_000
        if not piece["truncated"]:
            break
        offset = piece["next_offset"]
    assert len(parts) == 3 and "".join(parts) == text

    short = service.get(db, caller, ref=ref, offset=19_990, max_chars=8000)
    assert short["truncated"] is False and short["next_offset"] is None
    with pytest.raises(EmlekError) as info:
        service.get(db, caller, ref=ref, offset=-1)
    assert info.value.code is ErrorCode.INVALID_INPUT


def test_existing_fields_are_unchanged(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="単発の記録", event_time="2026-01-02")
    result = search.search(db, caller, query="単発")
    for key in ("total", "undated", "withheld", "order", "dir", "results", "next_cursor", "hints"):
        assert key in result
    assert result["results"][0]["status"] == "current"
    assert isinstance(db.conn, sqlite3.Connection)
