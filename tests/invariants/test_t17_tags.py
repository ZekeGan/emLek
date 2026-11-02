"""T17: tag names, aliases, the hierarchy and how a tag search expands."""

from __future__ import annotations

from itertools import pairwise
from typing import Any

import pytest

from emlek.core import search, service
from emlek.core import tags as tagmod
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel

AI = Caller(Channel.MCP)


def _save(db: Database, caller: Caller, body: str, *tags: str, **kw: Any) -> str:
    return str(service.save(db, caller, body=body, tags=list(tags), **kw)["ref"])


def _found(db: Database, caller: Caller, **kw: Any) -> set[str]:
    return {r["ref"] for r in search.search(db, caller, limit=100, **kw)["results"]}


def test_names_are_matched_after_normalisation(db: Database, caller: Caller) -> None:
    ref = _save(db, caller, "ラーメンを食べた", "ラーメン")
    # half-width kana, full-width latin and case all name the same tag
    assert _found(db, caller, tags=["ﾗｰﾒﾝ"]) == {ref}
    _save(db, caller, "Ｒａｍｅｎ", "Ramen")
    assert _found(db, caller, tags=["ＲＡＭＥＮ"]) != set()
    assert db.conn.execute("SELECT count(*) FROM tags WHERE name_key = 'ramen'").fetchone()[0] == 1


def test_an_alias_finds_the_same_records(db: Database, caller: Caller) -> None:
    ref = _save(db, caller, "拉麵很好吃", "拉麵")
    tagmod.alias(db, caller, alias_text="ramen", tag="拉麵")
    tagmod.alias(db, caller, alias_text="ラーメン", tag="拉麵")
    assert _found(db, caller, tags=["ramen"]) == {ref} == _found(db, caller, tags=["ラーメン"])
    assert tagmod.alias(db, caller, alias_text="RAMEN", tag="拉麵")["created"] is False


def test_an_alias_cannot_steal_another_name(db: Database, caller: Caller) -> None:
    _save(db, caller, "x", "京都")
    _save(db, caller, "y", "大阪")
    tagmod.alias(db, caller, alias_text="関西", tag="大阪")
    for taken in ("京都", "大阪", "関西"):
        with pytest.raises(EmlekError) as info:
            tagmod.alias(db, caller, alias_text=taken, tag="京都" if taken != "京都" else "大阪")
        assert info.value.code is ErrorCode.CONFLICT
    with pytest.raises(EmlekError) as info:
        tagmod.alias(db, caller, alias_text="x", tag="不存在")
    assert info.value.code is ErrorCode.NOT_FOUND


def test_expansion_goes_down_only(db: Database, caller: Caller) -> None:
    japan = _save(db, caller, "日本全体のメモ", "日本")
    tokyo = _save(db, caller, "東京で散歩", "東京")
    asakusa = _save(db, caller, "浅草寺でお参り", "浅草")
    tagmod.link(db, caller, parent="日本", child="東京")
    tagmod.link(db, caller, parent="東京", child="浅草")
    assert _found(db, caller, tags=["日本"]) == {japan, tokyo, asakusa}
    assert _found(db, caller, tags=["東京"]) == {tokyo, asakusa}  # not upward
    assert _found(db, caller, tags=["浅草"]) == {asakusa}
    assert _found(db, caller, tags=["日本"], expand=False) == {japan}
    result = search.search(db, caller, tags=["日本"])
    assert set(result["expanded_tags"]) == {"日本", "東京", "浅草"}


def test_expansion_stops_after_three_levels_and_two_hundred_tags(
    db: Database, caller: Caller
) -> None:
    names = [f"層{i}" for i in range(6)]
    refs = [_save(db, caller, f"メモ{i}", n) for i, n in enumerate(names)]
    for parent, child in pairwise(names):
        tagmod.link(db, caller, parent=parent, child=child)
    assert _found(db, caller, tags=["層0"]) == set(refs[:4])  # itself + 3 levels

    _save(db, caller, "根", "幅根")
    with db.transaction() as conn:
        for i in range(260):
            conn.execute(
                "INSERT INTO tags (name, name_key, type, created_by, created_at)"
                " VALUES (?, ?, 'topic', 'ai', '2026-01-01T00:00:00.000Z')",
                (f"枝{i}", f"枝{i}"),
            )
            conn.execute(
                "INSERT INTO tag_links (parent_tag_id, child_tag_id, created_by, created_at)"
                " SELECT p.id, c.id, 'ai', '2026-01-01T00:00:00.000Z'"
                " FROM tags p, tags c WHERE p.name_key = '幅根' AND c.name_key = ?",
                (f"枝{i}",),
            )
    wide = search.search(db, caller, tags=["幅根"])
    assert wide["expanded_truncated"] is True and len(wide["expanded_tags"]) == tagmod.MAX_EXPANSION


def test_cycles_and_self_links_are_refused(db: Database, caller: Caller) -> None:
    for name in ("甲", "乙", "丙"):
        _save(db, caller, name, name)
    tagmod.link(db, caller, parent="甲", child="乙")
    tagmod.link(db, caller, parent="乙", child="丙")
    for parent, child in (("丙", "甲"), ("乙", "甲"), ("甲", "甲")):
        with pytest.raises(EmlekError) as info:
            tagmod.link(db, caller, parent=parent, child=child)
        assert info.value.code is ErrorCode.INVALID_INPUT
    assert tagmod.link(db, caller, parent="甲", child="乙")["created"] is False  # idempotent


def test_all_versus_any_and_unknown_names(db: Database, caller: Caller) -> None:
    both = _save(db, caller, "小明と京都", "小明", "京都")
    only_person = _save(db, caller, "小明だけ", "小明")
    only_place = _save(db, caller, "京都だけ", "京都")
    assert _found(db, caller, tags=["小明", "京都"], match="all") == {both}
    assert _found(db, caller, tags=["小明", "京都"], match="any") == {both, only_person, only_place}
    got = search.search(db, caller, tags=["小明", "存在しない"], match="all")
    assert got["total"] == 0 and got["unknown_tags"] == ["存在しない"]
    assert _found(db, caller, tags=["小明", "存在しない"], match="any") == {both, only_person}


def test_tags_combine_with_text_and_type_filters(db: Database, caller: Caller) -> None:
    food = service.save(
        db, caller, body="京都で抹茶", tags=[{"name": "抹茶", "type": "topic"}, "京都"]
    )["ref"]
    place = service.save(db, caller, body="京都で散歩", tags=[{"name": "嵐山", "type": "place"}])[
        "ref"
    ]
    assert _found(db, caller, tags=["京都"], query="抹茶") == {food}
    assert _found(db, caller, tag_types=["place"]) == {place}
    assert _found(db, caller, tag_types=["place", "topic"]) == {food, place}
    with pytest.raises(EmlekError):
        search.search(db, caller, tag_types=["colour"])
    with pytest.raises(EmlekError):
        search.search(db, caller, match="most")


def test_hidden_records_do_not_count_for_a_tag_search(db: Database, caller: Caller) -> None:
    from emlek.core import versions

    ref = _save(db, caller, "隠れる", "秘密の話")
    keep = _save(db, caller, "残る", "秘密の話")
    versions.hide(db, caller, ref=ref)
    assert _found(db, caller, tags=["秘密の話"]) == {keep}
    assert _found(db, caller, tags=["秘密の話"], include_hidden=True) == {ref, keep}
