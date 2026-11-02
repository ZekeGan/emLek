"""T30: near-duplicate names, tag coverage, facets and fuzzy tag lookup."""

from __future__ import annotations

import pytest

from emlek.core import search, service
from emlek.core import tags as tagmod
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel


def test_the_same_name_is_reused_and_a_near_name_waits_for_a_decision(
    db: Database, caller: Caller
) -> None:
    service.save(db, caller, body="a", tags=["拉麵"])
    again = service.save(db, caller, body="b", tags=["拉麵"])
    assert again["tags"] == ["拉麵"] and again["tags_pending"] == []
    assert db.conn.execute("SELECT count(*) FROM tags WHERE name_key = '拉麵'").fetchone()[0] == 1

    near = service.save(db, caller, body="c", tags=["拉麵店"])
    assert near["tags"] == [] and near["tags_pending"] == [{"name": "拉麵店", "similar": ["拉麵"]}]
    assert db.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 3  # the text was saved
    forced = service.save(db, caller, body="d", tags=["拉麵店"], allow_new=["拉麵店"])
    assert forced["tags"] == ["拉麵店"] and forced["tags_pending"] == []


@pytest.mark.parametrize(
    ("new", "near"),
    [
        ("Tokyoo", True),
        ("Tokyo Tower", False),
        ("東京都", True),
        ("Kyoto", False),
        ("tokio", True),
    ],
)
def test_what_counts_as_near(db: Database, caller: Caller, new: str, near: bool) -> None:
    service.save(db, caller, body="a", tags=["Tokyo", "東京"])
    key = tagmod.normalize(new)
    assert bool(tagmod.similar_names(db.conn, key)) is near


def test_the_response_says_how_much_of_the_data_has_tags(db: Database, caller: Caller) -> None:
    for i in range(6):
        service.save(db, caller, body=f"京都のメモ {i}", tags=["旅行"] if i < 2 else None)
    service.save(db, caller, body="関係ない話")
    result = search.search(db, caller, query="京都", tags=["旅行"])
    assert result["total"] == 2
    assert result["tag_coverage"] == {"tagged": 2, "untagged": 4}  # among the records matching 京都
    assert "tag_coverage" not in search.search(db, caller, query="京都")


def test_facets_only_when_asked(db: Database, caller: Caller) -> None:
    for i in range(5):
        service.save(db, caller, body=f"京都 {i}", tags=["旅行", "抹茶"] if i < 3 else ["旅行"])
    plain = search.search(db, caller, query="京都")
    assert "facets" not in plain
    asked = search.search(db, caller, query="京都", facets=True)
    assert asked["facets"][0] == {"name": "旅行", "type": "topic", "count": 5}
    assert asked["facets"][1]["name"] == "抹茶" and asked["facets"][1]["count"] == 3


def test_an_empty_result_suggests_close_tags(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="a", tags=["Tokyo"])
    got = search.search(db, caller, tags=["Tokyoo"])
    assert (
        got["total"] == 0 and got["unknown_tags"] == ["Tokyoo"] and got["similar_tags"] == ["Tokyo"]
    )
    miss = search.search(db, caller, query="Tokyoo")
    assert miss["total"] == 0 and miss["similar_tags"] == ["Tokyo"]


def test_tags_find_tolerates_width_case_and_one_typo_but_not_script(
    db: Database, caller: Caller
) -> None:
    service.save(db, caller, body="a", tags=["Tokyo", "拉麵", "浅草寺"])
    tagmod.alias(db, caller, alias_text="ラーメン", tag="拉麵")
    seen = Caller(Channel.MCP_READONLY)

    def names(text: str) -> list[str]:
        return [r["name"] for r in tagmod.find(db, seen, text=text)["results"]]

    assert names("ＴＯＫＹＯ") == ["Tokyo"]
    assert names("Tkio") == []  # two edits away
    assert names("Tokyoo") == ["Tokyo"]  # one typo
    assert names("ﾗｰﾒﾝ") == ["拉麵"]  # through the alias, after width folding
    assert names("拉面") == []  # no automatic Simplified/Traditional conversion
    assert names("浅草") == ["浅草寺"]  # prefix


def test_tags_find_ranks_exact_before_alias_before_text(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="a", tags=[{"name": "酒", "description": "お酒、ビール、日本酒"}])
    service.save(db, caller, body="b", tags=[{"name": "日本酒", "description": "米のお酒"}])
    got = tagmod.find(db, Caller(Channel.CLI), text="日本酒")["results"]
    assert [r["name"] for r in got] == ["日本酒", "酒"]
    assert got[0]["matched_via"] == "name" and got[1]["matched_via"] == "text"


def test_listing_modes(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="a", tags=["旅行", "京都"])
    service.save(db, caller, body="b", tags=["旅行", "京都", "抹茶"])
    service.save(db, caller, body="c", tags=["旅行"])
    tagmod.link(db, caller, parent="旅行", child="京都")
    top = tagmod.listing(db, caller)["tags"]
    assert top[0] == {"name": "旅行", "type": "topic", "uses": 3}
    assert tagmod.listing(db, caller, tree="旅行")["tree"]["children"][0]["name"] == "京都"
    related = tagmod.listing(db, caller, related_to="京都")["related"]
    assert related[0] == {"name": "旅行", "together": 2}
    with pytest.raises(EmlekError) as info:
        tagmod.listing(db, caller, tree="旅行", related_to="京都")
    assert info.value.code is ErrorCode.INVALID_INPUT
    with pytest.raises(EmlekError):
        tagmod.listing(db, caller, tree="不存在")


def test_the_tag_limits(db: Database, caller: Caller) -> None:
    with pytest.raises(EmlekError):
        service.save(
            db,
            caller,
            body="a",
            tags=[
                f"{chr(0x4E00 + i * 13)}{chr(0x5000 + i * 17)}"
                for i in range(tagmod.MAX_TAGS_PER_RECORD + 1)
            ],
        )
    with pytest.raises(EmlekError):
        service.save(
            db, Caller(Channel.MCP), body="b", tags=[f"新{chr(0x4E00 + i * 7)}" for i in range(11)]
        )
    assert db.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 0


def test_the_command_line_says_unknown_tags_were_ignored_not_that_the_index_is_stale(
    data_dir: object,
) -> None:
    import subprocess
    import sys

    def run(*args: str) -> str:
        done = subprocess.run(
            [sys.executable, "-m", "emlek", "--data-dir", str(data_dir), *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )
        return (done.stdout + done.stderr).decode("utf-8", errors="replace")

    run("save", "--text", "京都で抹茶")
    out = run("search", "京都", "--tag", "沒有這個標籤")
    assert "找不到的標籤：沒有這個標籤" in out and "索引" not in out and "共 1 筆" in out
