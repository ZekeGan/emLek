"""T14: dangerous commands need a real terminal and the PIN; phrases are read-only for the AI."""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from emlek.cli.commands import common, init, maintenance, trust
from emlek.config import load_config
from emlek.core import phrases, security, service
from emlek.core.backup import create_backup
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel

PIN = "correct horse"
PERSON = Caller(Channel.CLI, interactive=True)
NOT_A_PERSON = Caller(Channel.CLI, interactive=False)


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "KDF_N", 16)


class Console:
    """A stand-in for the person at the keyboard: answers PIN prompts from a script."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, answers: list[str], *, person: bool
    ) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []
        who = PERSON if person else NOT_A_PERSON
        for module in (common, trust, init, maintenance):
            if hasattr(module, "cli_caller"):
                monkeypatch.setattr(module, "cli_caller", lambda who=who: who)
        monkeypatch.setattr(common, "read_secret", self.read)
        monkeypatch.setattr(trust, "read_secret", self.read)

    def read(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        if not self.answers:
            raise AssertionError(f"unexpected prompt: {prompt}")
        return self.answers.pop(0)


@pytest.fixture
def console(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Console]:
    def make(*answers: str, person: bool = True) -> Console:
        return Console(monkeypatch, list(answers), person=person)

    return make


def _args(data_dir: Path, **extra: object) -> argparse.Namespace:
    return argparse.Namespace(data_dir=str(data_dir), json=False, **extra)


@pytest.fixture
def pinned(db: Database, data_dir: Path) -> Iterator[Path]:
    security.set_pin(db, data_dir, PIN)
    db.close()
    yield data_dir


def _run(cmd: list[str], data_dir: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "emlek", "--data-dir", str(data_dir), *cmd],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    "command",
    [
        ["pin", "set"],
        ["pin", "change"],
        ["pin", "reset"],
        ["phrase", "add", "save", "全部都記"],
        ["phrase", "set", "1", "--disable"],
        ["phrase", "remove", "1"],
        ["notice", "enable", "medium"],
        ["sensitivity", "set", "r1", "high"],
    ],
)
def test_without_a_terminal_the_dangerous_commands_are_refused(
    data_dir: Path, command: list[str]
) -> None:
    assert _run(command, data_dir).returncode == 3


def test_reading_phrases_and_notice_status_needs_no_gate(data_dir: Path) -> None:
    listing = _run(["phrase", "list"], data_dir)
    assert listing.returncode == 0 and "完全刪除".encode() in listing.stdout
    assert _run(["notice", "status"], data_dir).returncode == 0


def test_a_script_is_never_asked_for_a_pin(pinned: Path, console: Callable[..., Console]) -> None:
    keys = console(person=False)
    with pytest.raises(EmlekError) as info:
        common.authorize(_args(pinned), "phrase_add")
    assert info.value.code is ErrorCode.NOT_PERMITTED and keys.prompts == []


def test_no_pin_set_means_no_prompt_and_no_access(
    data_dir: Path, console: Callable[..., Console]
) -> None:
    keys = console()
    with pytest.raises(EmlekError) as info:
        common.authorize(_args(data_dir), "phrase_add")
    assert "pin set" in info.value.message and keys.prompts == []


def test_the_right_pin_opens_the_gate_and_the_wrong_one_does_not(
    pinned: Path, console: Callable[..., Console]
) -> None:
    keys = console("wrong guess", PIN)
    with pytest.raises(EmlekError):
        common.authorize(_args(pinned), "phrase_add")
    caller = common.authorize(_args(pinned), "phrase_add")
    assert caller.pin_verified and caller.interactive and len(keys.prompts) == 2


def test_after_five_mistakes_the_gate_stops_asking(
    pinned: Path, console: Callable[..., Console]
) -> None:
    keys = console(*["bad guess"] * 5)
    for _ in range(5):
        with pytest.raises(EmlekError):
            common.authorize(_args(pinned), "phrase_add")
    with pytest.raises(EmlekError) as info:
        common.authorize(_args(pinned), "phrase_add")
    assert "鎖定" in info.value.message and len(keys.prompts) == 5  # no sixth prompt


def test_phrase_commands_go_through_the_gate(pinned: Path, console: Callable[..., Console]) -> None:
    console(PIN)
    out = trust.run_phrase(_args(pinned, phrase_command="add", kind="save", text="記下來"))
    assert "已新增語句" in out.text
    console("not the pin")
    with pytest.raises(EmlekError):
        trust.run_phrase(_args(pinned, phrase_command="remove", id=1))
    listing = trust.run_phrase(_args(pinned, phrase_command="list", kind=None))
    assert "記下來" in listing.text and "記住" in listing.text  # the removal never happened


def test_phrases_are_validated_and_purge_can_be_switched_off(db: Database) -> None:
    gate = Caller(Channel.CLI, interactive=True, pin_verified=True)
    got = phrases.list_phrases(db, Caller(Channel.CLI))
    assert got["purge_enabled"] and [p["text"] for p in got["phrases"]["purge"]] == ["完全刪除"]
    with pytest.raises(EmlekError) as info:
        phrases.add(db, gate, kind="purge", text="ＦＵＬＬ　ＤＥＬＥＴＥ".replace("　", " "))
        phrases.add(db, gate, kind="purge", text="full delete")  # same after NFKC + casefold
    assert info.value.code is ErrorCode.CONFLICT
    for kind, text in (("nope", "x"), ("save", ""), ("save", "x" * 101), ("save", "a\x07b")):
        with pytest.raises(EmlekError) as bad:
            phrases.add(db, gate, kind=kind, text=text)
        assert bad.value.code is ErrorCode.INVALID_INPUT
    for item in phrases.list_phrases(db, gate, kind="purge")["phrases"]["purge"]:
        phrases.update(db, gate, phrase_id=item["id"], enabled=False)
    assert phrases.list_phrases(db, gate)["purge_enabled"] is False
    assert (
        phrases.list_phrases(db, Caller(Channel.MCP_READONLY), enabled_only=True)["phrases"][
            "purge"
        ]
        == []
    )
    with pytest.raises(EmlekError):
        phrases.update(db, gate, phrase_id=9999, enabled=True)


def test_the_ai_can_read_phrases_but_not_change_them(db: Database) -> None:
    for channel in (Channel.MCP, Channel.MCP_READONLY):
        mcp = Caller(channel, interactive=True, pin_verified=True)
        assert phrases.list_phrases(db, mcp, enabled_only=True)["phrases"]["save"]
        with pytest.raises(EmlekError) as info:
            phrases.add(db, mcp, kind="save", text="全部都存")
        assert info.value.code is ErrorCode.NOT_PERMITTED
        with pytest.raises(EmlekError) as info:
            phrases.remove(db, mcp, phrase_id=1)
        assert info.value.code is ErrorCode.NOT_PERMITTED


def test_restore_needs_the_pin_and_a_wrong_one_changes_nothing(
    db: Database,
    pinned: Path,
    tmp_path: Path,
    console: Callable[..., Console],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    again = Database.open(load_config(pinned).db_path)
    service.save(again, Caller(Channel.CLI), body="バックアップする記録")
    backup = create_backup(again, Caller(Channel.CLI), tmp_path / "backups", pinned)["file"]
    service.save(again, Caller(Channel.CLI), body="あとから増えた記録")
    again.close()

    console("a wrong pin")
    monkeypatch.setattr(sys, "stdin", io.StringIO("是\n"))
    with pytest.raises(EmlekError):
        maintenance.run_restore(_args(pinned, file=backup))
    check = Database.open(load_config(pinned).db_path)
    assert check.conn.execute("SELECT count(*) FROM records").fetchone()[0] == 2
    check.close()

    console(PIN)
    monkeypatch.setattr(sys, "stdin", io.StringIO("是\n"))
    out = maintenance.run_restore(_args(pinned, file=backup))
    assert "已還原：1 筆記錄" in out.text


def test_init_in_a_terminal_sets_the_pin_and_shows_the_recovery_code(
    tmp_path: Path, console: Callable[..., Console]
) -> None:
    target = tmp_path / "fresh"
    console(PIN, PIN)
    out = init.run(_args(target))
    assert out.result["pin_state"] == security.SET and "復原碼" in out.text
    db = Database.open(load_config(target).db_path)
    try:
        security.verify_pin(db, target, PIN)
    finally:
        db.close()


def test_init_without_a_terminal_leaves_the_pin_for_later(
    tmp_path: Path, console: Callable[..., Console]
) -> None:
    keys = console(person=False)
    out = init.run(_args(tmp_path / "scripted"))
    assert out.result["pin_state"] == security.UNSET and "emlek pin set" in out.text
    assert keys.prompts == []


def test_mismatched_new_pins_are_rejected(data_dir: Path, console: Callable[..., Console]) -> None:
    console("first choice", "second choice")
    with pytest.raises(EmlekError) as info:
        trust.run_pin_set(_args(data_dir))
    assert info.value.code is ErrorCode.INVALID_INPUT
    db = Database.open(load_config(data_dir).db_path)
    try:
        assert security.state(db.conn, data_dir) == security.UNSET
    finally:
        db.close()


def test_sensitivity_and_notice_commands_use_the_gate(
    pinned: Path, console: Callable[..., Console]
) -> None:
    db = Database.open(load_config(pinned).db_path)
    ref = service.save(db, Caller(Channel.CLI), body="ふつうの記録")["ref"]
    db.close()
    console(PIN)
    out = trust.run_sensitivity(_args(pinned, ref=ref, level="high"))
    assert "none → high" in out.text
    console(PIN)
    assert (
        "重新開啟" in trust.run_notice(_args(pinned, notice_command="enable", level="medium")).text
    )


def test_filtering_the_list_does_not_change_whether_purge_is_on(db: Database) -> None:
    only_save = phrases.list_phrases(db, Caller(Channel.CLI), kind="save")
    assert only_save["phrases"]["purge"] == [] and only_save["purge_enabled"] is True
