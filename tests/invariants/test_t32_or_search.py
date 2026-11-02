"""T32: words in one group must all appear, a bare uppercase OR means "any group", and an
empty answer says which word found what."""

from __future__ import annotations

from typing import Any

import pytest

from emlek.core import search, service, versions
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller


def _save(db: Database, caller: Caller, body: str, **kw: Any) -> str:
    return str(service.save(db, caller, body=body, **kw)["ref"])


def _found(db: Database, caller: Caller, query: str, **kw: Any) -> set[str]:
    return {r["ref"] for r in search.search(db, caller, query=query, limit=100, **kw)["results"]}


@pytest.fixture
def filled(db: Database, caller: Caller) -> dict[str, str]:
    return {
        "hospital": _save(db, caller, "病院で定期検診を受けた", event_time="2026-02-09"),
        "clinic": _save(db, caller, "駅前のクリニックに行った", event_time="2026-05-01"),
        "checkup": _save(db, caller, "去醫院做健康檢查，一切正常", event_time="2026-03-10"),
        "ramen": _save(db, caller, "ラーメンを食べた", event_time="2026-04-01"),
        "both": _save(db, caller, "病院の帰りにラーメンを食べた", event_time="2026-06-01"),
    }


def test_words_in_one_group_must_all_appear(
    db: Database, caller: Caller, filled: dict[str, str]
) -> None:
    assert _found(db, caller, "病院 ラーメン") == {filled["both"]}
    assert _found(db, caller, "病院") == {filled["hospital"], filled["both"]}


def test_or_means_any_group(db: Database, caller: Caller, filled: dict[str, str]) -> None:
    got = _found(db, caller, "病院 OR クリニック OR 醫院")
    assert got == {filled["hospital"], filled["both"], filled["clinic"], filled["checkup"]}
    # a group can have several words: (病院 and ラーメン) or クリニック
    assert _found(db, caller, "病院 ラーメン OR クリニック") == {filled["both"], filled["clinic"]}


def test_only_a_bare_uppercase_or_is_an_operator(db: Database, caller: Caller) -> None:
    both = _save(db, caller, "cats or dogs are nice")
    only_cats = _save(db, caller, "cats are nice")
    assert _found(db, caller, "cats or dogs") == {both}  # lowercase: just a word
    assert _found(db, caller, 'cats "OR" dogs') == {both}  # quoted: the word "or", not an operator
    assert _found(db, caller, "cats OR dogs") == {both, only_cats}


@pytest.mark.parametrize("query", ["OR 病院", "病院 OR", "OR OR 病院 OR OR"])
def test_stray_operators_are_ignored(
    db: Database, caller: Caller, filled: dict[str, str], query: str
) -> None:
    assert _found(db, caller, query) == {filled["hospital"], filled["both"]}


def test_a_lone_or_is_no_query_at_all(db: Database, caller: Caller, filled: dict[str, str]) -> None:
    assert search.search(db, caller, query="OR", limit=100)["total"] == len(filled)


def test_the_limits(db: Database, caller: Caller) -> None:
    for query in (" OR ".join(f"語{i}" for i in range(search.MAX_ALTERNATIVES + 1)),):
        with pytest.raises(EmlekError) as info:
            search.search(db, caller, query=query)
        assert info.value.code is ErrorCode.INVALID_INPUT
    too_many = " ".join(f"詞{i}" for i in range(search.MAX_TERMS + 1))
    with pytest.raises(EmlekError):
        search.search(db, caller, query=too_many)


@pytest.mark.parametrize(
    ("order", "direction"),
    [
        ("relevance", "asc"),
        ("created_at", "desc"),
        ("created_at", "asc"),
        ("event_time", "desc"),
        ("event_time", "asc"),
    ],
)
def test_paging_through_an_or_query_has_no_gaps_or_repeats(
    db: Database, caller: Caller, order: str, direction: str
) -> None:
    for i in range(17):
        _save(db, caller, f"病院 メモ {i}", event_time=f"2026-0{1 + i % 6}-1{i % 9}")
        _save(db, caller, f"クリニック メモ {i}")
    whole = search.search(
        db, caller, query="病院 OR クリニック", order=order, direction=direction, limit=100
    )
    assert whole["total"] == 34
    walked: list[str] = []
    cursor = None
    while True:
        page = search.search(
            db,
            caller,
            query="病院 OR クリニック",
            order=order,
            direction=direction,
            limit=5,
            cursor=cursor,
        )
        walked += [r["ref"] for r in page["results"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert walked == [r["ref"] for r in whole["results"]] and len(set(walked)) == 34


def test_or_works_with_dates_tags_and_hidden_records(
    db: Database, caller: Caller, filled: dict[str, str]
) -> None:
    assert _found(db, caller, "病院 OR クリニック", date_from="2026-05", date_to="2026-12") == {
        filled["clinic"],
        filled["both"],
    }
    versions.hide(db, caller, ref=filled["clinic"])
    assert filled["clinic"] not in _found(db, caller, "病院 OR クリニック")
    service.save(db, caller, body="京都の話", tags=["旅行"])
    ref = _save(db, caller, "病院の話", tags=["旅行"])
    assert _found(db, caller, "病院 OR 京都", tags=["旅行"]) == {ref, _save_ref(db, "京都の話")}


def _save_ref(db: Database, body: str) -> str:
    row = db.conn.execute(
        "SELECT record_id FROM revisions WHERE body = ? ORDER BY id DESC", (body,)
    ).fetchone()
    return f"r{row[0]}"


def test_a_stale_index_still_answers_an_or_query(
    db: Database, caller: Caller, filled: dict[str, str]
) -> None:
    db.conn.execute("INSERT INTO revisions_fts (revisions_fts) VALUES ('delete-all')")
    got = search.search(db, caller, query="病院 OR クリニック", limit=100)
    assert got["warnings"] == ["index_stale"] and got["total"] == 3


def test_an_empty_answer_says_which_word_found_what(
    db: Database, caller: Caller, filled: dict[str, str]
) -> None:
    got = search.search(db, caller, query="病院 薬局")
    assert got["total"] == 0 and got["term_hits"] == {"病院": 2, "薬局": 0}
    hint = got["hints"][-1]
    assert "term_hits" in hint and "病院" in hint and "OR" in hint
    none_at_all = search.search(db, caller, query="薬局 歯科")
    assert none_at_all["term_hits"] == {"薬局": 0, "歯科": 0}
    assert "每個詞單獨都沒有命中" in none_at_all["hints"][-1]


def test_no_hit_counts_when_there_is_nothing_to_explain(
    db: Database, caller: Caller, filled: dict[str, str]
) -> None:
    assert "term_hits" not in search.search(db, caller, query="薬局")  # one word
    assert "term_hits" not in search.search(db, caller, query="病院 OR 薬局")  # it found something
    assert "term_hits" not in search.search(db, caller, query="病院 ラーメン")


def test_hit_counts_never_count_what_the_caller_may_not_see(db: Database, caller: Caller) -> None:
    hidden = _save(db, caller, "秘密の薬局メモ")
    secret = _save(db, caller, "薬局で買い物")
    shown = _save(db, caller, "薬局へ行った")
    versions.hide(db, caller, ref=hidden)
    service.set_sensitivity(
        db, Caller(caller.channel, interactive=True, pin_verified=True), ref=secret, level="high"
    )
    got = search.search(db, caller, query="薬局 歯科", max_sensitivity="medium")
    assert got["term_hits"] == {"薬局": 1, "歯科": 0}
    assert shown  # only this one is visible
