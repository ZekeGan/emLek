"""One consent covers personal auto-recording; credentials are never written."""

from __future__ import annotations

from pathlib import Path

import pytest

from emlek.core import auto, notice, service, tokens
from emlek.core.db import Database, load_migrations
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel

AI = Caller(Channel.MCP)
PERSON = Caller(Channel.CLI, interactive=True, pin_verified=True)


def test_first_personal_auto_save_requires_one_global_consent(db: Database) -> None:
    assert auto.policy(db, AI)["enabled"] is True
    assert {c["mode"] for c in auto.policy(db, AI)["categories"]} == {"auto"}
    body = "今天中午吃了拉麵"
    with pytest.raises(EmlekError) as asked:
        service.save(db, AI, body=body, source="auto:生活點滴")
    assert asked.value.code is ErrorCode.NOT_PERMITTED
    assert "ask_user" not in asked.value.data
    assert db.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 0
    with pytest.raises(EmlekError) as terms:
        notice.start(db, AI)
    notice.start(db, AI, notice_token=terms.value.data["notice_token"])
    saved = service.save(db, AI, body=body, source="auto:生活點滴")
    assert saved["marker"] == "◆ emLek｜r1.✔️"
    assert not notice.is_enabled(db.conn)
    assert (
        service.save(db, AI, body="我覺得陪伴很重要", source="auto:思考")["marker"]
        == "◆ emLek｜r2.✔️"
    )
    assert (
        service.save(db, AI, body="合成電話 0912-345-678", source="auto:生活點滴")["sensitivity"]
        == "medium"
    )


@pytest.mark.parametrize("channel", [Channel.CLI, Channel.MCP])
def test_credentials_are_refused_even_with_a_confirmation_token(
    db: Database, channel: Channel
) -> None:
    before = db.conn.execute("SELECT count(*) FROM confirm_tokens").fetchone()[0]
    with pytest.raises(EmlekError) as denied:
        service.save(db, Caller(channel), body="密碼：abc12345", confirm_token="not-an-override")
    assert denied.value.code is ErrorCode.NOT_PERMITTED
    assert "ask_user" not in denied.value.data
    assert db.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 0
    assert db.conn.execute("SELECT count(*) FROM confirm_tokens").fetchone()[0] == before


def test_reenabled_consent_covers_plain_personal_content_again(db: Database) -> None:
    notice.acknowledge(db.conn)
    notice.enable_medium(db, PERSON)
    with pytest.raises(EmlekError) as asked:
        service.save(db, AI, body="今天去散步", source="auto:生活點滴")
    assert asked.value.code is ErrorCode.NOT_PERMITTED


def test_amend_refuses_credentials_and_returns_the_note_number(db: Database) -> None:
    saved = service.save(db, Caller(Channel.CLI), body="測試筆記")
    notice.acknowledge(db.conn)
    assert saved["marker"] == "◆ emLek｜r1.✔️"
    with pytest.raises(EmlekError) as denied:
        service.amend(db, AI, ref="r1", body="密碼：abc12345")
    assert denied.value.code is ErrorCode.NOT_PERMITTED
    assert service.get(db, AI, ref="r1")["body"] == "測試筆記"
    assert service.amend(db, AI, ref="r1", body="測試筆記補充")["marker"] == "◆ emLek｜r1.✔️"


def test_upgrade_does_not_expand_old_consent_or_reenable_a_disabled_vault(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    old = Database.open(path, must_exist=False, migrations=load_migrations()[:9])
    old.conn.execute("INSERT INTO meta(key,value) VALUES ('created_at','2026-01-01')")
    old.conn.execute("UPDATE notice_settings SET enabled=0, acknowledged_at='2026-01-01'")
    old.conn.execute("UPDATE auto_categories SET mode='off' WHERE name='工作'")
    service.save(old, Caller(Channel.CLI), body="原有筆記")
    old.close()
    upgraded = Database.open(path)
    try:
        assert notice.is_enabled(upgraded.conn)
        assert auto.policy(upgraded, AI)["enabled"] is False
        modes = {c["name"]: c["mode"] for c in auto.policy(upgraded, AI)["categories"]}
        assert modes["工作"] == "off" and modes["生活點滴"] == "auto"
        assert service.get(upgraded, AI, ref="r1")["body"] == "原有筆記"
    finally:
        upgraded.close()


def test_pending_old_notice_token_cannot_grant_broader_consent(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    body = "合成電話 0912-345-678"
    old = Database.open(path, must_exist=False, migrations=load_migrations()[:9])
    token = tokens.issue(old, "notice", tokens.content_hash("save", "", body))
    old.close()
    upgraded = Database.open(path)
    try:
        with pytest.raises(EmlekError) as denied:
            service.save(upgraded, AI, body=body, notice_token=token)
        assert denied.value.code is ErrorCode.TOKEN_INVALID
        assert notice.is_enabled(upgraded.conn)
        assert upgraded.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 0
    finally:
        upgraded.close()


@pytest.mark.parametrize("operation", ["save", "amend"])
def test_consent_reset_between_check_and_write_prevents_the_write(
    db: Database, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    service.save(db, Caller(Channel.CLI), body="原文")
    notice.acknowledge(db.conn)
    original_gate = service._sensitivity_gate

    def reset_after_check(*args: object, **kwargs: object) -> object:
        gate = original_gate(*args, **kwargs)  # type: ignore[arg-type]
        notice.enable_medium(db, PERSON)
        return gate

    monkeypatch.setattr(service, "_sensitivity_gate", reset_after_check)
    with pytest.raises(EmlekError) as denied:
        if operation == "save":
            service.save(db, AI, body="新筆記")
        else:
            service.amend(db, AI, ref="r1", body="修改原文")
    assert denied.value.code is ErrorCode.CONFLICT
    assert service.get(db, AI, ref="r1")["body"] == "原文"
    assert db.conn.execute("SELECT count(*) FROM revisions").fetchone()[0] == 1
