"""T31: merging and removing tags, who may do it, and what an export carries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emlek.core import search, service
from emlek.core import tags as tagmod
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.export import export_all, verify_export
from emlek.core.permissions import Caller, Channel

PERSON = Caller(Channel.CLI, interactive=True, pin_verified=True)


def _tags(db: Database, ref: str) -> set[str]:
    return {t["name"] for t in tagmod.tags_of(db.conn, int(ref[1:]))}


def test_merge_moves_records_and_turns_the_old_name_into_an_alias(
    db: Database, caller: Caller
) -> None:
    a = service.save(db, caller, body="a", tags=["Ramen"])["ref"]
    b = service.save(db, caller, body="b", tags=["拉麵"])["ref"]
    both = service.save(db, caller, body="c", tags=["Ramen", "拉麵"])["ref"]
    done = tagmod.merge(db, PERSON, old="Ramen", new="拉麵")
    assert done["into"] == "拉麵" and done["records_moved"] == 1
    assert _tags(db, a) == {"拉麵"} and _tags(db, both) == {"拉麵"}  # no duplicate
    found = search.search(db, caller, tags=["Ramen"])  # the old name still works, as an alias
    assert {r["ref"] for r in found["results"]} == {a, b, both}
    assert db.conn.execute("SELECT count(*) FROM tags WHERE name_key = 'ramen'").fetchone()[0] == 0
    actions = [r[0] for r in db.conn.execute("SELECT action FROM tag_events")]
    assert "tag_merge" in actions


def test_merge_keeps_the_hierarchy_and_skips_what_would_loop(db: Database, caller: Caller) -> None:
    for name in ("上", "中", "下", "別名候補"):
        service.save(db, caller, body=name, tags=[name])
    tagmod.link(db, caller, parent="上", child="中")
    tagmod.link(db, caller, parent="中", child="下")
    tagmod.link(db, caller, parent="別名候補", child="下")
    done = tagmod.merge(db, PERSON, old="別名候補", new="上")  # 上 > 下 is fine, nothing loops
    assert done["links_skipped"] == []
    assert {c["name"] for c in tagmod.listing(db, caller, tree="上")["tree"]["children"]} == {
        "中",
        "下",
    }
    again = tagmod.merge(db, PERSON, old="下", new="上")  # would make 上 contain itself
    assert again["links_skipped"] and "上 > 上" in again["links_skipped"][0]


def test_remove_deletes_the_tag_but_never_a_record(db: Database, caller: Caller) -> None:
    ref = service.save(db, caller, body="残る本文", tags=["消す", "残す"])["ref"]
    tagmod.alias(db, caller, alias_text="delete me", tag="消す")
    done = tagmod.remove(db, PERSON, name="消す")
    assert done["records_untagged"] == 1
    assert _tags(db, ref) == {"残す"} and service.get(db, caller, ref=ref)["body"] == "残る本文"
    assert tagmod.resolve_id(db.conn, "delete me") is None
    with pytest.raises(EmlekError) as info:
        tagmod.remove(db, PERSON, name="消す")
    assert info.value.code is ErrorCode.NOT_FOUND


def test_the_ai_cannot_merge_or_remove(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="a", tags=["甲", "乙"])
    for channel in (Channel.MCP, Channel.MCP_READONLY):
        mcp = Caller(channel, interactive=True, pin_verified=True)
        with pytest.raises(EmlekError) as info:
            tagmod.merge(db, mcp, old="甲", new="乙")
        assert info.value.code is ErrorCode.NOT_PERMITTED
        with pytest.raises(EmlekError):
            tagmod.remove(db, mcp, name="甲")
    with pytest.raises(EmlekError) as info:  # a person without the PIN is not enough
        tagmod.merge(db, Caller(Channel.CLI, interactive=True), old="甲", new="乙")
    assert info.value.code is ErrorCode.NOT_PERMITTED
    with pytest.raises(EmlekError):  # nor read-only callers for the writing tools
        tagmod.link(db, Caller(Channel.MCP_READONLY), parent="甲", child="乙")


def test_audit_finds_duplicates_and_thin_tags(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="a", tags=["Tokyo", "Tokyoo-x"], allow_new=["Tokyoo-x"])
    for i in range(5):
        service.save(db, caller, body=f"b{i}", tags=["常用"])
    report = tagmod.audit(db, caller)
    assert report["records"] == 6 and report["records_with_tags"] == 6
    assert report["coverage_percent"] == 100.0
    assert ["Tokyo", "Tokyoo-x"] in report["possible_duplicates"]
    assert "Tokyo" in report["used_once"] and "常用" in report["too_common"]


def _read(folder: Path) -> list[dict[str, object]]:
    lines = (folder / "export.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_an_export_carries_the_tags_and_checks_them(
    db: Database, caller: Caller, tmp_path: Path
) -> None:
    service.save(db, caller, body="京都で抹茶 #旅行", tags=["抹茶"])
    tagmod.alias(db, caller, alias_text="matcha", tag="抹茶")
    tagmod.link(db, caller, parent="旅行", child="抹茶")
    folder = Path(export_all(db, Caller(Channel.CLI), tmp_path / "out")["folder"])
    verify_export(folder)
    items = _read(folder)
    kinds = [str(i["type"]) for i in items]
    for kind in ("tag", "record_tag", "tag_link", "tag_alias", "tag_event"):
        assert kind in kinds
    header = items[0]["counts"]
    assert isinstance(header, dict) and header["record_tag"] == 2 and header["tag_alias"] == 1
    assert all("body_norm" not in i for i in items)


def test_excluding_high_leaves_out_tags_only_those_records_used(
    db: Database, caller: Caller, tmp_path: Path
) -> None:
    service.save(db, caller, body="ふつう", tags=["公開"])
    secret = service.save(db, caller, body="秘密", tags=["非公開の話題"])["ref"]
    service.set_sensitivity(db, PERSON, ref=secret, level="high")
    folder = Path(
        export_all(db, Caller(Channel.CLI), tmp_path / "out", exclude_high=True)["folder"]
    )
    verify_export(folder)
    text = (folder / "export.jsonl").read_text(encoding="utf-8")
    assert "公開" in text and "非公開の話題" not in text
    full = Path(export_all(db, Caller(Channel.CLI), tmp_path / "out2")["folder"])
    assert "非公開の話題" in (full / "export.jsonl").read_text(encoding="utf-8")


def test_reindex_rebuilds_the_tag_index(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="a", tags=[{"name": "抹茶", "description": "お茶、緑茶"}])
    db.conn.execute("DELETE FROM tags_fts")
    assert not tagmod.find(db, caller, text="緑茶")["results"]
    search.reindex(db, caller)
    assert tagmod.find(db, caller, text="緑茶")["results"][0]["name"] == "抹茶"
