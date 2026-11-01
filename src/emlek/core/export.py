"""Lossless export (JSONL, format v1) plus a readable Markdown copy.

The JSONL file can be read without emlek or SQLite. The derived search copy (body_norm) is not
exported; it is rebuilt from the text.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from emlek import __version__
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, require
from emlek.core.timeutil import utc_now_iso

FORMAT_VERSION = 1

_RECORD_COLUMNS = ("id", "created_at", "hidden", "hidden_at", "sensitivity")
_REVISION_COLUMNS = (
    "id",
    "record_id",
    "version_no",
    "body",
    "kind",
    "created_at",
    "event_time",
    "event_time_precision",
    "source",
)


def _line(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"


def _stamp() -> str:
    return utc_now_iso().replace("-", "").replace(":", "").replace(".", "")


def _record_filter(exclude_high: bool) -> str:
    return "sensitivity != 'high'" if exclude_high else "1"


def export_all(
    db: Database, caller: Caller, out_dir: Path, *, exclude_high: bool = False
) -> dict[str, Any]:
    require(caller, "export")
    folder = out_dir / f"export-{_stamp()}"
    (folder / "markdown").mkdir(parents=True)
    keep = _record_filter(exclude_high)
    conn = db.conn
    records = conn.execute(f"SELECT count(*) FROM records WHERE {keep}").fetchone()[0]
    revisions = conn.execute(
        f"SELECT count(*) FROM revisions WHERE record_id IN (SELECT id FROM records WHERE {keep})"
    ).fetchone()[0]
    excluded = conn.execute(
        "SELECT count(*) FROM records WHERE sensitivity = 'high'" if exclude_high else "SELECT 0"
    ).fetchone()[0]
    header = {
        "type": "header",
        "format_version": FORMAT_VERSION,
        "schema_version": db.user_version,
        "emlek_version": __version__,
        "exported_at": utc_now_iso(),
        "counts": {"record": records, "revision": revisions},
        "excluded_high_records": excluded,
    }
    jsonl = folder / "export.jsonl"
    try:
        _write_jsonl(db, jsonl, header, keep)
        _write_markdown(db, folder / "markdown", keep)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)  # never leave a half-written export
        raise
    return {
        "folder": str(folder),
        "records": records,
        "revisions": revisions,
        "excluded_high_records": excluded,
        "jsonl_bytes": jsonl.stat().st_size,
    }


def _write_jsonl(db: Database, jsonl: Path, header: dict[str, Any], keep: str) -> None:
    conn = db.conn
    with jsonl.open("w", encoding="utf-8", newline="\n") as out:
        out.write(_line(header))
        for key, value in conn.execute("SELECT key, value FROM meta ORDER BY key"):
            out.write(_line({"type": "meta", "key": key, "value": value}))
        columns = ", ".join(_RECORD_COLUMNS)
        for row in conn.execute(f"SELECT {columns} FROM records WHERE {keep} ORDER BY id"):
            out.write(_line({"type": "record", **dict(zip(_RECORD_COLUMNS, row, strict=True))}))
        columns = ", ".join(f"r.{c}" for c in _REVISION_COLUMNS)
        for row in conn.execute(
            f"SELECT {columns} FROM revisions r JOIN records rec ON rec.id = r.record_id"
            f" WHERE {keep} ORDER BY r.record_id, r.version_no"
        ):
            out.write(_line({"type": "revision", **dict(zip(_REVISION_COLUMNS, row, strict=True))}))


def _write_markdown(db: Database, folder: Path, keep: str) -> None:
    current: int | None = None
    handle = None
    try:
        for row in db.conn.execute(
            "SELECT r.record_id, r.version_no, r.kind, r.body, r.event_time,"
            " r.event_time_precision, r.source, r.created_at, rec.created_at, rec.hidden,"
            f" rec.sensitivity FROM revisions r JOIN records rec ON rec.id = r.record_id"
            f" WHERE {keep} ORDER BY r.record_id, r.version_no"
        ):
            record_id, version, kind, body, event, precision, source, saved, first, hidden, sens = (
                row
            )
            if record_id != current:
                if handle:
                    handle.close()
                handle = (folder / f"r{record_id:06d}.md").open("w", encoding="utf-8", newline="\n")
                handle.write(
                    f"# r{record_id}\n\n- 存入時間：{first}\n- 隱藏：{'是' if hidden else '否'}\n"
                    f"- 敏感度：{sens}\n"
                )
                current = record_id
            else:
                assert handle is not None
                handle.write("\n---\n")
            assert handle is not None
            handle.write(f"\n## r{record_id}.v{version} · {kind}\n\n- 版本存入：{saved}\n")
            if event:
                handle.write(f"- 事件時間：{event}（{precision}）\n")
            if source:
                handle.write(f"- 來源：{source}\n")
            handle.write(f"\n{body}\n")
    finally:
        if handle:
            handle.close()


def verify_export(folder: Path) -> dict[str, Any]:
    """Check an export folder against its own header. Raises EmlekError if it is inconsistent."""
    path = folder / "export.jsonl"
    if not path.is_file():
        raise EmlekError(ErrorCode.NOT_FOUND, "找不到 export.jsonl")
    counts: dict[str, int] = {}
    record_ids: set[int] = set()
    header: dict[str, Any] | None = None
    with path.open(encoding="utf-8", newline="") as source:
        for number, line in enumerate(source, 1):
            if not line.endswith("\n"):
                raise EmlekError(ErrorCode.INVALID_INPUT, f"第 {number} 行沒有換行結尾")
            item = json.loads(line)
            kind = item["type"]
            if number == 1:
                if kind != "header" or item["format_version"] != FORMAT_VERSION:
                    raise EmlekError(ErrorCode.INVALID_INPUT, "標頭格式不符")
                header = item
                continue
            counts[kind] = counts.get(kind, 0) + 1
            if kind == "record":
                record_ids.add(item["id"])
            elif kind == "revision":
                if item["record_id"] not in record_ids:
                    raise EmlekError(ErrorCode.INVALID_INPUT, "版本找不到所屬的記錄")
                if "body_norm" in item:
                    raise EmlekError(ErrorCode.INVALID_INPUT, "不應匯出衍生欄位 body_norm")
    assert header is not None
    if counts.get("record", 0) != header["counts"]["record"]:
        raise EmlekError(ErrorCode.INVALID_INPUT, "記錄筆數與標頭不符")
    if counts.get("revision", 0) != header["counts"]["revision"]:
        raise EmlekError(ErrorCode.INVALID_INPUT, "版本筆數與標頭不符")
    markdown = len(list((folder / "markdown").glob("r*.md")))
    if markdown != counts.get("record", 0) and counts.get("revision", 0) > 0:
        raise EmlekError(ErrorCode.INVALID_INPUT, "Markdown 檔數與記錄數不符")
    return {"header": header, "counts": counts, "markdown_files": markdown}
