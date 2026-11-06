"""T39: auto-record policy (D96). The core
refuses an automatic save for any category that is not `auto`, for highest-risk content, for an
inference, and past the daily limit; personal data follows the one-time notice. Every record can be
taken back (hidden, never purged)."""

from __future__ import annotations

import argparse
import io
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from emlek.cli.commands import autocmd, common
from emlek.config import load_config
from emlek.core import auto, notice, security, service, versions
from emlek.core import sensitivity as scanner
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel
from emlek.mcp_server import server

PIN = "123456"
PERSON = Caller(Channel.CLI, interactive=True, pin_verified=True)
AI = Caller(Channel.MCP)
CATEGORY = "生活點滴"
SOURCE = f"auto:{CATEGORY}"
MEAL = "今天中午在京都吃了拉麵"


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "KDF_N", 16)


@pytest.fixture
def on(db: Database) -> Database:
    auto.set_enabled(db, PERSON, on=True)
    auto.set_mode(db, PERSON, name=CATEGORY, mode="auto")
    notice.acknowledge(db.conn)
    return db


def _save(
    db: Database, body: str = MEAL, *, kind: str = "original", sensitivity: str | None = None
) -> dict[str, object]:
    return service.save(db, AI, body=body, source=SOURCE, kind=kind, sensitivity=sensitivity)


def _refused(
    db: Database, body: str = MEAL, *, kind: str = "original", sensitivity: str | None = None
) -> EmlekError:
    with pytest.raises(EmlekError) as info:
        _save(db, body, kind=kind, sensitivity=sensitivity)
    assert info.value.code is ErrorCode.NOT_PERMITTED
    return info.value


def test_new_vault_is_ready_and_explicitly_disabling_it_blocks_auto(db: Database) -> None:
    seen = auto.policy(db, AI)
    assert seen["enabled"] is True
    assert {c["mode"] for c in seen["categories"]} == {"auto"}
    assert len(seen["categories"]) == 5
    auto.set_enabled(db, PERSON, on=False)
    _refused(db)
    assert service.save(db, Caller(Channel.CLI), body=MEAL)["ref"] == "r1"


def test_a_category_that_is_not_auto_is_refused(db: Database) -> None:
    auto.set_enabled(db, PERSON, on=True)
    auto.set_mode(db, PERSON, name=CATEGORY, mode="ask")
    _refused(db)  # enabled but the category is still "ask"
    auto.set_mode(db, PERSON, name=CATEGORY, mode="auto")
    notice.acknowledge(db.conn)
    saved = _save(db)
    assert saved["marker"] == "◆ emLek｜r1.✔️"
    auto.set_mode(db, PERSON, name=CATEGORY, mode="off")
    _refused(db)
    with pytest.raises(EmlekError):
        service.save(db, AI, body=MEAL, source="auto:不存在的類別")


def test_an_automatic_save_is_marked_and_the_marker_is_ready_to_paste(on: Database) -> None:
    saved = _save(on)
    assert saved["marker"] == "◆ emLek｜r1.✔️"
    assert service.get(on, AI, ref="r1")["source"] == SOURCE
    assert service.save(on, AI, body="手動存的")["marker"] == "◆ emLek｜r2.✔️"


def test_inferences_and_highest_risk_text_are_never_saved_automatically(on: Database) -> None:
    _refused(on, kind="inference")
    for body in ("密碼：abc12345", "卡號 4111 1111 1111 1111"):
        assert scanner.assess(body, "none")[0] == "high"  # the premise: the scan reacts
        refused = _refused(on, body)
        assert "改為詢問" not in refused.message
    _refused(on, sensitivity="high")  # the AI declaring it is enough to stop an auto save
    assert on.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 0
    assert on.conn.execute("SELECT count(*) FROM confirm_tokens").fetchone()[0] == 0
    assert _save(on, kind="ai_summary", body="整理：今天吃了拉麵")["ref"] == "r1"


def test_personal_data_flows_only_after_explicit_start(on: Database) -> None:
    from emlek.core import notice

    notice.enable_medium(on, PERSON)
    phone = "朋友小明的電話 0912-345-678"
    assert scanner.assess(phone, "none")[0] == "medium"
    with pytest.raises(EmlekError) as asked:  # the first time: the one-time notice
        _save(on, phone)
    assert asked.value.code is ErrorCode.NOT_PERMITTED
    assert on.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 0
    with pytest.raises(EmlekError) as terms:
        notice.start(on, AI)
    notice.start(on, AI, notice_token=terms.value.data["notice_token"])
    first = service.save(on, AI, body=phone, source=SOURCE)
    assert first["marker"] == "◆ emLek｜r1.✔️" and first["sensitivity"] == "medium"
    assert notice.is_enabled(on.conn) is False
    # afterwards personal data is saved without asking, whether the scan or the AI marked it
    assert _save(on, "同事王小華 0987-654-321")["ref"] == "r2"
    assert _save(on, "我的朋友阿明住在大阪", sensitivity="medium")["ref"] == "r3"
    # taking the permission back needs a person with the PIN, and asks again
    notice.enable_medium(on, PERSON)
    with pytest.raises(EmlekError) as again:
        _save(on, "另一個電話 0911-222-333")
    assert again.value.code is ErrorCode.NOT_PERMITTED


def test_the_daily_limit_stops_a_runaway_loop(on: Database) -> None:
    auto.set_limit(on, PERSON, limit=2)
    _save(on, "第一件")
    _save(on, "第二件")
    assert "上限" in _refused(on, "第三件").message
    assert auto.policy(on, AI)["used_24h"] == 2
    auto.set_limit(on, PERSON, limit=3)
    assert _save(on, "第三件")["ref"] == "r3"
    for bad in (0, 201, True):
        with pytest.raises(EmlekError):
            auto.set_limit(on, PERSON, limit=bad)


def _attempts(db: Database, who: Caller) -> list[Callable[[], object]]:
    return [
        lambda: auto.set_enabled(db, who, on=True),
        lambda: auto.set_mode(db, who, name=CATEGORY, mode="auto"),
        lambda: auto.add_category(db, who, name="新類別"),
        lambda: auto.remove_category(db, who, name=CATEGORY),
        lambda: auto.set_limit(db, who, limit=5),
        lambda: auto.exclude(db, who, keyword="secret-project"),
    ]


def test_only_a_person_with_the_pin_can_change_the_policy(db: Database) -> None:
    for caller in (AI, Caller(Channel.CLI), Caller(Channel.CLI, interactive=True)):
        for attempt in _attempts(db, caller):
            with pytest.raises(EmlekError) as info:
                attempt()
            assert info.value.code is ErrorCode.NOT_PERMITTED
    assert auto.policy(db, AI)["enabled"] is True


def test_the_read_only_server_cannot_even_read_the_policy(db: Database) -> None:
    with pytest.raises(EmlekError) as info:
        auto.policy(db, Caller(Channel.MCP_READONLY))
    assert info.value.code is ErrorCode.NOT_PERMITTED


def test_categories_exclusions_and_names(db: Database) -> None:
    auto.add_category(db, PERSON, name="旅行", description="去了哪些地方")
    with pytest.raises(EmlekError) as info:
        auto.add_category(db, PERSON, name="旅行")
    assert info.value.code is ErrorCode.CONFLICT
    for bad in ("", "x" * 21, "含:冒號", "含：冒號", "換\n行"):
        with pytest.raises(EmlekError):
            auto.add_category(db, PERSON, name=bad)
    auto.remove_category(db, PERSON, name="旅行")
    with pytest.raises(EmlekError):
        auto.remove_category(db, PERSON, name="旅行")
    auto.exclude(db, PERSON, keyword="Secret-Project")
    again = auto.exclude(db, PERSON, keyword="secret-project")  # same word, no duplicate
    assert again["excluded_projects"] == ["Secret-Project"]
    assert auto.policy(db, AI)["excluded_projects"] == ["Secret-Project"]
    assert (
        auto.exclude(db, PERSON, keyword="SECRET-PROJECT", remove=True)["excluded_projects"] == []
    )


def test_recent_lists_what_was_saved_and_marks_the_automatic_ones(on: Database) -> None:
    service.save(on, AI, body="手動存的一筆")
    _save(on, "自動存的一筆")
    everything = auto.recent(on, PERSON, days=7)["records"]
    assert [r["ref"] for r in everything] == ["r2", "r1"]
    only = auto.recent(on, PERSON, days=7, auto_only=True)["records"]
    assert [(r["ref"], r["category"]) for r in only] == [("r2", CATEGORY)]
    assert only[0]["excerpt"] == "自動存的一筆" and only[0]["hidden"] is False
    with pytest.raises(EmlekError):
        auto.recent(on, AI)  # recent is the person's view, not an AI tool


def test_taking_back_hides_and_never_purges(on: Database) -> None:
    service.save(on, AI, body="手動存的一筆")
    _save(on, "自動一")
    _save(on, "自動二")
    done = auto.hide_since(on, PERSON, since="2000-01-01")
    assert done["hidden"] == ["r2", "r3"] and done["count"] == 2
    assert service.get(on, AI, ref="r1")["body"] == "手動存的一筆"
    with pytest.raises(EmlekError) as info:
        service.get(on, AI, ref="r2")
    assert info.value.code is ErrorCode.NOT_FOUND
    versions.unhide(on, AI, ref="r2")  # recoverable
    assert service.get(on, AI, ref="r2")["body"] == "自動一"
    assert auto.hide_since(on, PERSON, since="2999-01-01")["count"] == 0
    with pytest.raises(EmlekError):
        auto.hide_since(on, PERSON, since="昨天")
    with pytest.raises(EmlekError) as denied:
        auto.hide_since(on, Caller(Channel.MCP), since="2000-01-01")
    assert denied.value.code is ErrorCode.NOT_PERMITTED


def test_amend_cannot_claim_the_automatic_source(on: Database) -> None:
    ref = str(service.save(on, AI, body="手動存的一筆")["ref"])
    with pytest.raises(EmlekError) as info:
        service.amend(on, AI, ref=ref, body="改過", source=SOURCE)
    assert info.value.code is ErrorCode.NOT_PERMITTED
    kept = _save(on)
    assert service.amend(on, AI, ref=str(kept["ref"]), body="補充")["version"] == 2


def test_opening_instructions_name_only_the_auto_categories(db: Database, data_dir: Path) -> None:
    path = load_config(data_dir).db_path
    auto.set_enabled(db, PERSON, on=False)
    for item in auto.policy(db, PERSON)["categories"]:
        auto.set_mode(db, PERSON, name=item["name"], mode="off")
    assert "自動記錄已開啟" not in server._instructions(path, "high")
    auto.set_enabled(db, PERSON, on=True)
    assert "自動記錄已開啟" not in server._instructions(path, "high")  # nothing is "auto" yet
    auto.set_mode(db, PERSON, name=CATEGORY, mode="auto")
    text = server._instructions(path, "high")
    assert '["生活點滴"]' in text and "思考" not in text
    assert "自動記錄已開啟" not in server._instructions(path, "medium", can_write=False)


# --- the terminal commands -------------------------------------------------------------------


def _terminal(monkeypatch: pytest.MonkeyPatch, *, pins: list[str], person: bool = True) -> None:
    who = Caller(Channel.CLI, interactive=person)
    for module in (common, autocmd):
        if hasattr(module, "cli_caller"):
            monkeypatch.setattr(module, "cli_caller", lambda who=who: who)
    answers = list(pins)
    monkeypatch.setattr(common, "read_secret", lambda prompt="": answers.pop(0))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))


def _args(data_dir: Path, command: str, **extra: object) -> argparse.Namespace:
    return argparse.Namespace(data_dir=str(data_dir), json=False, auto_command=command, **extra)


def test_the_cli_needs_a_terminal_and_the_pin_but_status_is_free(
    db: Database, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auto.set_enabled(db, PERSON, on=False)
    security.set_pin(db, data_dir, PIN)
    _terminal(monkeypatch, pins=[], person=False)
    assert "關閉" in autocmd.run_auto(_args(data_dir, "status")).text
    with pytest.raises(EmlekError) as info:
        autocmd.run_auto(_args(data_dir, "on"))
    assert info.value.code is ErrorCode.NOT_PERMITTED
    _terminal(monkeypatch, pins=["000000"])
    with pytest.raises(EmlekError):
        autocmd.run_auto(_args(data_dir, "on"))
    assert auto.policy(db, AI)["enabled"] is False
    _terminal(monkeypatch, pins=[PIN, PIN, PIN])
    assert "已開啟" in autocmd.run_auto(_args(data_dir, "on")).text
    assert "直接存" in autocmd.run_auto(_args(data_dir, "set", name=CATEGORY, mode="auto")).text
    assert "上限" in autocmd.run_auto(_args(data_dir, "limit", count=10)).text
    status = autocmd.run_auto(_args(data_dir, "status")).text
    assert "開啟" in status
    assert "生活點滴　啟用後直接存" in status and "思考　啟用後直接存" in status
    assert "待在對話輸入 emlek start" in status


def test_the_cli_take_back_needs_a_terminal_but_no_pin(
    on: Database, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _save(on)
    _terminal(monkeypatch, pins=[], person=False)
    with pytest.raises(EmlekError):
        autocmd.run_auto(_args(data_dir, "hide", since="2000-01-01"))
    _terminal(monkeypatch, pins=[])
    out = autocmd.run_auto(_args(data_dir, "hide", since="2000-01-01"))
    assert "已隱藏 1 筆" in out.text
    shown = autocmd.run_recent(
        argparse.Namespace(data_dir=str(data_dir), json=False, auto=True, days=7, limit=10)
    )
    assert "r1" in shown.text and "已隱藏" in shown.text and CATEGORY in shown.text
