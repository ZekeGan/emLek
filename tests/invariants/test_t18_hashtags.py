"""T18: tag sources are recorded, `#tags` come from the user's own words, text never changes."""

from __future__ import annotations

from pathlib import Path

import pytest

from emlek.core import service
from emlek.core import tags as tagmod
from emlek.core.db import Database
from emlek.core.errors import EmlekError
from emlek.core.permissions import Caller, Channel


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("今日は #京都 に行った", ["京都"]),
        ("#start of line と #末尾", ["start", "末尾"]),
        ("全角スペース　#タグ、そして（#括弧）。", ["タグ", "括弧"]),
        ("C# と F# は言語", []),
        ("https://example.com/page#section を見た", []),
        ("# 見出し と #1 と #2024", []),
        ("#京都 #京都 #KYOTO #kyoto", ["京都", "KYOTO"]),
        ("#under_score と #dash-ed", ["under_score", "dash-ed"]),
        ("", []),
    ],
)
def test_hashtag_parsing(text: str, names: list[str]) -> None:
    assert tagmod.parse_hashtags(text) == names


def _added_by(db: Database, ref: str) -> dict[str, str]:
    record_id = int(ref[1:])
    return {
        row[0]: row[1]
        for row in db.conn.execute(
            "SELECT t.name, rt.added_by FROM record_tags rt JOIN tags t ON t.id = rt.tag_id"
            " WHERE rt.record_id = ?",
            (record_id,),
        )
    }


def test_typed_hashtags_are_the_users_and_the_text_is_untouched(
    db: Database, caller: Caller
) -> None:
    body = "今日は #京都 で #抹茶 を飲んだ"
    done = service.save(db, caller, body=body, tags=["お茶"])
    assert service.get(db, caller, ref=done["ref"])["body"] == body  # byte for byte
    mark = _added_by(db, done["ref"])
    assert mark["京都"] == "user" and mark["抹茶"] == "user"
    assert mark["お茶"] == "ai"  # a script is not a person at a terminal


def test_who_counts_as_user_depends_on_the_entry_not_on_a_claim(db: Database) -> None:
    from emlek.core import notice

    notice.acknowledge(db.conn)
    person = Caller(Channel.CLI, interactive=True)
    script = Caller(Channel.CLI, interactive=False)
    over_mcp = Caller(Channel.MCP, interactive=True)
    for who, expected in ((person, "user"), (script, "ai"), (over_mcp, "ai")):
        ref = service.save(db, who, body="メモ", tags=[f"標籤{expected}{who.channel}"])["ref"]
        assert set(_added_by(db, ref).values()) == {expected}


def test_only_the_users_original_text_is_scanned_for_hashtags(db: Database, caller: Caller) -> None:
    summary = service.save(db, caller, body="要約 #まとめ", kind="ai_summary")
    assert summary["tags"] == []
    original = service.save(db, caller, body="本文 #まとめ")
    assert original["tags"] == ["まとめ"]


def test_amend_reads_hashtags_in_the_new_version(db: Database, caller: Caller) -> None:
    ref = service.save(db, caller, body="最初 #一")["ref"]
    service.amend(db, caller, ref=ref, body="改訂 #二")
    assert set(_added_by(db, ref)) == {"一", "二"}  # tags belong to the record, not a version


def test_a_bad_hashtag_never_blocks_saving_the_text(db: Database, caller: Caller) -> None:
    body = "番号 #a0912345678 と #ふつう"  # the number itself is personal data: the user says yes
    with pytest.raises(EmlekError) as asked:
        service.save(db, caller, body=body)
    token = asked.value.data["notice_token"]
    done = service.save(db, caller, body=body, notice_token=token)
    assert done["tags"] == ["ふつう"] and done["hashtags_skipped"] == ["a0912345678"]
    assert service.get(db, caller, ref=done["ref"])["body"] == body


def test_tags_and_text_are_saved_together_or_not_at_all(
    db: Database, caller: Caller, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode() -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(service, "_before_commit", explode)
    with pytest.raises(RuntimeError):
        service.save(db, caller, body="書けない #幻", tags=["幻の標籤"])
    monkeypatch.undo()
    assert db.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 0
    names = {r[0] for r in db.conn.execute("SELECT name FROM tags")}
    assert "幻" not in names and "幻の標籤" not in names


def test_every_tag_change_leaves_an_event_without_text(
    db: Database, caller: Caller, data_dir: Path
) -> None:
    ref = service.save(db, caller, body="秘密の本文ではない #旅行")["ref"]
    tagmod.alias(db, caller, alias_text="trip", tag="旅行")
    rows = db.conn.execute(
        "SELECT action, detail, record_id FROM tag_events ORDER BY id"
    ).fetchall()
    actions = [r[0] for r in rows]
    assert {"tag_create", "tag_add", "tag_alias"} <= set(actions)
    assert all("本文" not in r[1] for r in rows)
    assert [r[2] for r in rows if r[0] == "tag_add"] == [int(ref[1:])]
