"""Deterministic synthetic data for the benchmark. Every sentence here is invented.

build_corpus(): a small fictional life log (about 600 entries) with planted facts, so the
expected answer to each question is known by construction.
bulk_load(): many realistic-length rows for the scale test.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from unittest.mock import patch

from emlek.core import service
from emlek.core.db import Database
from emlek.core.permissions import Caller
from emlek.core.timeutil import utc_now_iso

TODAY = date(2026, 11, 1)
TARGET_WORDS = (
    "京都",
    "小明",
    "頭痛",
    "カット",
    "猫",
    "量子糾纏",
    "ジム",
    "筋トレ",
    "走った",
    "健身",
    "gym",
    "ユニクロ",
    "購入",
    "買了",
    "bought",
    "淺草",
    "浅草",
    "asakusa",
    "ラーメン",
    "拉麵",
    "ramen",
    "病院",
    "醫院",
    "doctor",
    "引っ越",
    "搬家",
    "moved",
)
FILLER_START = date(2025, 1, 1)
FILLER_END = date(2026, 10, 31)
RESERVED_EVENT_DATES = {date(2025, 11, 1)}  # filler never lands on "last year's today"
RESERVED_CREATED_DATES = {date(2026, 10, 18)}  # ...or on "two weeks ago"

_PLACES = ["東京", "大阪", "新宿", "渋谷", "上野", "橫濱", "札幌", "名古屋", "神戶", "福岡"]
_MEALS = ["寿司", "カレー", "蕎麦", "天ぷら", "牛丼", "うどん", "餃子", "お好み焼き"]
_VEHICLES = ["電車", "バス", "自転車", "新幹線"]
_STUDY = ["日本語", "文法", "数学", "プログラミング", "英語", "歴史"]
_TEMPLATES = [
    "今日は{p}で{m}を食べた。",
    "{p}まで{v}で行った。帰りは少し疲れた。",
    "{s}を一時間勉強した。",
    "今天在{p}吃了{m}，味道不錯。",
    "下午坐{v}去{p}散步。",
    "晚上讀了一點{s}的書。",
    "Had {m} near {p} and walked home.",
    "Studied {s} for an hour after dinner.",
    "Took the {v} to {p} in the morning.",
]


@dataclass(frozen=True)
class Entry:
    body: str
    event_time: str | None
    created_at: str
    kind: str = "original"
    fact: str | None = None


@dataclass(frozen=True)
class Corpus:
    entries: list[Entry]

    def ids_for(self, *facts: str) -> set[int]:
        """1-based record ids (insertion order) of the entries planted for these facts."""
        return {i for i, e in enumerate(self.entries, 1) if e.fact in facts}

    def id_of(self, fact: str) -> int:
        ids = self.ids_for(fact)
        assert len(ids) == 1, fact
        return next(iter(ids))


def _stamp(day: str) -> str:
    return f"{day}T12:00:00.000Z"


def _filler(rng: random.Random, count: int) -> list[Entry]:
    entries: list[Entry] = []
    span = (FILLER_END - FILLER_START).days
    while len(entries) < count:
        day = FILLER_START + timedelta(days=rng.randint(0, span))
        if day in RESERVED_EVENT_DATES or day in RESERVED_CREATED_DATES:
            continue
        text = " ".join(
            rng.choice(_TEMPLATES).format(
                p=rng.choice(_PLACES),
                m=rng.choice(_MEALS),
                v=rng.choice(_VEHICLES),
                s=rng.choice(_STUDY),
            )
            for _ in range(rng.randint(1, 3))
        )
        roll = rng.random()
        if roll < 0.80:
            event: str | None = day.isoformat()
        elif roll < 0.90:
            event = f"{day.isoformat()}T{rng.randint(6, 23):02d}:{rng.randint(0, 59):02d}+09:00"
        elif roll < 0.95:
            month = f"{day.year}-{day.month:02d}"
            event = month if month != "2025-11" else None
        else:
            event = None
        entries.append(Entry(text, event, _stamp(day.isoformat())))
    assert not any(w in e.body for e in entries for w in TARGET_WORDS)
    return entries


def _planted() -> list[Entry]:
    e: list[Entry] = []

    def add(
        body: str,
        event: str | None,
        fact: str,
        *,
        kind: str = "original",
        created: str | None = None,
    ) -> None:
        day = (event or "2026-01-01")[:10]
        e.append(Entry(body, event, created or _stamp(day), kind, fact))

    kyoto = [
        ("2025-03-20", "kyoto_first"),
        ("2025-08-10", "kyoto"),
        ("2025-12-28", "kyoto"),
        ("2026-04-05", "kyoto"),
        ("2026-07-19", "kyoto"),
        ("2026-10-02T10:00+09:00", "kyoto_last"),
    ]
    for when, fact in kyoto:
        add(f"京都で抹茶を飲んで、お寺を回った。 ({when})", when, fact)
    for n, when in enumerate(
        ["2025-02-10", "2025-06-03", "2025-10-21", "2026-01-30", "2026-05-17"]
    ):
        add(f"今天和小明見面，聊了很久 #{n}", when, "xiaoming")
    add("今天和小明見面，約好下次再聊", "2026-09-12", "xiaoming_last")
    for when in ["2025-04-14", "2025-09-02", "2026-01-11", "2026-06-23"]:
        add(f"朝から頭痛がして早く寝た ({when})", when, "headache")
    add("また頭痛。水を多めに飲んだ", "2026-10-20", "headache_last")
    for when in ["2025-02-01", "2025-03-15", "2025-05-02", "2025-06-20", "2025-08-09"]:
        add(f"美容院でカットしてもらった ({when})", when, "haircut")
    for when in ["2025-04-02", "2026-02-14"]:
        add(f"復習した単語：猫 ({when})", when, "word_cat")
    add("復習した単語：猫", "2026-10-05", "word_cat_last")
    add("復習した単語：犬", "2026-10-25", "word_dog")
    add("復習した単語：桜", "2026-10-30", "word_other")
    for n, when in enumerate(["2025-05-05", "2025-09-09", "2026-02-02", "2026-08-08"]):
        add(f"量子糾纏についての読書メモ その{n}", when, "topic")
    add("量子糾纏のまとめ：二つの粒子の相関について", "2026-08-09", "topic", kind="ai_summary")
    add("量子糾纏は応用が早く進むかもしれない（推測）", "2026-08-10", "topic", kind="inference")
    add("去年の今日のこと その一", "2025-11-01", "lastyear")
    add("去年の今日のこと その二", "2025-11-01T08:15+09:00", "lastyear")
    add("去年の今日のこと その三", "2025-11-01T23:59:59+09:00", "lastyear")
    add("前日の記録", "2025-10-31", "near_miss")
    add("翌日の記録", "2025-11-02", "near_miss")
    add("一昨年の同じ日", "2024-11-01", "near_miss")
    for when, text in [
        ("2025-04-06", "浅草寺でおみくじを引いた"),
        ("2025-12-31", "今天去淺草寺拜拜，人很多"),
        ("2026-03-08", "Walked around Asakusa and visited Senso-ji temple"),
        ("2026-09-20", "淺草寺の雷門の前で写真を撮った"),
    ]:
        add(f"{text} ({when})", when, "asakusa")
    for when, text in [
        ("2025-06-14", "ラーメンを食べた。豚骨が濃かった"),
        ("2025-10-03", "今晚吃了拉麵，湯頭很棒"),
        ("2026-01-24", "Had ramen near the station, best miso broth so far"),
        ("2026-08-30", "昼にラーメン、夜はうどん"),
    ]:
        add(f"{text} ({when})", when, "ramen")
    for when, text in [
        ("2025-07-07", "病院で定期検診を受けた"),
        ("2026-02-09", "去醫院做健康檢查，一切正常"),
        ("2026-09-01", "Doctor visit for the yearly check-up, all good"),
    ]:
        add(f"{text} ({when})", when, "clinic")
    for when, text in [
        ("2025-09-30", "来月の引っ越しの荷造りを始めた"),
        ("2026-04-01", "今天搬家，整天都在搬箱子"),
        ("2026-05-02", "We moved the last boxes into the new apartment"),
    ]:
        add(f"{text} ({when})", when, "moving")
    for when, text in [
        ("2025-05-10", "ジムで筋トレを一時間した"),
        ("2025-09-14", "朝から10キロ走った、気持ちいい"),
        ("2026-02-21", "在健身房練了胸和背"),
        ("2026-08-15", "Went to the gym for a weight session"),
    ]:
        add(f"{text} ({when})", when, "exercise")
    for when, text in [
        ("2025-03-02", "ユニクロでセーターを購入した"),
        ("2025-11-23", "今天去百貨公司買了一件外套"),
        ("2026-06-06", "Bought a new pair of sneakers at the outlet"),
    ]:
        add(f"{text} ({when})", when, "shopping")
    for n, event in enumerate(["2026-10-17", None, "2026-10-18", "2026-12-01"]):
        add(f"二週間前に記したメモ {n}", event, "review14", created="2026-10-18T03:00:00.000Z")
    return e


def build_corpus(seed: int = 7, filler: int = 600) -> Corpus:
    rng = random.Random(seed)
    entries = _filler(rng, filler) + _planted()
    rng.shuffle(entries)
    return Corpus(entries)


@contextmanager
def _clock(stamp: str) -> Iterator[None]:
    with patch.object(service, "utc_now_iso", return_value=stamp):
        yield


def load(db: Database, caller: Caller, corpus: Corpus) -> None:
    """Save every entry through the real service, with the intended created_at."""
    for entry in corpus.entries:
        with _clock(entry.created_at):
            service.save(db, caller, body=entry.body, kind=entry.kind, event_time=entry.event_time)


_JA = (
    "今日天気東京大阪新宿渋谷浅草寺拉麺豚骨醤油味噌電車新幹線"
    "勉強文法単語友達仕事会議映画散歩料理旅行買物朝昼晩疲眠楽"
)
_ZH = (
    "今天天氣東京大阪新宿澀谷淺草寺拉麵豚骨醬油味噌電車新幹線"
    "學習文法單字朋友工作會議電影散步料理旅行購物早午晚累睡開心"
)
NEEDLES = ("zxqvw-needle", "針山", "桜の針")  # absent from the pool; planted in a few rows


def _pool(rng: random.Random, size: int) -> list[str]:
    pool = []
    for _ in range(size):
        chars = rng.choice((_JA, _ZH))
        words = ["".join(rng.choices(chars, k=rng.randint(2, 9))) for _ in range(120)]
        pool.append(" ".join(words))
    return pool


def bulk_rows(rng: random.Random, count: int) -> Iterator[tuple[str, str | None, str]]:
    """Yield (body, event_time, created_at) with diary-like lengths (300-3000 characters)."""
    pool = _pool(rng, 400)
    span = (FILLER_END - FILLER_START).days
    for i in range(count):
        length = rng.choice((300, 800, 1500, 3000))
        body = ""
        while len(body) < length:
            body += rng.choice(pool) + " "
        body = body[:length]
        needle_rows = {count // 5: NEEDLES[0], count // 2: NEEDLES[1], count - 7: NEEDLES[2]}
        if i in needle_rows:
            body = body[:100] + " " + needle_rows[i] + " " + body[100:]
        day = FILLER_START + timedelta(days=rng.randint(0, span))
        event = day.isoformat() if rng.random() < 0.9 else None
        yield body, event, f"{day.isoformat()}T{rng.randint(0, 23):02d}:00:00.000Z"


def fresh_stamp() -> str:
    return utc_now_iso()
