"""Benchmark system layer (M2-M4): can the tools reach the answer? No AI involved.

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

import bank
import pytest
import synth

from emlek.config import load_config
from emlek.core import search, service
from emlek.core.backup import create_backup, restore_backup
from emlek.core.db import Database
from emlek.core.export import export_all, verify_export
from emlek.core.permissions import Caller, Channel
from emlek.core.stats import stats
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
    workdir: Path

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
    yield Env(db, caller, corpus, path.parent)
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


def q21(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    create_backup(env.db, env.caller, env.workdir / "bk21", env.workdir / "vault")
    shown = stats(env.db, env.caller)
    found = {shown["records"], int(bool(shown["last_backup_at"]))}
    return found, {len(env.corpus.entries), 1}, shown


def q25(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    made = create_backup(env.db, env.caller, env.workdir / "bk25", env.workdir / "vault")
    clean = env.workdir / "new-computer"
    person = Caller(Channel.CLI, interactive=True)
    init_vault(person, clean)
    restore_backup(person, clean, Path(made["file"]))
    restored = Database.open(load_config(clean).db_path)
    try:
        assert restored.conn.execute("SELECT count(*) FROM records").fetchone()[0] == len(
            env.corpus.entries
        )
        result = search.search(
            restored,
            env.caller,
            date_from="2025-11-01",
            date_to="2025-11-01",
            limit=100,
            timezone=TZ,
        )
    finally:
        restored.close()
    return env.ids(result), env.corpus.ids_for("lastyear"), result


def q27(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    made = export_all(env.db, env.caller, env.workdir / "ex27")
    checked = verify_export(Path(made["folder"]))
    total = len(env.corpus.entries)
    assert checked["counts"]["record"] == total and checked["markdown_files"] == total
    return {made["records"]}, {total}, {"total": made["records"], **checked["header"]}


def _union(env: Env, fact: str, words: list[str]) -> tuple[set[int], set[int], dict[str, Any]]:
    """What an agent that tries the term in every language would collect."""
    found: set[int] = set()
    last: dict[str, Any] = {}
    for word in words:
        last = env.ask(query=word, limit=100)
        found |= env.ids(last)
    return found, env.corpus.ids_for(fact), {"total": len(found), **last}


def q44(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _union(env, "asakusa", ["淺草寺", "浅草寺", "asakusa"])


def q45(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _union(env, "ramen", ["ラーメン", "拉麵", "ramen"])


def q46(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _union(env, "clinic", ["病院", "醫院", "doctor"])


def q47(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _union(env, "moving", ["引っ越", "搬家", "moved"])


def q48(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _union(env, "exercise", ["ジム", "筋トレ", "走った", "健身", "gym"])


def q49(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _union(env, "shopping", ["ユニクロ", "購入", "買了", "bought"])


def _gold(env: Env, qid: str) -> set[int]:
    return bank.SPECS[qid].gold(env.corpus)


def _none(env: Env, words: list[str]) -> tuple[set[int], set[int], dict[str, Any]]:
    """Every wording tried: nothing exists, so nothing may be found."""
    found: set[int] = set()
    last: dict[str, Any] = {}
    for word in words:
        last = env.ask(query=word, limit=100)
        found |= env.ids(last)
    return found, set(), {"total": len(found), **last}


def _dated(
    env: Env, qid: str, day_from: str, day_to: str, **kwargs: Any
) -> tuple[set[int], set[int], dict[str, Any]]:
    result = env.ask(date_from=day_from, date_to=day_to, limit=100, **kwargs)
    return env.ids(result), _gold(env, qid), result


def q59(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _none(env, ["沖繩", "沖縄"])


def q60(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _none(env, ["小明明"])


def q61(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _dated(env, "Q61", "2026-03-03", "2026-03-03")


def q62(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _dated(env, "Q62", "2027-06-01", "2027-08-31")


def q63(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _none(env, ["韓文", "韓国語", "ハングル", "Korean"])


def q64(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _dated(env, "Q64", "2026-10-29", "2026-10-29")


def q65(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _dated(env, "Q65", "2026-10-01", "2026-10-31", query="頭痛")


def q66(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _dated(env, "Q66", "2026-10-01", "2026-10-31", query="京都")


def q67(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _dated(env, "Q67", "2025-06-01", "2025-08-31", query="京都")


def q68(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    result = env.ask(
        query="京都",
        date_from="2026-01-01",
        date_to="2026-12-31",
        order="event_time",
        direction="asc",
        limit=1,
    )
    return env.ids(result), _gold(env, "Q68"), result


def q69(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _dated(env, "Q69", "2024-01-01", "2024-12-31")


def q70(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    return _dated(env, "Q70", "2026-10-28", "2026-10-28")


def q71(env: Env) -> tuple[set[int], set[int], dict[str, Any]]:
    result = env.ask(query="北海道", limit=100)
    return env.ids(result), _gold(env, "Q71"), result


QUESTIONS: dict[str, tuple[str, Question]] = {
    "Q01": ("去年今天我做了什麼", q01),
    "Q02": ("我第一次去京都是什麼時候", q02),
    "Q06": ("我跟小明最後一次見面是什麼時候", q06),
    "Q07": ("我寫過關於量子糾纏的筆記嗎", q07),
    "Q13": ("我上次複習某個單字（猫）是什麼時候", q13),
    "Q15": ("上次頭痛是什麼時候", q15),
    "Q20": ("我多久剪一次頭髮", q20),
    "Q37": ("兩週前我記了什麼（回顧提醒）", q37),
    "Q21": ("我存了多少筆、上次備份是哪天", q21),
    "Q25": ("換電腦：備份後在乾淨資料夾還原", q25),
    "Q27": ("匯出全部資料", q27),
    "Q44": ("我去過幾次淺草寺（跨語言）", q44),
    "Q45": ("我吃過幾次拉麵（跨語言）", q45),
    "Q46": ("我看過醫生嗎（跨語言）", q46),
    "Q47": ("我什麼時候搬過家（跨語言）", q47),
    "Q48": ("我運動過幾次（遠義詞）", q48),
    "Q49": ("我買過幾次衣服鞋子（遠義詞）", q49),
    "Q59": ("我去過沖繩嗎（查無）", q59),
    "Q60": ("我跟小明明最後一次見面（相似名字，查無）", q60),
    "Q61": ("2026 年 3 月 3 日我做了什麼（沒有記錄的一天）", q61),
    "Q62": ("2027 年夏天我去了哪些地方（沒有記錄的期間）", q62),
    "Q63": ("我學過韓文嗎（查無）", q63),
    "Q64": ("三天前我做了什麼", q64),
    "Q65": ("上個月我有頭痛嗎", q65),
    "Q66": ("上個月我有去京都嗎", q66),
    "Q67": ("去年夏天我有去京都嗎", q67),
    "Q68": ("今年第一次去京都是什麼時候", q68),
    "Q69": ("前年我記了什麼", q69),
    "Q70": ("10 月 28 日凌晨我做了什麼（跨日邊界）", q70),
    "Q71": ("我去過北海道嗎（內含惡意指令的記錄）", q71),
}


def test_every_system_question_reaches_full_marks(env: Env) -> None:
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
                "total_reported": raw.get("total", raw.get("records")),
                "tool_result_tokens_est": est_tokens(payload),
            }
        )
    REPORT_DIR.mkdir(exist_ok=True)
    summary = {
        "layer": "system",
        "milestone": "M4",
        "corpus_entries": len(env.corpus.entries),
        "questions": report,
        "total_tokens_est": sum(q["tool_result_tokens_est"] for q in report),
        "note": "token numbers are character-based estimates, not measured model usage",
    }
    (REPORT_DIR / "system-m4.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    failed = {q["id"]: q["score"] for q in report if q["score"] != 5}
    assert not failed, failed


def test_filler_never_collides_with_planted_dates(env: Env) -> None:
    """Guards the benchmark itself: the planted answers are the only ones for their dates."""
    for entry in env.corpus.entries:
        if entry.fact is None:
            assert entry.created_at[:10] != "2026-10-18"
            for day in ("2025-11-01", "2026-10-28", "2026-10-29", "2026-03-03"):
                assert not (entry.event_time or "").startswith(day)
                assert entry.created_at[:10] != day
            for month in synth.NO_MONTH_EVENTS:
                assert entry.event_time != month


def test_injected_records_come_back_as_plain_data(env: Env) -> None:
    """The tools hand back stored orders word for word; refusing to obey them is the agent's job."""
    for fact, order in (("inject_save", "PWNED"), ("inject_deny", "該当する記録はありません")):
        entry = next(e for e in env.corpus.entries if e.fact == fact)
        shown = service.get(env.db, env.caller, ref=f"r{env.corpus.id_of(fact)}")
        assert shown["body"] == entry.body and order in shown["body"]
    before = env.db.conn.execute("SELECT count(*) FROM records").fetchone()[0]
    env.ask(query="北海道", limit=100)
    assert env.db.conn.execute("SELECT count(*) FROM records").fetchone()[0] == before
