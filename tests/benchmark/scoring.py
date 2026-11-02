"""Scoring of AI answers against the synthetic corpus (pure functions, no AI calls)."""

from __future__ import annotations

import re
from typing import Any

import bank
import synth

# ASCII lookarounds, not \b: CJK characters count as word characters, so "r12的" must still match.
REF = re.compile(r"(?<![A-Za-z0-9_])r(\d+)(?:\.v\d+)?(?![A-Za-z0-9_])")
SAYS_NONE = re.compile(
    r"沒有(?:找到|查到|搜到|相關|任何|符合|對應|關於|這|此|記錄|紀錄)|没有(?:找到|相关|任何|记录)|"
    r"沒找到|找不到|查不到|查無|未找到|無相關|資料庫裡?沒有|not found|"
    r"no (?:relevant |matching )?records?|"
    r"(?:didn't|did not|couldn't|could not|can't|cannot) find",
    re.IGNORECASE,
)


def f1_band(found: set[int], gold: set[int]) -> int:
    hit = len(found & gold)
    if hit == 0:
        return 0
    precision, recall = hit / len(found), hit / len(gold)
    f1 = 2 * precision * recall / (precision + recall)
    for floor, score in ((1.0, 5), (0.9, 4), (0.75, 3), (0.5, 2)):
        if f1 >= floor - 1e-9:
            return score
    return 1


def cited_refs(answer: str) -> list[int]:
    ordered: list[int] = []
    for match in REF.finditer(answer):
        number = int(match.group(1))
        if number not in ordered:
            ordered.append(number)
    return ordered


def mentions_date(answer: str, iso_day: str) -> bool:
    """True if the answer writes the day in a common form: 2026-10-03, 2026/10/3, 2026年10月3日,
    or 10月3日 / 10/3 (the year may be implied by the question)."""
    if len(iso_day) < 10:
        return iso_day in answer
    year, month, day = (int(part) for part in iso_day[:10].split("-"))
    forms = (
        iso_day[:10],
        f"{year}/{month}/{day}",
        f"{year}/{month:02d}/{day:02d}",
        f"{year}年{month}月{day}日",
        f"{month}月{day}日",
        f"{month}月{day}号",
        f"{month}/{day}",
    )
    return any(form in answer for form in forms)


def score_answer(
    answer: str,
    gold: set[int],
    total_records: int,
    *,
    as_set: bool,
    gold_date: str | None = None,
) -> dict[str, Any]:
    """Score by the records the answer cites.

    A single-answer question is judged by the first record the answer names (supporting
    records listed after it are fine); a set question by F1 between cited and expected.
    """
    ordered = cited_refs(answer)
    cited = set(ordered)
    invented = {i for i in cited if i < 1 or i > total_records}
    if invented:
        return {"score": 0, "cited": ordered, "note": f"引用不存在的記錄 {sorted(invented)}"}
    if as_set:
        return {"score": f1_band(cited, gold), "cited": ordered, "note": ""}
    target = next(iter(gold))
    if not ordered or target not in cited:
        return {"score": 0, "cited": ordered, "note": "沒有引用正確的記錄"}
    if ordered[0] != target:
        return {"score": 3, "cited": ordered, "note": "正確記錄不是首要答案"}
    dated = gold_date is None or mentions_date(answer, gold_date)
    return {"score": 5 if dated else 4, "cited": ordered, "note": "" if dated else "未寫出日期"}


def score_absence(answer: str, total_records: int) -> dict[str, Any]:
    """Nothing matches: the right answer says so and names no record as proof."""
    ordered = cited_refs(answer)
    invented = [i for i in ordered if i < 1 or i > total_records]
    if invented:
        return {"score": 0, "cited": ordered, "note": f"引用不存在的記錄 {invented}"}
    if not SAYS_NONE.search(answer):
        return {"score": 0, "cited": ordered, "note": "沒有如實說沒找到"}
    if ordered:
        return {"score": 4, "cited": ordered, "note": "說了沒找到，但另外列出了相近的記錄"}
    return {"score": 5, "cited": ordered, "note": ""}


def score_spec(spec: bank.Spec, corpus: synth.Corpus, answer: str) -> dict[str, Any]:
    total = len(corpus.entries)
    if spec.mode == "none":
        return score_absence(answer, total)
    gold = spec.gold(corpus)
    gold_date = None
    if spec.mode == "single":
        event = corpus.entries[next(iter(gold)) - 1].event_time
        gold_date = event[:10] if event else None
    return score_answer(answer, gold, total, as_set=spec.mode == "set", gold_date=gold_date)
