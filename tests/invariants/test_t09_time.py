"""T09: event time keeps its precision; date ranges and time zones behave as documented."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest

from emlek.core import search
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller

Saver = Callable[..., dict[str, Any]]


def _refs(db: Database, caller: Caller, **kwargs: Any) -> list[str]:
    return [r["ref"] for r in search.search(db, caller, **kwargs)["results"]]


@pytest.mark.parametrize("timezone", ["local", "+09:00", "-08:00"])
def test_day_precision_does_not_depend_on_the_time_zone(
    db: Database, caller: Caller, save_at: Saver, timezone: str
) -> None:
    ref = save_at("その日の記録", event_time="2026-11-01")["ref"]
    save_at("別の日", event_time="2026-11-02")
    got = _refs(db, caller, date_from="2026-11-01", date_to="2026-11-01", timezone=timezone)
    assert got == [ref]


def test_clock_precision_keeps_the_date_as_written(
    db: Database, caller: Caller, save_at: Saver
) -> None:
    late = save_at("深夜の記録", event_time="2026-01-15T23:30-08:00")["ref"]  # 16 Jan in UTC
    early = save_at("早朝の記録", event_time="2026-01-16T00:10+09:00")["ref"]  # 15 Jan in UTC
    assert _refs(db, caller, date_from="2026-01-15", date_to="2026-01-15") == [late]
    assert _refs(db, caller, date_from="2026-01-16", date_to="2026-01-16") == [early]


def test_coarse_events_match_any_range_they_overlap(
    db: Database, caller: Caller, save_at: Saver
) -> None:
    month = save_at("十一月の出来事", event_time="2026-11")["ref"]
    year = save_at("今年の出来事", event_time="2026")["ref"]
    day = save_at("特定の日", event_time="2026-11-20")["ref"]
    assert set(_refs(db, caller, date_from="2026-11-15", date_to="2026-11-25")) == {
        month,
        year,
        day,
    }
    assert set(_refs(db, caller, date_from="2026-12-01", date_to="2026-12-31")) == {year}
    assert set(_refs(db, caller, date_from="2027-01-01")) == set()
    assert set(_refs(db, caller, date_from="2026-11", date_to="2026-11")) == {month, year, day}


def test_range_ends_are_inclusive(db: Database, caller: Caller, save_at: Saver) -> None:
    first = save_at("a", event_time="2026-05-01")["ref"]
    last = save_at("b", event_time="2026-05-31")["ref"]
    save_at("c", event_time="2026-06-01")
    save_at("d", event_time="2026-04-30")
    assert set(_refs(db, caller, date_from="2026-05", date_to="2026-05")) == {first, last}


def test_undated_records_are_counted_not_dropped_silently(
    db: Database, caller: Caller, save_at: Saver
) -> None:
    dated = save_at("日付あり", event_time="2026-03-03")["ref"]
    save_at("日付なし1")
    save_at("日付なし2")
    filtered = search.search(db, caller, date_from="2026-03-01", date_to="2026-03-31")
    assert [r["ref"] for r in filtered["results"]] == [dated]
    assert filtered["undated"] == 2
    unfiltered = search.search(db, caller, order="event_time", direction="asc")
    assert unfiltered["total"] == 3 and unfiltered["undated"] == 0
    assert unfiltered["results"][0]["ref"] == dated  # undated records sort last


def test_first_and_last_occurrence_by_event_time(
    db: Database, caller: Caller, save_at: Saver
) -> None:
    save_at("京都の旅 二回目", event_time="2025-08-10")
    first = save_at("京都の旅 一回目", event_time="2025-03-20")["ref"]
    last = save_at("京都の旅 三回目", event_time="2026-10-02T10:00+09:00")["ref"]
    save_at("京都 日付不明")
    asc = search.search(db, caller, query="京都", order="event_time", direction="asc", limit=1)
    desc = search.search(db, caller, query="京都", order="event_time", direction="desc", limit=1)
    assert asc["results"][0]["ref"] == first
    assert desc["results"][0]["ref"] == last


@pytest.mark.parametrize(
    ("timezone", "expected_day"),
    [("+09:00", "2026-11-01"), ("-05:00", "2026-10-31"), ("+00:00", "2026-10-31")],
)
def test_created_at_filter_uses_the_users_calendar_day(
    db: Database, caller: Caller, save_at: Saver, timezone: str, expected_day: str
) -> None:
    ref = save_at("夜に書いた", created_at="2026-10-31T16:00:00.000Z")["ref"]
    other = "2026-11-01" if expected_day == "2026-10-31" else "2026-10-31"
    hit = _refs(
        db,
        caller,
        date_field="created_at",
        date_from=expected_day,
        date_to=expected_day,
        timezone=timezone,
    )
    miss = _refs(
        db, caller, date_field="created_at", date_from=other, date_to=other, timezone=timezone
    )
    assert hit == [ref] and miss == []


def test_created_at_filter_with_the_system_zone(
    db: Database, caller: Caller, save_at: Saver
) -> None:
    created = "2026-10-31T16:00:00.000Z"
    ref = save_at("夜に書いた", created_at=created)["ref"]
    local_day = (
        datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone().date().isoformat()
    )
    got = _refs(db, caller, date_field="created_at", date_from=local_day, date_to=local_day)
    assert got == [ref]


def test_bad_date_arguments(db: Database, caller: Caller) -> None:
    bad: tuple[dict[str, Any], ...] = (
        {"date_from": "2026-13"},
        {"date_to": "yesterday"},
        {"timezone": "Asia/Tokyo"},
        {"date_field": "updated_at"},
    )
    for kwargs in bad:
        with pytest.raises(EmlekError) as info:
            search.search(db, caller, **kwargs)
        assert info.value.code is ErrorCode.INVALID_INPUT
