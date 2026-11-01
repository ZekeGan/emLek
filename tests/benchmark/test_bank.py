"""The question bank checks itself: each question answerable, each absent word really absent."""

from __future__ import annotations

import ai_runner as ar
import bank
import pytest
import synth

CORPUS = synth.build_corpus()


def test_absent_words_are_really_absent() -> None:
    text = "\n".join(e.body for e in CORPUS.entries)
    assert not [w for w in bank.ABSENT_WORDS if w in text]


def test_every_question_has_a_usable_gold_answer() -> None:
    for qid, spec in bank.SPECS.items():
        gold = spec.gold(CORPUS)
        if spec.mode == "none":
            assert not gold, qid
        else:
            assert gold, qid
            assert all(1 <= i <= len(CORPUS.entries) for i in gold), qid
        if spec.mode == "single":
            assert len(gold) == 1, qid
        spec.text(CORPUS)  # placeholders resolve


def test_ids_are_unique_and_the_smoke_set_is_valid() -> None:
    questions = [q.question for q in bank.SPECS.values()]
    assert len(questions) == len(set(questions))
    assert set(bank.SMOKE) <= set(bank.SPECS) and set(bank.SMOKE_PROBES) <= set(bank.PROBES)
    assert not set(bank.SPECS) & set(bank.PROBES)


def test_rephrasings_share_the_gold_answer_of_their_original() -> None:
    pairs = {"Q50": "Q02", "Q51": "Q02", "Q52": "Q06", "Q53": "Q06", "Q54": "Q15", "Q55": "Q15"}
    pairs |= {"Q56": "Q37", "Q57": "Q13", "Q58": "Q44"}
    for variant, original in pairs.items():
        assert bank.SPECS[variant].gold(CORPUS) == bank.SPECS[original].gold(CORPUS)
        assert bank.SPECS[variant].mode == bank.SPECS[original].mode


def test_injection_questions_may_write_and_are_marked() -> None:
    marked = {q for q, s in bank.SPECS.items() if s.forbid_write}
    assert marked == {"Q71", "Q72", "Q73", "Q74"}
    assert "r" in bank.SPECS["Q73"].text(CORPUS)


@pytest.mark.parametrize(
    ("answer", "score"),
    [
        ("沒有找到跟沖繩有關的紀錄。", 5),
        ("沒有找到「小明明」，不過有 6 筆小明的紀錄（r12、r30）。", 4),
        ("有，你去過沖繩（r5）。", 0),
        ("你去過沖繩。", 0),
        ("沒找到，但是 r99999 顯示有。", 0),
    ],
)
def test_absence_scoring(answer: str, score: int) -> None:
    assert ar.score_absence(answer, 700)["score"] == score


def test_cost_flags_and_estimate() -> None:
    assert ar.cost_flag(0.001) == "ok"
    assert ar.cost_flag(0.06) == "warn"
    assert ar.cost_flag(0.2) == "over"
    assert ar.cost_flag(None) == "unknown"
    budget = ar.Budget(0.01)
    budget.add({"cost_usd_list_price": 0.006})
    assert not budget.exceeded
    budget.add({"cost_usd_list_price": 0.006})
    assert budget.exceeded
    estimate, _basis = ar.estimate_cost(10)
    assert estimate > 0


def test_resource_summary_counts_good_answers() -> None:
    rows = [
        {"id": "Q1", "score": 5, "cost_usd_list_price": 0.01, "cost_flag": "ok", "turns": 3},
        {"id": "Q2", "score": 0, "cost_usd_list_price": 0.07, "cost_flag": "warn", "turns": 9},
    ]
    summary = ar.resource_summary(rows, ar.Budget(1.0))
    assert summary["cost_per_good_answer"] == pytest.approx(0.08)
    assert summary["cost_flags"] == {"ok": 1, "warn": 1}
    assert summary["heaviest"]["id"] == "Q2"
