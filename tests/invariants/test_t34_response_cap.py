"""T34: one search answer can be capped in size without losing the way to the rest."""

from __future__ import annotations

from emlek.core import search, service
from emlek.core.db import Database
from emlek.core.permissions import Caller


def _fill(db: Database, caller: Caller, count: int) -> None:
    for i in range(count):
        service.save(db, caller, body=f"共通の言葉 {i} " + "あ" * 150, event_time="2026-05-01")


def test_a_capped_answer_is_shorter_and_says_how_to_continue(db: Database, caller: Caller) -> None:
    _fill(db, caller, 40)
    whole = search.search(db, caller, query="共通の言葉", limit=40)
    capped = search.search(db, caller, query="共通の言葉", limit=40, max_response_chars=3000)
    assert len(whole["results"]) == 40 and "results_trimmed" not in whole
    assert 0 < len(capped["results"]) < 40
    assert capped["results_trimmed"] == 40 - len(capped["results"])
    assert capped["total"] == 40 and capped["next_cursor"]
    assert any("回應太長" in hint for hint in capped["hints"])


def test_walking_the_capped_pages_still_reaches_every_record_once(
    db: Database, caller: Caller
) -> None:
    _fill(db, caller, 40)
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        page = search.search(
            db, caller, query="共通の言葉", limit=40, cursor=cursor, max_response_chars=2500
        )
        seen += [r["ref"] for r in page["results"]]
        cursor, pages = page["next_cursor"], pages + 1
        if not cursor:
            break
    assert pages > 2 and len(seen) == len(set(seen)) == 40


def test_the_cap_never_empties_an_answer(db: Database, caller: Caller) -> None:
    _fill(db, caller, 5)
    tiny = search.search(db, caller, query="共通の言葉", limit=5, max_response_chars=10)
    assert len(tiny["results"]) == 1 and tiny["next_cursor"]


def test_without_a_cap_nothing_changes(db: Database, caller: Caller) -> None:
    _fill(db, caller, 10)
    got = search.search(db, caller, query="共通の言葉", limit=10)
    assert len(got["results"]) == 10 and got["next_cursor"] is None
