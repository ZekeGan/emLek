"""T23: only a person at a terminal with the PIN can purge; the AI side gets metadata only; a
"no" or an unclear answer deletes nothing; cleanup and restore guard what they touch."""

from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

import pytest

from emlek.cli.commands import common, importcmd, maintenance, purgecmd
from emlek.core import backup, cleanup, purge, security, service
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel

PIN = "123456"
PERSON = Caller(Channel.CLI, interactive=True, pin_verified=True)
TEXT = "GATED-LIMA 只有終端機看得到的內容"


@pytest.fixture(autouse=True)
def fast_kdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "KDF_N", 16)


@pytest.fixture
def pinned(db: Database, data_dir: Path) -> Path:
    security.set_pin(db, data_dir, PIN)
    return data_dir


def _terminal(
    monkeypatch: pytest.MonkeyPatch, *, typed: str, pins: list[str], person: bool = True
) -> None:
    who = Caller(Channel.CLI, interactive=person)
    for module in (common, purgecmd, maintenance, importcmd):
        if hasattr(module, "cli_caller"):
            monkeypatch.setattr(module, "cli_caller", lambda who=who: who)
    answers = list(pins)
    monkeypatch.setattr(common, "read_secret", lambda prompt="": answers.pop(0))
    monkeypatch.setattr(sys, "stdin", io.StringIO(typed))


def _args(data_dir: Path, **extra: object) -> argparse.Namespace:
    values: dict[str, object] = {"refs": ["r1"], "finish": False, "apply": False, **extra}
    return argparse.Namespace(data_dir=str(data_dir), json=False, **values)


@pytest.fixture
def saved(db: Database) -> str:
    return str(service.save(db, PERSON, body=TEXT)["ref"]).split(".")[0]


def test_ai_side_gets_metadata_only_and_cannot_purge(db: Database, saved: str) -> None:
    for channel in (Channel.MCP, Channel.MCP_READONLY):
        caller = Caller(channel, interactive=True, pin_verified=True)
        with pytest.raises(EmlekError) as info:
            purge.purge(db, caller, [saved], fingerprint="x", data_dir=Path("."), backup_dir=None)
        assert info.value.code is ErrorCode.NOT_PERMITTED
    with pytest.raises(EmlekError):
        purge.preview(db, Caller(Channel.MCP_READONLY), [saved])
    shown = purge.preview(db, Caller(Channel.MCP), [saved], with_text=True)
    assert "GATED" not in str(shown) and "excerpt" not in str(shown) and "fingerprint" not in shown
    assert shown["purge_enabled"] is True and shown["revisions"] == 1


@pytest.mark.parametrize(
    "caller",
    [Caller(Channel.CLI), Caller(Channel.CLI, interactive=True)],
    ids=["no terminal", "terminal without PIN"],
)
def test_a_script_or_an_unverified_terminal_cannot_purge(
    db: Database, saved: str, caller: Caller
) -> None:
    with pytest.raises(EmlekError) as info:
        purge.purge(db, caller, [saved], fingerprint="x", data_dir=Path("."), backup_dir=None)
    assert info.value.code is ErrorCode.NOT_PERMITTED
    assert service.get(db, PERSON, ref=saved)["body"] == TEXT


def test_the_cli_refuses_without_a_terminal_and_never_asks_for_a_pin(
    pinned: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _terminal(monkeypatch, typed="是\n", pins=[], person=False)
    with pytest.raises(EmlekError) as info:
        purgecmd.run(_args(pinned))
    assert info.value.code is ErrorCode.NOT_PERMITTED


def test_a_wrong_pin_stops_before_anything_is_shown(
    pinned: Path, saved: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _terminal(monkeypatch, typed="是\n", pins=["000000"])
    with pytest.raises(EmlekError):
        purgecmd.run(_args(pinned, refs=[saved]))
    assert "GATED" not in capsys.readouterr().err


@pytest.mark.parametrize("answer", ["否\n", "\n", "好\n", "yes\n", "是的\n", ""])
def test_anything_but_a_clear_yes_deletes_nothing(
    pinned: Path,
    db: Database,
    saved: str,
    monkeypatch: pytest.MonkeyPatch,
    answer: str,
) -> None:
    _terminal(monkeypatch, typed=answer, pins=[PIN])
    with pytest.raises(EmlekError) as info:
        purgecmd.run(_args(pinned, refs=[saved]))
    assert info.value.code is ErrorCode.NEEDS_CONFIRMATION
    assert service.get(db, PERSON, ref=saved)["body"] == TEXT


def test_the_fixed_question_the_preview_and_then_the_purge(
    pinned: Path,
    db: Database,
    saved: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _terminal(monkeypatch, typed="是\n", pins=[PIN])
    output = purgecmd.run(_args(pinned, refs=[saved]))
    shown = capsys.readouterr().err
    assert purgecmd.QUESTION in shown and "GATED-LIMA" in shown  # the person sees the excerpt
    assert "完全刪除 1 筆記錄" in output.text and "到不了的地方" in output.text
    with pytest.raises(EmlekError) as info:
        service.get(db, PERSON, ref=saved)
    assert info.value.code is ErrorCode.NOT_FOUND


def test_turning_the_purge_phrases_off_closes_the_cli_too(
    pinned: Path, db: Database, saved: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    db.conn.execute("UPDATE phrases SET enabled = 0 WHERE kind = 'purge'")
    _terminal(monkeypatch, typed="是\n", pins=[PIN])
    with pytest.raises(EmlekError) as info:
        purgecmd.run(_args(pinned, refs=[saved]))
    assert info.value.code is ErrorCode.NOT_PERMITTED
    assert service.get(db, PERSON, ref=saved)["body"] == TEXT


def test_only_the_purge_module_can_switch_the_immutability_triggers_off() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "emlek"
    users = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if re.search(r"\.purge_mode\(", path.read_text(encoding="utf-8"))
    }
    assert users == {"core/purge.py"}


# --- cleanup ---------------------------------------------------------------------------------


def _leftovers(data_dir: Path) -> list[Path]:
    old = data_dir / "pre-migration"
    old.mkdir(exist_ok=True)
    files = [old / "pre-migration-v1.db", data_dir / "emlek.db.before-restore-x"]
    for file in files:
        file.write_bytes(b"old copy")
    return files


def test_cleanup_previews_by_default_and_only_lists_emlek_leftovers(
    db: Database, data_dir: Path
) -> None:
    files = _leftovers(data_dir)
    (data_dir / "exports").mkdir()
    export = data_dir / "exports" / "export.jsonl"
    export.write_bytes(b"keep me")
    shown = cleanup.preview(Caller(Channel.CLI), data_dir)
    assert sorted(shown["files"]) == sorted(str(f) for f in files)
    assert all(f.exists() for f in files) and export.exists()
    assert db.path.exists()


def test_cleanup_refuses_without_a_newer_good_backup_and_then_works(
    db: Database, data_dir: Path, tmp_path: Path
) -> None:
    files = _leftovers(data_dir)
    service.save(db, PERSON, body="CLEAN-MIKE 內容")
    backups = tmp_path / "bk"
    with pytest.raises(EmlekError) as info:
        cleanup.apply(db, PERSON, data_dir, backups, lambda: "")
    assert info.value.code is ErrorCode.CONFLICT and all(f.exists() for f in files)
    made = backup.create_backup(db, PERSON, backups, data_dir)
    result = cleanup.apply(db, PERSON, data_dir, backups, lambda: "")
    assert result["removed"] == 2 and not any(f.exists() for f in files)
    assert db.path.exists() and Path(str(made["file"])).exists()
    assert service.get(db, PERSON, ref="r1")["body"] == "CLEAN-MIKE 內容"


def test_cleanup_needs_a_terminal_and_the_pin(db: Database, data_dir: Path, tmp_path: Path) -> None:
    for caller in (Caller(Channel.CLI), Caller(Channel.CLI, interactive=True)):
        with pytest.raises(EmlekError) as info:
            cleanup.apply(db, caller, data_dir, tmp_path, lambda: "")
        assert info.value.code is ErrorCode.NOT_PERMITTED


# --- restore after a purge -------------------------------------------------------------------


def test_restore_warns_when_the_backup_is_older_than_a_purge_and_keeps_the_audit(
    db: Database, data_dir: Path, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    first = service.save(db, PERSON, body="BEFORE-NOVEMBER 備份時還在的內容")
    made = backup.create_backup(db, PERSON, tmp_path / "bk", data_dir)
    backup_file = Path(str(made["file"]))
    assert backup.purges_missing_from(db.path, backup_file) == 0
    purge.purge(
        db,
        PERSON,
        [str(first["ref"]).split(".")[0]],
        fingerprint=str(
            purge.preview(db, PERSON, [str(first["ref"]).split(".")[0]], with_text=True)[
                "fingerprint"
            ]
        ),
        data_dir=data_dir,
        backup_dir=None,
    )
    assert backup.purges_missing_from(db.path, backup_file) == 1
    db.close()
    backup.restore_backup(PERSON, data_dir, backup_file)
    restored = Database.open(db.path)
    request.addfinalizer(restored.close)
    assert restored.conn.execute("SELECT count(*) FROM purge_log").fetchone()[0] == 1
    fresh = service.save(restored, PERSON, body="AFTER-RESTORE 還原後的新記錄")
    assert fresh["ref"] != first["ref"]  # the purged id is not handed out again


def test_a_purge_shows_up_in_stats_as_a_count_and_a_time_only(
    db: Database, data_dir: Path, saved: str
) -> None:
    from emlek.core import stats

    before = stats.stats(db, PERSON)["purges"]
    assert before == {"count": 0, "last_at": None}
    purge.purge(
        db,
        PERSON,
        [saved],
        fingerprint=str(purge.preview(db, PERSON, [saved], with_text=True)["fingerprint"]),
        data_dir=data_dir,
        backup_dir=None,
    )
    after = stats.stats(db, PERSON)["purges"]
    assert after["count"] == 1 and after["last_at"]
