"""T08: the full-text index always agrees with the data, and a silent index never means "none"."""

from __future__ import annotations

import random
import unicodedata
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from emlek.config import load_config
from emlek.core import search, service
from emlek.core.db import Database
from emlek.core.doctor import run_checks
from emlek.core.permissions import Caller, Channel
from emlek.core.vault import init_vault

POOL = (
    "今日天気東京大阪京都新宿渋谷拉麺豚骨醤油味噌電車勉強文法単語友達仕事会議映画散歩料理旅行"
    "今天氣學習朋友工作會議電影散步購物早午晚累睡開心 abcdefghij klmnop QRSTUV 0123456789"
)


@pytest.fixture(scope="module")
def corpus_db(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Database, list[str]]]:
    path = tmp_path_factory.mktemp("corpus") / "vault"
    cli = Caller(Channel.CLI)
    init_vault(cli, path)
    db = Database.open(load_config(path).db_path)
    rng = random.Random(3)
    bodies = ["".join(rng.choice(POOL) for _ in range(rng.randint(15, 90))) for _ in range(150)]
    for body in bodies:
        service.save(db, cli, body=body)
    yield db, [service.normalize_for_search(b) for b in bodies]
    db.close()


def _expected(norms: list[str], terms: list[str]) -> set[str]:
    return {f"r{i}" for i, n in enumerate(norms, 1) if all(t in n for t in terms)}


@settings(max_examples=120, deadline=None)
@given(
    st.lists(
        st.tuples(st.integers(0, 149), st.integers(0, 60), st.integers(1, 5)),
        min_size=1,
        max_size=3,
    )
)
def test_search_equals_brute_force(
    corpus_db: tuple[Database, list[str]], picks: list[tuple[int, int, int]]
) -> None:
    db, norms = corpus_db
    terms = []
    for index, start, length in picks:
        piece = norms[index][start : start + length].strip()
        if piece and " " not in piece:
            terms.append(piece)
    if not terms:
        return
    result = search.search(db, Caller(Channel.CLI), query=" ".join(terms), limit=100)
    expected = _expected(norms, list(dict.fromkeys(terms)))
    assert result["total"] == len(expected)
    if result["total"] <= 100:
        assert {r["ref"] for r in result["results"]} == expected


def test_index_stays_in_step_with_saves(db: Database, caller: Caller) -> None:
    for text in ("一つ目の記録", "second record", "第三筆記錄"):
        service.save(db, caller, body=text)
        status = search.index_status(db)
        assert status["ok"] and status["indexed"] == status["revisions"]
    db.conn.execute("INSERT INTO revisions_fts (revisions_fts) VALUES ('integrity-check')")


def test_index_removal_follows_purge(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="消える予定の記録")
    with db.purge_mode(), db.transaction() as conn:
        conn.execute("DELETE FROM revisions")
        conn.execute("DELETE FROM records")
    assert search.index_status(db) == {"revisions": 0, "indexed": 0, "ok": True}
    assert search.search(db, caller, query="消える予定")["total"] == 0
    db.conn.execute("INSERT INTO revisions_fts (revisions_fts) VALUES ('integrity-check')")


def test_a_damaged_index_is_detected_and_not_mistaken_for_no_results(
    db: Database, data_dir: Path, caller: Caller
) -> None:
    ref = service.save(db, caller, body="京都の新幹線に乗った")["ref"]
    db.conn.execute("INSERT INTO revisions_fts (revisions_fts) VALUES ('delete-all')")
    result = search.search(db, caller, query="新幹線")
    assert [r["ref"] for r in result["results"]] == [ref]
    assert result["warnings"] == ["index_stale"]
    checks = {c["name"]: c["status"] for c in run_checks(caller, data_dir)["checks"]}
    assert checks["search_index"] == "warn"
    assert search.reindex(db, caller)["ok"] is True
    healed = search.search(db, caller, query="新幹線")
    assert healed["warnings"] == [] and healed["total"] == 1


def test_really_absent_terms_stay_absent(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="京都の新幹線に乗った")
    result = search.search(db, caller, query="存在しない言葉")
    assert result["total"] == 0 and result["warnings"] == []


def test_fts_syntax_characters_are_taken_literally(
    db: Database, caller: Caller, save_at: Callable[..., dict[str, Any]]
) -> None:
    save_at('a-b AND c* (test) "quoted" NEAR(x y) ^start')
    save_at("plain words only")
    for query in ('"quoted"', "c*", "a-b", "(test)", "NEAR(x", "^start", "AND"):
        result = search.search(db, caller, query=query)
        assert result["total"] == 1, query
    assert search.search(db, caller, query="'; DROP TABLE records; --")["total"] == 0


def test_like_wildcards_are_taken_literally(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="100% sure")
    service.save(db, caller, body="100 percent")
    service.save(db, caller, body="snake_case name")
    service.save(db, caller, body="snakeXcase name")
    assert search.search(db, caller, query="0%")["total"] == 1
    assert search.search(db, caller, query="e_c")["total"] == 1
    assert search.search(db, caller, query="\\")["total"] == 0


def test_short_and_long_terms_combine(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="東京で新幹線に乗る")
    service.save(db, caller, body="大阪で新幹線に乗る")
    service.save(db, caller, body="東京で電車に乗る")
    assert (
        search.search(db, caller, query="新幹線 東京")["total"] == 1
    )  # 3-char index + 2-char scan
    assert search.search(db, caller, query="東京")["total"] == 2  # scan only
    assert search.search(db, caller, query="乗")["total"] == 3  # single character
    assert unicodedata.normalize("NFKC", "ｱ") == "ア"
