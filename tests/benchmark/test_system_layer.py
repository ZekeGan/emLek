"""Benchmark system layer (M2): can the tools reach the answer? No AI involved.

Each question is answered by calling the search tool the way an agent would, then scored
against the planted facts. Scores follow BENCHMARK.md (F1 bands). All M2 questions must
reach 5; the report also records an estimate of the tokens the tool results would cost.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import synth

from emlek.config import load_config
from emlek.core import search
from emlek.core.db import Database
from emlek.core.permissions import Caller, Channel
from emlek.core.vault import init_vault

REPORT_DIR = Path(__file__).resolve().parents[2] / "benchmark-output"
TZ = "+09:00"


def est_tokens(text: str) -> int:
    """Rough token estimate (marked as an estimate everywhere it is reported)."""
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    return math.ceil(ascii_chars / 4 + (len(text) - ascii_chars) / 1.5)


def f1_score(found: set[int], gold: set[int]) -> int:
    if not gold and not found:
        return 5
    hit = len(found & gold)
    if hit == 0:
        return 0
    precision, recall = hit / len(found), hit / len(gold)
    f1 = 2 * precision * recall / (precision + recall)
    for floor, score in ((1.0, 5), (0.9, 4), (0.75, 3), (0.5, 2)):
        if f1 >= floor - 1e-9:
            return score
    return 1


@dataclass
class Env:
    db: Database
    caller: Caller
    corpus: synth.Corpus

    def ask(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("timezone", TZ)
        return search.search(self.db, self.caller, **kwargs)

    def ids(self, result: dict[str, Any]) -> set[int]:
        return {int(r["ref"][1:]) for r in result["results"]}


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    path = tmp_path_factory.mktemp("bench") / "vault"
    caller = Caller(Channel.CLI)
    init_vault(caller, path)
    db = Database.open(load_config(path).db_path)
    corpus = synth.build_corpus()
    synth.load(db, caller, corpus)
    yield Env(db, caller, corpus)
    db.close()


Question = Callable[[Env], tuple[set[int], set[int], dict[str, Any]]]


def q01(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    result = env.ask(date_from="2025-11-01", date_to="2025-11-01", order="event_time", limit=100)
    return env.ids(result), env.corpus.ids_for("lastyear"), result


def q02(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    result = env.ask(query="京都", order="event_time", direction="asc", limit=1)
    return env.ids(result), env.corpus.ids_for("kyoto_first"), result


def q06(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    result = env.ask(query="小明", order="event_time", direction="desc", limit=1)
    return env.ids(result), env.corpus.ids_for("xiaoming_last"), result


def q07(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    result = env.ask(query="量子糾纏", limit=100)
    return env.ids(result), env.corpus.ids_for("topic"), result


def q13(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    result = env.ask(query="猫", kinds=["original"], order="event_time", direction="desc", limit=1)
    return env.ids(result), env.corpus.ids_for("word_cat_last"), result


def q15(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    result = env.ask(query="頭痛", order="event_time", direction="desc", limit=1)
    return env.ids(result), env.corpus.ids_for("headache_last"), result


def q20(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    result = env.ask(query="カット", order="event_time", direction="asc", limit=100)
    days = [r["event_time"] for r in result["results"]]
    assert days == ["2025-02-01", "2025-03-15", "2025-05-02", "2025-06-20", "2025-08-09"]
    return env.ids(result), env.corpus.ids_for("haircut"), result


def q37(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    result = env.ask(
        date_field="created_at", date_from="2026-10-18", date_to="2026-10-18", limit=100
    )
    return env.ids(result), env.corpus.ids_for("review14"), result


QUESTIONS: dict[str, tuple[str, Question]] = {
    "Q01": ("去年今天我做了什麼", q01),
    "Q02": ("我第一次去京都是什麼時候", q02),
    "Q06": ("我跟小明最後一次見面是什麼時候", q06),
    "Q07": ("我寫過關於量子糾纏的筆記嗎", q07),
    "Q13": ("我上次複習某個單字（猫）是什麼時候", q13),
    "Q15": ("上次頭痛是什麼時候", q15),
    "Q20": ("我多久剪一次頭髮", q20),
    "Q37": ("兩週前我記了什麼（回顧提醒）", q37),
}


def test_every_m2_question_reaches_full_marks(env: Env) -> None:
    report: list[dict[str, Any]] = []
    for qid, (text, run) in QUESTIONS.items():
        found, gold, raw = run(env)
        payload = json.dumps(raw, ensure_ascii=False)
        report.append(
            {
                "id": qid,
                "question": text,
                "score": f1_score(found, gold),
                "found": len(found),
                "expected": len(gold),
                "total_reported": raw["total"],
                "tool_result_tokens_est": est_tokens(payload),
            }
        )
    REPORT_DIR.mkdir(exist_ok=True)
    summary = {
        "layer": "system",
        "milestone": "M2",
        "corpus_entries": len(env.corpus.entries),
        "questions": report,
        "total_tokens_est": sum(q["tool_result_tokens_est"] for q in report),
        "note": "token numbers are character-based estimates, not measured model usage",
    }
    (REPORT_DIR / "system-m2.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    failed = {q["id"]: q["score"] for q in report if q["score"] != 5}
    assert not failed, failed


def test_filler_never_collides_with_planted_dates(env: Env) -> None:
    """Guards the benchmark itself: the planted answers are the only ones for their dates."""
    for entry in env.corpus.entries:
        if entry.fact is None:
            assert entry.created_at[:10] != "2026-10-18"
            assert not (entry.event_time or "").startswith("2025-11-01")
