"""The AI-layer scoring rules themselves (no model calls)."""

from __future__ import annotations

import json
from pathlib import Path

import ai_runner as ar
import pytest
import synth


def test_single_answer_is_judged_by_the_first_record_named() -> None:
    answer = "第一次是 2025-03-20（r466.v1）。其他京都紀錄：r514、r368"
    assert ar.score_answer(answer, {466}, 700, as_set=False, gold_date="2025-03-20")["score"] == 5
    assert ar.score_answer(answer, {466}, 700, as_set=False, gold_date="2025-03-21")["score"] == 4
    assert ar.score_answer(answer, {514}, 700, as_set=False, gold_date=None)["score"] == 3
    assert ar.score_answer(answer, {999}, 1000, as_set=False, gold_date=None)["score"] == 0
    assert ar.score_answer("沒有找到。", {466}, 700, as_set=False)["score"] == 0


def test_invented_records_score_zero() -> None:
    result = ar.score_answer("見 r9999", {1}, 700, as_set=True)
    assert result["score"] == 0 and "不存在" in result["note"]


@pytest.mark.parametrize(
    ("cited", "expected"),
    [("r1 r2 r3", 5), ("r1 r2", 3), ("r1 r2 r3 r4", 3), ("r1", 2), ("r9 r8", 0)],
)
def test_set_answers_use_f1_bands(cited: str, expected: int) -> None:
    assert ar.score_answer(cited, {1, 2, 3}, 100, as_set=True)["score"] == expected


def test_rescoring_keeps_the_old_score(tmp_path: Path) -> None:
    corpus = synth.build_corpus()
    gold = next(iter(corpus.ids_for("kyoto_first")))
    path = tmp_path / "report.json"
    row = {"id": "Q02", "score": 3, "answer": f"2025-03-20 是第一次（r{gold}），另有 r1、r2"}
    path.write_text(json.dumps({"questions": [row]}), encoding="utf-8")
    ar.rescore(path)
    updated = json.loads(path.read_text(encoding="utf-8"))["questions"][0]
    assert updated["score_first_rule"] == 3 and updated["score"] == 5
