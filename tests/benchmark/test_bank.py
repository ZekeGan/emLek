"""The question bank checks itself: each question answerable, each absent word really absent."""

from __future__ import annotations

import ai_runner as ar
import bank
import personas
import pytest
import scoring as sc
import synth

CORPUS = synth.build_corpus()


def test_absent_words_are_really_absent() -> None:
    text = "\n".join(e.body for e in CORPUS.entries)
    assert not [w for w in bank.ABSENT_WORDS if w in text]


def test_every_question_has_a_usable_gold_answer() -> None:
    for qid, spec in bank.SPECS.items():
        gold = spec.gold(CORPUS)
        if spec.mode in ("none", "scale"):
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
        ("你去過沖繩，雖然我沒有說明日期，但記錄在 r5。", 0),
        ("查無相關記錄，r12的內容與沖繩無關。", 4),
        ("記憶庫裡沒有事件日期是 2026 年 3 月 3 日的記錄，所以無法回答。", 5),
        ("我沒有說明日期，但記錄在 r5 還有 r7。", 0),
    ],
)
def test_absence_scoring(answer: str, score: int) -> None:
    assert sc.score_absence(answer, 700)["score"] == score


def test_refs_are_found_next_to_cjk_text_but_not_inside_words() -> None:
    assert sc.cited_refs("見r12的內容、也看r30.v2和（r7）") == [12, 30, 7]
    assert sc.cited_refs("error12 or bar5 or r12x") == []


@pytest.mark.parametrize(
    "answer",
    ["2026-10-03", "2026/10/3", "2026年10月3日", "10月3日去了鎌倉", "10/3"],
)
def test_a_date_counts_in_any_common_form(answer: str) -> None:
    assert sc.mentions_date(answer, "2026-10-03")
    assert not sc.mentions_date("2026年10月4日", "2026-10-03")


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


def test_persona_set_is_complete_synthetic_and_kept_out_of_the_other_sets() -> None:
    assert len(bank.PERSONA_IDS) == len(personas.PERSONAS) * len(personas.BASES) == 48
    for qid in bank.PERSONA_IDS:
        _, persona, base = qid.split("-")
        spec, original = bank.SPECS[qid], bank.SPECS[base]
        assert spec.group == f"persona:{persona}"
        assert spec.gold(CORPUS) == original.gold(CORPUS) and spec.mode == original.mode
        assert spec.question != original.question
    assert not set(bank.PERSONA_IDS) & set(bank.SMOKE)
    texts = [s for phrasings in personas.PERSONAS.values() for s in phrasings]
    assert len(texts) == len(set(texts))


def test_group_averages_are_reported_per_persona() -> None:
    rows = [
        {"group": "persona:kansai", "score": 5},
        {"group": "persona:kansai", "score": 3},
        {"group": "core", "score": 4},
    ]
    assert ar.by_group(rows)["persona:kansai"] == {"questions": 2, "average_score": 4.0}


@pytest.mark.parametrize(
    ("answer", "score"),
    [
        ("共 617 筆，我只看了前 20 筆，請指定年份再縮小範圍。", 5),
        ("我只看了其中一部分，請告訴我想看哪一段。", 4),
        ("總共有 617 筆提到勉強。以下是摘要：天天都在讀書。", 3),
        ("以下是你勉強的全部紀錄：天天都在讀書。", 2),
        ("共 617 筆，其中 r99999 最有代表性，我只看了一部分。", 0),
    ],
)
def test_scale_scoring_rewards_saying_only_part_was_read(answer: str, score: int) -> None:
    assert sc.score_scale(answer, 617, 3072)["score"] == score


def test_scale_question_is_separate_and_counts_real_matches() -> None:
    assert bank.SCALE_IDS == ("Q75",) and bank.SPECS["Q75"].mode == "scale"
    corpus = synth.build_corpus(filler=bank.SCALE_FILLER)
    matches = sum(1 for e in corpus.entries if bank.SCALE_WORD in e.body)
    assert matches > 500  # far more than a page, so the question really tests the behaviour


def test_story_chain_is_planted_with_links() -> None:
    chain = [bank.SPECS[q].gold(CORPUS) for q in ("Q09", "Q10")]
    assert all(len(g) == 1 for g in chain)
    story = [e for e in CORPUS.entries if e.fact and e.fact.startswith("study_")]
    assert [e.fact for e in story] == ["study_a", "study_b", "study_c", "study_d"]
    assert story[3].links == (("study_c", "supersedes"), ("study_a", "supports"))


def test_consent_dialogues_are_well_formed_and_use_public_test_values() -> None:
    assert list(bank.CONSENT) == ["C01", "C02", "C03", "C04", "C05"]
    for item in bank.CONSENT.values():
        assert item.first and (item.asks_first or not item.replies)
        if item.saved:
            assert item.level in ("medium", "high")
    # every sensitive prompt really is caught by the core's own scan
    from emlek.core import sensitivity

    levels = {cid: sensitivity.assess(item.first)[0] for cid, item in bank.CONSENT.items()}
    assert levels == {
        "C01": "high",
        "C02": "high",
        "C03": "medium",
        "C04": "medium",
        "C05": "medium",
    }


def test_vague_questions_are_answered_by_records_that_never_use_the_question_words() -> None:
    words = {
        "vague_fight": ("吵架", "爭吵", "跟人"),
        "vague_sweets": ("甜點", "點心", "dessert"),
        "vague_gadget": ("電子", "產品", "gadget"),
        "vague_film": ("電影", "movie", "film"),
        "vague_spend": ("花很多錢", "買東西", "spend"),
        "vague_instrument": ("樂器", "instrument"),
        "vague_family": ("家人", "family"),
        "vague_worry": ("煩惱", "工作"),
    }
    for qid, (_text, fact) in bank.VAGUE_QUESTIONS.items():
        gold = bank.SPECS[qid].gold(CORPUS)
        assert len(gold) == 3, qid
        for record in gold:
            body = CORPUS.entries[record - 1].body.casefold()
            assert not [w for w in words[fact] if w.casefold() in body], (qid, body)
    # and they are not caught by the words other questions search for
    others = " ".join(
        e.body for e in CORPUS.entries if (e.fact or "").startswith("vague_")
    ).casefold()
    assert not [w for w in synth.TARGET_WORDS if w.casefold() in others]
