"""M4 extras: stats, the doctor backup check and the zero-result language hint."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from emlek.core import search, service
from emlek.core.backup import create_backup
from emlek.core.db import Database
from emlek.core.doctor import run_checks
from emlek.core.permissions import Caller, Channel
from emlek.core.stats import stats

Saver = Callable[..., dict[str, Any]]
CLI = Caller(Channel.CLI)


def test_stats_counts_and_ranges(db: Database, save_at: Saver) -> None:
    empty = stats(db, CLI)
    assert empty["records"] == 0 and empty["event_dates"] == {"first": None, "last": None}
    save_at("一つ目", created_at="2026-02-01T00:00:00.000Z", event_time="2026-01-05")
    save_at("二つ目", created_at="2026-03-01T00:00:00.000Z", event_time="2026-11")
    save_at("三つ目", created_at="2026-04-01T00:00:00.000Z", kind="inference")
    db.conn.execute("UPDATE records SET hidden = 1 WHERE id = 3")
    result = stats(db, CLI)
    assert (result["records"], result["hidden_records"], result["revisions"]) == (2, 1, 3)
    assert result["revisions_by_kind"] == {"original": 2, "inference": 1}
    assert result["event_dates"] == {"first": "2026-01-05", "last": "2026-11-30"}
    assert result["saved_between"]["first"].startswith("2026-02-01")
    assert result["search_index_ok"] is True
    assert result["last_backup_at"] is None
    assert "body" not in json.dumps(result)  # counts only, never content


def test_readonly_channel_may_read_stats(db: Database) -> None:
    assert stats(db, Caller(Channel.MCP_READONLY))["records"] == 0


def _statuses(data_dir: Path) -> dict[str, str]:
    return {c["name"]: c["status"] for c in run_checks(CLI, data_dir)["checks"]}


def test_doctor_tracks_backup_age(db: Database, data_dir: Path, tmp_path: Path) -> None:
    assert _statuses(data_dir)["backup"] == "warn"  # none yet
    create_backup(db, CLI, tmp_path / "bk", data_dir)
    assert _statuses(data_dir)["backup"] == "ok"
    db.conn.execute(
        "UPDATE meta SET value = '2020-01-01T00:00:00.000Z' WHERE key = 'last_backup_at'"
    )
    assert _statuses(data_dir)["backup"] == "warn"  # too old


def test_zero_results_carry_a_language_hint(db: Database) -> None:
    for text in ("今日は京都へ行った", "Went to Kyoto today", "今天去了京都"):
        service.save(db, CLI, body=text)
    miss = search.search(db, CLI, query="存在しない")
    assert miss["total"] == 0 and len(miss["hints"]) == 1
    hint = miss["hints"][0]
    assert "英文字母" in hint and "日文假名" not in hint  # only the scripts not yet tried
    latin = search.search(db, CLI, query="nothing")["hints"][0]
    assert "日文假名" in latin and "平假名" in latin and "英文字母" not in latin
    both = search.search(db, CLI, query="OR 存在しない OR nothing".replace("OR ", "", 1))["hints"][
        0
    ]
    assert "涵蓋" in both  # every script of the library was tried: do not ask for more languages
    assert search.search(db, CLI, query="京都")["hints"] == []  # only when nothing was found
    assert search.search(db, CLI)["hints"] == []  # browsing without a query never nags


def test_hint_names_only_scripts_that_exist(db: Database) -> None:
    service.save(db, CLI, body="plain english text only")
    hint = search.search(db, CLI, query="missing")["hints"][0]
    assert "日文假名" not in hint and "漢字" not in hint  # scripts the library lacks stay unnamed


@pytest.mark.slow
def test_cli_stats_and_backup_end_to_end(data_dir: Path, tmp_path: Path) -> None:
    import subprocess
    import sys

    base = [sys.executable, "-m", "emlek", "--data-dir", str(data_dir), "--json"]
    subprocess.run([*base, "save", "--text", "CLI 経由の記録"], check=True, capture_output=True)
    backup = subprocess.run(
        [*base, "backup", "--to", str(tmp_path / "bk")], check=True, capture_output=True
    )
    assert json.loads(backup.stdout.decode("utf-8"))["result"]["records"] == 1
    shown = subprocess.run([*base, "stats"], check=True, capture_output=True)
    result = json.loads(shown.stdout.decode("utf-8"))["result"]
    assert result["records"] == 1 and result["last_backup_at"]
    exported = subprocess.run(
        [*base, "export", "--out", str(tmp_path / "ex")], check=True, capture_output=True
    )
    folder = Path(json.loads(exported.stdout.decode("utf-8"))["result"]["folder"])
    assert (folder / "export.jsonl").is_file()
