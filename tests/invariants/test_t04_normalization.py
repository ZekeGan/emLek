"""T04: normalization only affects matching; the original text is never changed."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from emlek.core import search, service
from emlek.core.db import Database
from emlek.core.permissions import Caller


def _refs(db: Database, caller: Caller, query: str) -> list[str]:
    return [r["ref"] for r in search.search(db, caller, query=query)["results"]]


@pytest.mark.parametrize(
    ("saved", "query"),
    [
        ("Ramen in TOKYO", "ｔｏｋｙｏ"),  # full-width lower case
        ("Ｒａｍｅｎ ＴＯＫＹＯ", "ramen tokyo"),  # full-width saved, ASCII queried
        ("ﾗｰﾒﾝ屋に行った", "ラーメン"),  # half-width katakana
        ("Straße", "STRASSE"),  # case folding beyond ASCII
        ("１２３４５ 円", "12345"),  # full-width digits
        ("école", "école"),  # combining accent vs precomposed
    ],
)
def test_variants_match_and_original_is_untouched(
    db: Database, caller: Caller, saved: str, query: str
) -> None:
    ref = service.save(db, caller, body=saved)["ref"]
    assert _refs(db, caller, query) == [ref]
    assert service.get(db, caller, ref=ref)["body"] == saved
    assert search.search(db, caller, query=query)["results"][0]["snippet"].replace(" ", "") != ""


def test_snippets_come_from_the_original_not_the_search_copy(
    db: Database, caller: Caller, save_at: Callable[..., dict[str, Any]]
) -> None:
    save_at("Ｒａｍｅｎ ＴＯＫＹＯ で食事")
    snippet = search.search(db, caller, query="tokyo")["results"][0]["snippet"]
    assert "ＴＯＫＹＯ" in snippet


def test_traditional_and_simplified_are_not_unified(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="學習日文")
    assert _refs(db, caller, "學習") != []
    assert _refs(db, caller, "学习") == []  # handled with aliases later (M7), by design
