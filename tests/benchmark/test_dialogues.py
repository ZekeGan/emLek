"""The expanded bank is synthetic, reproducible, and rejects semantic damage."""

from __future__ import annotations

import dialogues
import pytest
from dialogue_runner import judge, original_match, seed, snapshot

from emlek.core.db import Database


def test_dialogue_bank_is_fixed_and_has_separate_holdouts() -> None:
    assert set(dialogues.CASES) == {f"D{i:02d}" for i in range(1, 25)}
    assert sum(c.holdout for c in dialogues.CASES.values()) == 6
    assert sum(len(c.turns) for c in dialogues.CASES.values()) == 35


@pytest.mark.parametrize("case", dialogues.CASES.values())
def test_dialogue_fixtures_are_usable(db: Database, case: dialogues.Dialogue) -> None:
    seed(db, case.seed)
    state = snapshot(db.path.parent)
    assert state["started"] == (case.seed != "inactive")
    assert all(t.text.strip() for t in case.turns)
    if case.seed == "years":
        assert len(state["records"]) == 55
        assert {r["event_time_precision"] for r in state["records"] if r["event_time"]} == {"month"}


@pytest.mark.parametrize(
    ("expected", "actual", "verdict"),
    [
        ("周末  walk", "周末 walk", "layout"),
        ("今天散步，天氣好。", "今天散步,天氣好。", "layout"),
        ("我不搬家", "我搬家", "review"),
        ("只去三次", "去四次", "review"),
        ("不要，記下來", "不要記下來", "review"),
        ("not a", "nota", "review"),
        ("https://example.test/a  b", "https://example.test/a b", "review"),
        ("`x  y`", "`x y`", "review"),
        ("完全相同", "完全相同", "exact"),
    ],
)
def test_original_comparison_does_not_erase_meaning(
    expected: str, actual: str, verdict: str
) -> None:
    assert original_match(expected, actual) == verdict


def test_existing_id_does_not_prove_a_write_succeeded() -> None:
    state = {"records": [{"id": 1}], "started": True}
    result = judge(dialogues.Turn("幫我記下來"), state, state, "◆ emLek｜r1.✔️", False)
    assert not result["mechanical_pass"]
    after = {"records": [{"id": 1}, {"id": 2}], "started": True}
    wrong = judge(dialogues.Turn("新增", delta=1), state, after, "◆ emLek｜r1.✔️", False)
    right = judge(dialogues.Turn("新增", delta=1), state, after, "◆ emLek｜r2.✔️", False)
    assert not wrong["mechanical_pass"] and right["mechanical_pass"]
