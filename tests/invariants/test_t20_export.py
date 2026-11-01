"""T20: the export is lossless, readable without emlek, and never half-written."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from emlek.core import export as export_module
from emlek.core import service
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.export import FORMAT_VERSION, export_all, verify_export
from emlek.core.permissions import Caller, Channel

Saver = Callable[..., dict[str, Any]]
CLI = Caller(Channel.CLI)
TEXTS = ["京都で抹茶 😀", "CRLF\r\nと LF\n", "Ｆｕｌｌｗｉｄｔｈ", "é combining", "plain"]


@pytest.fixture
def populated(db: Database, save_at: Saver) -> Database:
    for i, text in enumerate(TEXTS):
        save_at(
            text,
            created_at=f"2026-0{i + 1}-10T09:00:00.000Z",
            event_time=f"2026-0{i + 1}-10" if i % 2 == 0 else None,
            source="手動" if i == 0 else None,
        )
    return db


def _read(folder: Path) -> list[dict[str, Any]]:
    text = (folder / "export.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.split("\n") if line]


def test_export_matches_the_database_exactly(populated: Database, tmp_path: Path) -> None:
    result = export_all(populated, CLI, tmp_path / "out")
    folder = Path(result["folder"])
    verify_export(folder)
    items = _read(folder)
    header = items[0]
    assert header["format_version"] == FORMAT_VERSION and header["counts"] == {
        "record": 5,
        "revision": 5,
    }
    revisions = {i["id"]: i for i in items if i["type"] == "revision"}
    for row in populated.conn.execute(
        "SELECT id, record_id, version_no, body, kind, created_at, event_time,"
        " event_time_precision, source FROM revisions"
    ):
        exported = revisions[row[0]]
        assert (
            exported["record_id"],
            exported["version_no"],
            exported["body"],
            exported["kind"],
            exported["created_at"],
            exported["event_time"],
            exported["event_time_precision"],
            exported["source"],
        ) == row[1:]
    assert all("body_norm" not in i for i in items)
    records = {i["id"]: i for i in items if i["type"] == "record"}
    assert set(records) == {1, 2, 3, 4, 5}


def test_files_are_plain_utf8_with_unix_line_endings(populated: Database, tmp_path: Path) -> None:
    folder = Path(export_all(populated, CLI, tmp_path / "out")["folder"])
    raw = (folder / "export.jsonl").read_bytes()
    assert b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf")
    raw.decode("utf-8")
    markdown = (folder / "markdown" / "r000002.md").read_text(encoding="utf-8")
    assert "# r2" in markdown and "## r2.v1 · original" in markdown and "LF" in markdown
    first = (folder / "markdown" / "r000001.md").read_text(encoding="utf-8")
    assert "京都で抹茶 😀" in first and "來源：手動" in first


def test_hidden_records_are_exported_with_their_flag(populated: Database, tmp_path: Path) -> None:
    populated.conn.execute("UPDATE records SET hidden = 1, hidden_at = 'now' WHERE id = 3")
    items = _read(Path(export_all(populated, CLI, tmp_path / "out")["folder"]))
    record = next(i for i in items if i["type"] == "record" and i["id"] == 3)
    assert record["hidden"] == 1


def test_high_sensitivity_can_be_left_out(populated: Database, tmp_path: Path) -> None:
    populated.conn.execute("UPDATE records SET sensitivity = 'high' WHERE id = 2")
    kept = Path(export_all(populated, CLI, tmp_path / "a")["folder"])
    assert any(i["type"] == "revision" and i["record_id"] == 2 for i in _read(kept))
    result = export_all(populated, CLI, tmp_path / "b", exclude_high=True)
    folder = Path(result["folder"])
    verify_export(folder)
    items = _read(folder)
    assert items[0]["counts"] == {"record": 4, "revision": 4}
    assert items[0]["excluded_high_records"] == 1
    assert not any(
        i.get("record_id") == 2 or i.get("id") == 2 for i in items if i["type"] != "meta"
    )
    assert not (folder / "markdown" / "r000002.md").exists()
    assert "CRLF" not in (folder / "export.jsonl").read_text(encoding="utf-8")


def test_export_does_not_change_the_vault_and_can_repeat(
    populated: Database, tmp_path: Path
) -> None:
    before = populated.conn.execute("SELECT count(*), max(id) FROM revisions").fetchone()
    first = export_all(populated, CLI, tmp_path / "out")
    second = export_all(populated, CLI, tmp_path / "out")
    assert first["folder"] != second["folder"]
    assert populated.conn.execute("SELECT count(*), max(id) FROM revisions").fetchone() == before


def test_a_failed_export_leaves_nothing_behind(
    populated: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(export_module, "_write_markdown", boom)
    with pytest.raises(RuntimeError):
        export_all(populated, CLI, tmp_path / "out")
    assert list((tmp_path / "out").iterdir()) == []


def test_mcp_cannot_export(populated: Database, tmp_path: Path) -> None:
    for channel in (Channel.MCP, Channel.MCP_READONLY):
        with pytest.raises(EmlekError) as info:
            export_all(populated, Caller(channel), tmp_path / "out")
        assert info.value.code is ErrorCode.NOT_PERMITTED


def test_verification_catches_a_damaged_export(populated: Database, tmp_path: Path) -> None:
    folder = Path(export_all(populated, CLI, tmp_path / "out")["folder"])
    path = folder / "export.jsonl"
    lines = path.read_text(encoding="utf-8").split("\n")
    path.write_text("\n".join(lines[:-2]) + "\n", encoding="utf-8")  # drop the last revision
    with pytest.raises(EmlekError):
        verify_export(folder)
    (folder / "export.jsonl").unlink()
    with pytest.raises(EmlekError) as info:
        verify_export(folder)
    assert info.value.code is ErrorCode.NOT_FOUND


def test_empty_vault_exports_cleanly(db: Database, tmp_path: Path) -> None:
    folder = Path(export_all(db, CLI, tmp_path / "out")["folder"])
    summary = verify_export(folder)
    assert summary["counts"].get("record", 0) == 0
    assert service.KINDS  # sanity: module imported
