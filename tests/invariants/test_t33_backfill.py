"""T33: older records get the existing tags by their literal name, only after a preview, and the
rule's work can be undone without touching what a person or an AI chose."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from emlek.config import load_config
from emlek.core import search, service, versions
from emlek.core import tags as tagmod
from emlek.core.db import Database, load_migrations
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.export import export_all, verify_export
from emlek.core.permissions import Caller, Channel

PERSON = Caller(Channel.CLI, interactive=True)
SCRIPT = Caller(Channel.CLI, interactive=False)


def _tag(db: Database, caller: Caller, name: str, kind: str = "place", **kw: Any) -> None:
    ref = service.save(
        db, caller, body=f"vocabulary {name}", tags=[{"name": name, "type": kind}], allow_new=[name]
    )
    assert ref["tags"] == [name]
    del kw


def _pad(db: Database, caller: Caller, count: int = 12) -> None:
    """Neutral records, so that a tag is never on most of the vault by accident."""
    for i in range(count):
        service.save(db, caller, body=f"天気の記録 {i}")


def _added_by(db: Database, ref: str) -> set[str]:
    rows = db.conn.execute("SELECT added_by FROM record_tags WHERE record_id = ?", (int(ref[1:]),))
    return {r[0] for r in rows}


def test_the_table_accepts_the_new_source_and_keeps_old_rows(tmp_path: Path) -> None:
    old = Database.open(tmp_path / "old.db", must_exist=False, migrations=load_migrations()[:5])
    caller = Caller(Channel.CLI)
    service.save(old, caller, body="古い記録", tags=["旅行"])
    old.close()
    db = Database.open(tmp_path / "old.db")
    try:
        assert db.user_version == len(load_migrations())
        assert db.conn.execute("SELECT added_by FROM record_tags").fetchall() == [("ai",)]
        db.conn.execute(
            "INSERT INTO record_tags (record_id, tag_id, added_by, added_at)"
            " VALUES (1, (SELECT id FROM tags WHERE name_key = '待辦'), 'rule', 'x')"
        )
        with pytest.raises(Exception, match="CHECK"):
            db.conn.execute(
                "INSERT INTO record_tags (record_id, tag_id, added_by, added_at)"
                " VALUES (1, (SELECT id FROM tags WHERE name_key = '截止'), 'robot', 'x')"
            )
    finally:
        db.close()


def test_a_preview_shows_what_would_be_added_and_changes_nothing(
    db: Database, caller: Caller
) -> None:
    _pad(db, caller)
    _tag(db, caller, "京都")
    tagmod.alias(db, caller, alias_text="kyoto", tag="京都")
    old = service.save(db, caller, body="去年は京都で抹茶を飲んだ")["ref"]
    english = service.save(db, caller, body="A short Kyoto trip")["ref"]
    service.save(db, caller, body="大阪でたこ焼き")
    before = db.conn.execute("SELECT count(*) FROM record_tags").fetchone()[0]
    plan = tagmod.backfill_plan(db, SCRIPT)
    item = next(p for p in plan["plan"] if p["tag"] == "京都")
    assert item["records"] == 2 and {s["ref"] for s in item["samples"]} == {old, english}
    assert plan["new_links"] == 2
    assert db.conn.execute("SELECT count(*) FROM record_tags").fetchone()[0] == before


def test_applying_needs_a_person_and_marks_the_source_as_rule(db: Database, caller: Caller) -> None:
    _pad(db, caller)
    _tag(db, caller, "京都")
    old = service.save(db, caller, body="京都で散歩")["ref"]
    with pytest.raises(EmlekError) as info:
        tagmod.backfill_apply(db, SCRIPT)
    assert info.value.code is ErrorCode.NOT_PERMITTED
    for channel in (Channel.MCP, Channel.MCP_READONLY):
        with pytest.raises(EmlekError):
            tagmod.backfill_apply(db, Caller(channel, interactive=True))
    assert _added_by(db, old) == set()

    done = tagmod.backfill_apply(db, PERSON)
    assert done["new_links"] == 1 and _added_by(db, old) == {"rule"}
    found = search.search(db, caller, tags=["京都"], limit=100)
    assert old in {r["ref"] for r in found["results"]}
    assert tagmod.backfill_apply(db, PERSON)["new_links"] == 0  # nothing left to add
    actions = [r[0] for r in db.conn.execute("SELECT action FROM tag_events")]
    assert "tag_backfill" in actions


def test_status_and_emotion_tags_and_one_character_names_are_not_backfilled(
    db: Database, caller: Caller
) -> None:
    service.save(db, caller, body="x", tags=[{"name": "焦慮", "type": "emotion"}])
    service.save(db, caller, body="y", tags=[{"name": "京", "type": "place"}])
    service.save(db, caller, body="待辦は焦慮と京都の話")
    plan = tagmod.backfill_plan(db, SCRIPT)
    reasons = {s["tag"]: s["reason"] for s in plan["skipped"]}
    assert "待辦" in reasons and "焦慮" in reasons and "京" in reasons
    assert plan["new_links"] == 0


def test_a_name_inside_a_longer_tag_name_is_not_matched(db: Database, caller: Caller) -> None:
    _pad(db, caller)
    _tag(db, caller, "京都")
    _tag(db, caller, "東京都")
    only_tokyo = service.save(db, caller, body="東京都で会議があった")["ref"]
    kyoto = service.save(db, caller, body="京都へ行った")["ref"]
    both = service.save(db, caller, body="東京都のあと京都にも寄った")["ref"]
    plan = {p["tag"]: set(p["record_ids"]) for p in tagmod.backfill_plan(db, SCRIPT)["plan"]}
    assert int(kyoto[1:]) in plan["京都"] and int(both[1:]) in plan["京都"]
    assert int(only_tokyo[1:]) not in plan["京都"]
    assert int(only_tokyo[1:]) in plan["東京都"]


def test_a_tag_that_would_land_on_most_records_is_skipped(db: Database, caller: Caller) -> None:
    _tag(db, caller, "メモ", "topic")
    for i in range(6):
        service.save(db, caller, body=f"メモ {i}")
    plan = tagmod.backfill_plan(db, SCRIPT)
    assert [s["tag"] for s in plan["skipped"] if "區辨力" in s["reason"]] == ["メモ"]
    assert not [p for p in plan["plan"] if p["tag"] == "メモ"]


def test_hidden_records_are_left_alone_and_only_limits_the_tags(
    db: Database, caller: Caller
) -> None:
    _pad(db, caller)
    _tag(db, caller, "京都")
    _tag(db, caller, "大阪")
    hidden = service.save(db, caller, body="京都の隠した話")["ref"]
    service.save(db, caller, body="京都の話と大阪の話")
    versions.hide(db, caller, ref=hidden)
    plan = tagmod.backfill_plan(db, SCRIPT, only=["京都"])
    assert [p["tag"] for p in plan["plan"]] == ["京都"] and plan["plan"][0]["records"] == 1


def test_undo_removes_only_what_a_rule_added(db: Database, caller: Caller) -> None:
    _pad(db, caller)
    _tag(db, caller, "京都")
    mine = service.save(db, caller, body="京都 #旅行", tags=["旅行メモ"])["ref"]
    other = service.save(db, caller, body="京都でラーメン")["ref"]
    tagmod.backfill_apply(db, PERSON)
    assert _added_by(db, other) == {"rule"} and "rule" in _added_by(db, mine)
    with pytest.raises(EmlekError):
        tagmod.backfill_undo(db, SCRIPT)
    removed = tagmod.backfill_undo(db, PERSON)["removed"]
    assert removed == 2
    assert _added_by(db, other) == set() and "rule" not in _added_by(db, mine)
    assert {t["name"] for t in tagmod.tags_of(db.conn, int(mine[1:]))} >= {"旅行", "旅行メモ"}


def test_untagged_records_can_be_listed(db: Database, caller: Caller) -> None:
    tagged = service.save(db, caller, body="京都", tags=["旅行"])["ref"]
    bare = service.save(db, caller, body="何も付いていない")["ref"]
    got = search.search(db, caller, untagged=True, limit=100)
    refs = {r["ref"] for r in got["results"]}
    assert bare in refs and tagged not in refs


def test_exports_still_verify_with_rule_tags(db: Database, caller: Caller, tmp_path: Path) -> None:
    _pad(db, caller)
    _tag(db, caller, "京都")
    service.save(db, caller, body="京都で散歩")
    tagmod.backfill_apply(db, PERSON)
    folder = Path(export_all(db, Caller(Channel.CLI), tmp_path / "out")["folder"])
    verify_export(folder)
    assert '"added_by":"rule"' in (folder / "export.jsonl").read_text(encoding="utf-8")


def test_the_command_line_previews_freely_but_will_not_apply_without_a_person(
    data_dir: Path, db: Database, caller: Caller
) -> None:
    _tag(db, caller, "京都")
    service.save(db, caller, body="京都で散歩")
    db.close()

    def run(*args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [sys.executable, "-m", "emlek", "--data-dir", str(data_dir), "tags", "backfill", *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )

    preview = run()
    assert preview.returncode == 0 and "京都".encode() in preview.stdout
    assert run("--apply").returncode == 3
    assert run("--undo").returncode == 3
    check = Database.open(load_config(data_dir).db_path)
    try:
        assert (
            check.conn.execute("SELECT count(*) FROM record_tags WHERE added_by='rule'").fetchone()[
                0
            ]
            == 0
        )
    finally:
        check.close()
