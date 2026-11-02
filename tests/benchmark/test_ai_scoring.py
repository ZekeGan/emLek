"""The AI-layer scoring rules themselves (no model calls)."""

from __future__ import annotations

import json
from pathlib import Path

import ai_runner as ar
import pytest
import scoring as sc
import synth


def test_single_answer_is_judged_by_the_first_record_named() -> None:
    answer = "第一次是 2025-03-20（r466.v1）。其他京都紀錄：r514、r368"
    assert sc.score_answer(answer, {466}, 700, as_set=False, gold_date="2025-03-20")["score"] == 5
    assert sc.score_answer(answer, {466}, 700, as_set=False, gold_date="2025-03-21")["score"] == 4
    assert sc.score_answer(answer, {514}, 700, as_set=False, gold_date=None)["score"] == 3
    assert sc.score_answer(answer, {999}, 1000, as_set=False, gold_date=None)["score"] == 0
    assert sc.score_answer("沒有找到。", {466}, 700, as_set=False)["score"] == 0


def test_invented_records_score_zero() -> None:
    result = sc.score_answer("見 r9999", {1}, 700, as_set=True)
    assert result["score"] == 0 and "不存在" in result["note"]


@pytest.mark.parametrize(
    ("cited", "expected"),
    [("r1 r2 r3", 5), ("r1 r2", 3), ("r1 r2 r3 r4", 3), ("r1", 2), ("r9 r8", 0)],
)
def test_set_answers_use_f1_bands(cited: str, expected: int) -> None:
    assert sc.score_answer(cited, {1, 2, 3}, 100, as_set=True)["score"] == expected


def test_rescoring_keeps_the_old_score(tmp_path: Path) -> None:
    corpus = synth.build_corpus()
    gold = next(iter(corpus.ids_for("kyoto_first")))
    path = tmp_path / "report.json"
    row = {"id": "Q02", "score": 3, "answer": f"2025-03-20 是第一次（r{gold}），另有 r1、r2"}
    path.write_text(json.dumps({"questions": [row]}), encoding="utf-8")
    ar.rescore(path)
    updated = json.loads(path.read_text(encoding="utf-8"))["questions"][0]
    assert updated["score_first_rule"] == 3 and updated["score"] == 5


def test_the_stream_parser_keeps_every_tool_call_and_its_result_size() -> None:
    import json as _json

    import ai_runner

    events = [
        {"type": "system"},
        {
            "type": "assistant",
            "message": {
                "id": "m1",
                "usage": {"input_tokens": 1},
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "mcp__emlek__search",
                        "input": {"query": "醫院 OR 診所"},
                    }
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": "x" * 40,
                        "is_error": True,
                    }
                ]
            },
        },
        {"type": "result", "result": "done", "num_turns": 2, "usage": {}},
    ]
    parsed = ai_runner.parse_stream("\n".join(_json.dumps(e, ensure_ascii=False) for e in events))
    assert parsed is not None
    final, calls = parsed
    assert final["result"] == "done"
    assert final["api_requests"] == 1
    assert calls == [
        {"name": "search", "input": {"query": "醫院 OR 診所"}, "result_chars": 40, "is_error": True}
    ]
    assert ai_runner.parse_stream("not json at all") is None


def test_records_mentioned_only_as_excluded_do_not_lower_the_adjusted_score() -> None:
    import bank
    import scoring
    import synth

    corpus = synth.build_corpus()
    spec = bank.SPECS["Q66"]  # "last month, did I go to Kyoto?" -> exactly one record
    gold = next(iter(spec.gold(corpus)))
    other = next(i for i in range(1, 50) if i != gold)
    answer = (
        f"有的，上個月去過：r{gold}（京都で抹茶）。\n\n"
        "**其他京都紀錄（不在 10 月）**\n"
        f"- r{other}：另一次\n"
        f"- r{other + 1}：再一次\n\n"
        "以上是全部。"
    )
    result = scoring.score_spec(spec, corpus, answer)
    assert result["score"] < 5 and result["adjusted_score"] == 5


def test_a_wrong_main_answer_is_not_rescued_by_the_adjustment() -> None:
    import bank
    import scoring
    import synth

    corpus = synth.build_corpus()
    spec = bank.SPECS["Q66"]
    gold = next(iter(spec.gold(corpus)))
    wrong = [i for i in range(1, 60) if i != gold][:3]
    answer = "有的：" + "、".join(f"r{i}" for i in wrong) + "。"
    result = scoring.score_spec(spec, corpus, answer)
    assert result["adjusted_score"] == result["score"] == 0


def test_the_adjusted_score_is_never_below_the_raw_score() -> None:
    import bank
    import scoring
    import synth

    corpus = synth.build_corpus()
    spec = bank.SPECS["Q66"]
    gold = next(iter(spec.gold(corpus)))
    # the right record sits on a line that happens to contain a marker word
    answer = f"r{gold} 是這筆，其他細節見原文。"
    result = scoring.score_spec(spec, corpus, answer)
    assert result["adjusted_score"] >= result["score"]


def test_without_extras_drops_lines_and_the_block_under_a_marked_heading() -> None:
    import scoring

    text = "答案 r1\n已排除：r2\n\n**其他相關紀錄**\n- r3\n- r4\n\n結尾 r5"
    assert scoring.without_extras(text) == "答案 r1\n\n\n結尾 r5"
