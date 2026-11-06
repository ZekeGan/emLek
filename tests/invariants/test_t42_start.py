"""Terms belong to explicit start, never an ordinary save or conversation."""

from __future__ import annotations

import pytest

from emlek.core import notice, service, tokens
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel

AI = Caller(Channel.MCP)


def test_only_start_returns_terms_and_accepting_it_never_saves_old_chat(db: Database) -> None:
    with pytest.raises(EmlekError) as blocked:
        service.save(db, AI, body="啟用前的生活敘述", source="auto:生活點滴")
    assert blocked.value.code is ErrorCode.NOT_PERMITTED
    assert "ask_user" not in blocked.value.data
    assert db.conn.execute("SELECT count(*) FROM confirm_tokens").fetchone()[0] == 0
    with pytest.raises(EmlekError) as asked:
        notice.start(db, AI)
    assert asked.value.code is ErrorCode.NEEDS_CONFIRMATION
    assert asked.value.data["ask_user"] == notice.TERMS
    assert notice.is_enabled(db.conn)
    notice.start(db, AI, notice_token=asked.value.data["notice_token"])
    assert not notice.is_enabled(db.conn)
    assert db.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 0
    assert service.save(db, AI, body="啟用後的生活敘述", source="auto:生活點滴")["ref"] == "r1"
    assert notice.start(db, AI)["started"] is True


def test_start_is_not_available_to_readonly_ai(db: Database) -> None:
    with pytest.raises(EmlekError) as denied:
        notice.start(db, Caller(Channel.MCP_READONLY))
    assert denied.value.code is ErrorCode.NOT_PERMITTED


def test_old_save_tokens_cannot_activate_start_and_start_token_cannot_save(db: Database) -> None:
    old = tokens.issue(db, "notice", tokens.content_hash("save", "", "電話 0912-345-678"))
    with pytest.raises(EmlekError) as denied:
        notice.start(db, AI, notice_token=old)
    assert denied.value.code is ErrorCode.TOKEN_INVALID
    with pytest.raises(EmlekError) as asked:
        notice.start(db, AI)
    token = asked.value.data["notice_token"]
    with pytest.raises(EmlekError) as denied:
        service.save(db, AI, body="今天散步", notice_token=token)
    assert denied.value.code is ErrorCode.TOKEN_INVALID
    assert notice.is_enabled(db.conn)
    assert db.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 0


def test_declining_or_not_replying_keeps_auto_inactive(db: Database) -> None:
    with pytest.raises(EmlekError):
        notice.start(db, AI)
    # No token is submitted on decline; later conversation must not produce more terms.
    for body in ("今天吃麵", "電話 0912-345-678"):
        with pytest.raises(EmlekError) as denied:
            service.save(db, AI, body=body)
        assert denied.value.code is ErrorCode.NOT_PERMITTED
        assert "ask_user" not in denied.value.data
    assert notice.is_enabled(db.conn)
