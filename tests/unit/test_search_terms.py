"""Query parsing, date bounds, time-zone modifiers and cursor handling."""

from __future__ import annotations

import pytest

from emlek.core import search
from emlek.core.errors import EmlekError, ErrorCode


def test_terms_are_normalized_deduplicated_and_phrases_kept() -> None:
    assert search.parse_terms('  Ｒａｍｅｎ  "new york"  ramen ') == ["ramen", "new york"]
    assert search.parse_terms("") == []
    assert search.parse_terms(None) == []
    assert search.parse_terms("   ") == []


def test_query_limits() -> None:
    with pytest.raises(EmlekError) as too_long:
        search.parse_terms("x" * 513)
    assert too_long.value.code is ErrorCode.INVALID_INPUT
    with pytest.raises(EmlekError):
        search.parse_terms(" ".join(f"t{i}" for i in range(search.MAX_TERMS + 1)))
    assert (
        len(search.parse_terms(" ".join(f"t{i}" for i in range(search.MAX_TERMS))))
        == search.MAX_TERMS
    )


@pytest.mark.parametrize(
    ("value", "start", "end"),
    [
        ("2026", "2026-01-01", "2026-12-31"),
        ("2026-02", "2026-02-01", "2026-02-28"),
        ("2024-02", "2024-02-01", "2024-02-29"),
        ("2026-11-05", "2026-11-05", "2026-11-05"),
    ],
)
def test_date_bounds(value: str, start: str, end: str) -> None:
    assert search.date_bound(value, end=False) == start
    assert search.date_bound(value, end=True) == end


@pytest.mark.parametrize("value", ["26", "2026-13", "2026-02-30", "2026/01/01", "2026-1-1", "abc"])
def test_bad_dates_are_rejected(value: str) -> None:
    with pytest.raises(EmlekError) as info:
        search.date_bound(value, end=False)
    assert info.value.code is ErrorCode.INVALID_INPUT


def test_timezone_modifiers() -> None:
    assert search.tz_modifiers("local") == ["localtime"]
    assert search.tz_modifiers("+09:00") == ["+9 hours", "+0 minutes"]
    assert search.tz_modifiers("-05:30") == ["-5 hours", "-30 minutes"]
    for bad in ("Asia/Tokyo", "JST", "9"):
        with pytest.raises(EmlekError) as info:
            search.tz_modifiers(bad)
        assert info.value.code is ErrorCode.INVALID_INPUT


def test_cursor_roundtrip_and_tampering() -> None:
    cursor = search._encode_cursor("event_time", "asc", [0, "2026-01-01", 7])
    assert search._decode_cursor(cursor, "event_time", "asc") == [0, "2026-01-01", 7]
    for bad in ("", "not-base64!!", "e30="):
        with pytest.raises(EmlekError):
            search._decode_cursor(bad, "event_time", "asc")
    with pytest.raises(EmlekError):  # cursor from another ordering
        search._decode_cursor(cursor, "created_at", "asc")
    with pytest.raises(EmlekError):
        search._decode_cursor(cursor, "event_time", "desc")


def test_snippet_points_at_the_match_in_the_original_text() -> None:
    body = "前置き。" * 30 + "ＴＯＫＹＯ駅で待ち合わせ" + "。続き" * 40
    snippet = search._snippet(body, ["tokyo"])
    assert "ＴＯＫＹＯ" in snippet  # original characters, not the normalized copy
    assert snippet.startswith("…") and snippet.endswith("…")
    assert search._snippet("短い本文", []) == "短い本文"
