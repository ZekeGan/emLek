"""T27: confirmation tokens are one-time, bound to the text, short-lived and never leak."""

from __future__ import annotations

import json
import logging
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from emlek.config import load_config
from emlek.core import notice, search, service, tokens
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel

SECRET = "網站密碼：abc12345"
PHONE = "小明的電話 0912-345-678"
PERSON = Caller(Channel.CLI, interactive=True, pin_verified=True)


def _asked(db: Database, caller: Caller, body: str, **kwargs: Any) -> dict[str, Any]:
    with pytest.raises(EmlekError) as info:
        service.save(db, caller, body=body, **kwargs)
    assert info.value.code is ErrorCode.NEEDS_CONFIRMATION
    return info.value.data


def _count(db: Database) -> int:
    return int(db.conn.execute("SELECT count(*) FROM records").fetchone()[0])


def test_high_risk_text_is_always_refused_without_a_confirmation_token(
    db: Database, caller: Caller
) -> None:
    with pytest.raises(EmlekError) as info:
        service.save(db, caller, body=SECRET)
    assert info.value.code is ErrorCode.NOT_PERMITTED
    assert "abc12345" not in json.dumps(info.value.data)
    assert _count(db) == 0
    assert db.conn.execute("SELECT count(*) FROM confirm_tokens").fetchone()[0] == 0


def test_a_token_works_once(db: Database, caller: Caller) -> None:
    data = _asked(db, caller, PHONE)
    service.save(db, caller, body=PHONE, notice_token=data["notice_token"])
    notice.enable_medium(db, PERSON)
    with pytest.raises(EmlekError) as info:
        service.save(db, caller, body=PHONE, notice_token=data["notice_token"])
    assert info.value.code is ErrorCode.TOKEN_INVALID
    assert _count(db) == 1


def test_a_token_is_bound_to_the_exact_text_and_the_operation(db: Database, caller: Caller) -> None:
    data = _asked(db, caller, PHONE)
    with pytest.raises(EmlekError) as info:
        service.save(db, caller, body=PHONE + "。", notice_token=data["notice_token"])
    assert info.value.code is ErrorCode.TOKEN_INVALID
    ref = service.save(db, caller, body="普通のメモ")["ref"]
    with pytest.raises(EmlekError) as info:  # a save token cannot authorise an amend
        service.amend(db, caller, ref=ref, body=PHONE, notice_token=data["notice_token"])
    assert info.value.code is ErrorCode.TOKEN_INVALID
    assert service.get(db, caller, ref=ref)["version"] == 1


def test_a_token_expires_after_ten_minutes(
    db: Database, caller: Caller, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _asked(db, caller, PHONE)
    later = tokens._now() + timedelta(seconds=tokens.TTL_SECONDS + 1)
    monkeypatch.setattr(tokens, "_now", lambda: later)
    with pytest.raises(EmlekError) as info:
        service.save(db, caller, body=PHONE, notice_token=data["notice_token"])
    assert info.value.code is ErrorCode.TOKEN_INVALID


def test_the_kinds_are_not_interchangeable(db: Database, caller: Caller) -> None:
    notice_data = _asked(db, caller, PHONE)
    with pytest.raises(EmlekError) as info:  # a notice token cannot confirm a secret
        service.save(db, caller, body=PHONE, confirm_token=notice_data["notice_token"])
    assert info.value.code is ErrorCode.NEEDS_CONFIRMATION  # the wrong parameter counts as absent
    confirm = tokens.issue(db, "confirm", tokens.content_hash("save", "", PHONE))
    with pytest.raises(EmlekError) as info:
        service.save(db, caller, body=PHONE, notice_token=confirm)
    assert info.value.code is ErrorCode.TOKEN_INVALID


def test_every_refusal_reads_the_same(db: Database, caller: Caller) -> None:
    good = _asked(db, caller, PHONE)["notice_token"]
    messages = set()
    for token in ("nonsense", good + "x", "y" * 22):
        with pytest.raises(EmlekError) as info:
            service.save(db, caller, body=PHONE, notice_token=token)
        messages.add((info.value.code, info.value.message))
    assert len(messages) == 1


def test_a_failed_write_does_not_burn_the_token(
    db: Database, caller: Caller, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _asked(db, caller, PHONE)

    def explode() -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(service, "_before_commit", explode)
    with pytest.raises(RuntimeError):
        service.save(db, caller, body=PHONE, notice_token=data["notice_token"])
    assert _count(db) == 0
    monkeypatch.undo()
    service.save(db, caller, body=PHONE, notice_token=data["notice_token"])
    assert _count(db) == 1


def test_two_processes_racing_for_one_token_only_one_wins(data_dir: Path) -> None:
    path = load_config(data_dir).db_path
    first = Database.open(path)
    try:
        data = _asked(first, Caller(Channel.CLI), PHONE)
    finally:
        first.close()
    outcomes: list[str] = []
    gate = threading.Barrier(2)

    def attempt() -> None:
        conn = Database.open(path)
        try:
            gate.wait()
            try:
                service.save(
                    conn, Caller(Channel.CLI), body=PHONE, notice_token=data["notice_token"]
                )
                outcomes.append("saved")
            except EmlekError as error:
                outcomes.append(error.code.value)
        finally:
            conn.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["TOKEN_INVALID", "saved"]


def test_tokens_are_stored_hashed_and_never_logged(
    db: Database, caller: Caller, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="emlek"):
        data = _asked(db, caller, PHONE)
        service.save(db, caller, body=PHONE, notice_token=data["notice_token"])
    token = data["notice_token"]
    assert token not in caplog.text and "0912" not in caplog.text
    stored = json.dumps(db.conn.execute("SELECT * FROM confirm_tokens").fetchall())
    assert token not in stored


def test_medium_content_asks_once_then_stays_quiet_until_reenabled(
    db: Database, caller: Caller
) -> None:
    data = _asked(db, caller, PHONE)
    assert data["state"] == "needs_notice" and data["categories"] == ["phone"]
    service.save(db, caller, body=PHONE, notice_token=data["notice_token"])
    assert notice.status(db, Caller(Channel.CLI))["medium_notice_enabled"] is False

    assert service.save(db, caller, body="別の人 0987-654-321")["sensitivity"] == "medium"
    notice.enable_medium(db, PERSON)
    again = _asked(db, caller, "また別の人 0911-222-333")
    assert again["state"] == "needs_notice"


def test_high_wins_when_both_appear(db: Database, caller: Caller) -> None:
    with pytest.raises(EmlekError) as info:
        service.save(db, caller, body=PHONE + "\n" + SECRET)
    assert info.value.code is ErrorCode.NOT_PERMITTED


def test_a_declared_level_can_raise_but_never_lower(db: Database, caller: Caller) -> None:
    for body, level in (("ふつうのメモ", "high"), (SECRET, "none")):
        with pytest.raises(EmlekError) as denied:
            service.save(db, caller, body=body, sensitivity=level)
        assert denied.value.code is ErrorCode.NOT_PERMITTED
    with pytest.raises(EmlekError) as info:
        service.save(db, caller, body="ふつう", sensitivity="secret")
    assert info.value.code is ErrorCode.INVALID_INPUT


def test_amend_goes_through_the_same_gate_and_only_raises_the_record(
    db: Database, caller: Caller
) -> None:
    ref = service.save(db, caller, body="最初のメモ")["ref"]
    with pytest.raises(EmlekError) as info:
        service.amend(db, caller, ref=ref, body=PHONE)
    data = info.value.data
    done = service.amend(db, caller, ref=ref, body=PHONE, notice_token=data["notice_token"])
    assert done["sensitivity"] == "medium"
    plain = service.amend(db, caller, ref=ref, body="秘密を消した版")
    assert plain["sensitivity"] == "medium"  # a record keeps the highest level of any version


def test_only_a_person_with_the_pin_can_set_a_level_directly(db: Database, caller: Caller) -> None:
    ref = service.save(db, caller, body="ふつうのメモ")["ref"]
    with pytest.raises(EmlekError) as info:
        service.set_sensitivity(db, caller, ref=ref, level="high")
    assert info.value.code is ErrorCode.NOT_PERMITTED
    assert service.set_sensitivity(db, PERSON, ref=ref, level="high")["sensitivity"] == "high"
    assert service.set_sensitivity(db, PERSON, ref=ref, level="none")["previous"] == "high"


def test_reads_respect_the_sensitivity_cap_everywhere(db: Database, caller: Caller) -> None:
    quiet = service.save(db, caller, body="共通語 普通")["ref"]
    loud = service.save(db, caller, body="共通語 秘密")["ref"]
    service.set_sensitivity(db, PERSON, ref=loud, level="high")
    service.save(db, caller, body="共通語 つづき", links=[{"ref": loud, "relation": "supports"}])
    with pytest.raises(EmlekError) as info:
        service.get(db, caller, ref=loud, max_sensitivity="medium")
    assert info.value.code is ErrorCode.NOT_PERMITTED
    assert "秘密" not in info.value.message
    assert service.get(db, caller, ref=quiet, max_sensitivity="medium")["body"] == "共通語 普通"

    reply = service.save(db, caller, body="共通語 返信", links=[{"ref": quiet}])["ref"]
    service.set_sensitivity(db, PERSON, ref=reply, level="high")
    seen = service.get(db, caller, ref=quiet, max_sensitivity="medium")
    assert reply not in [
        i["ref"] for i in seen["linked_from"]
    ]  # the hidden-by-cap record is not named
    assert reply in [i["ref"] for i in service.get(db, caller, ref=quiet)["linked_from"]]
    found = search.search(db, caller, query="共通語", max_sensitivity="medium")
    assert found["withheld"] == 2 and loud not in {r["ref"] for r in found["results"]}


def test_the_refusal_carries_the_exact_question_to_ask(db: Database, caller: Caller) -> None:
    from pathlib import Path

    medium = _asked(db, caller, PHONE)
    assert medium["ask_user"] == service.ASK_MEDIUM
    rules = (Path(__file__).resolve().parents[2] / "docs" / "AGENT_RULES.md").read_text("utf-8")
    assert service.ASK_MEDIUM in rules
    assert "0912" not in json.dumps(medium)
