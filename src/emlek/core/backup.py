"""Consistent backups and verified restores."""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from emlek.config import load_config
from emlek.core.db import Database, load_migrations
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, require
from emlek.core.timeutil import utc_now_iso

_REQUIRED_TABLES = {"meta", "records", "revisions"}


def _stamp() -> str:
    return utc_now_iso().replace("-", "").replace(":", "").replace(".", "")


def inspect_database(path: Path) -> dict[str, Any]:
    """Open a database file read-only and report whether it is a sound emlek vault."""
    if not path.is_file():
        raise EmlekError(ErrorCode.NOT_FOUND, "找不到備份檔")
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise EmlekError(ErrorCode.INVALID_INPUT, "這不是可讀取的資料庫檔") from exc
    try:
        try:
            check = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        except sqlite3.DatabaseError as exc:
            raise EmlekError(ErrorCode.INVALID_INPUT, "備份檔已損毀或不是 emlek 的資料庫") from exc
        if check != "ok":
            raise EmlekError(ErrorCode.INVALID_INPUT, "備份檔的完整性檢查未通過")
        if not tables >= _REQUIRED_TABLES:
            raise EmlekError(ErrorCode.INVALID_INPUT, "這不是 emlek 的備份檔")
        return {
            "schema_version": int(conn.execute("PRAGMA user_version").fetchone()[0]),
            "records": conn.execute("SELECT count(*) FROM records").fetchone()[0],
            "revisions": conn.execute("SELECT count(*) FROM revisions").fetchone()[0],
        }
    finally:
        conn.close()


def create_backup(db: Database, caller: Caller, backup_dir: Path, data_dir: Path) -> dict[str, Any]:
    require(caller, "backup")
    target_dir = backup_dir.resolve()
    if target_dir == data_dir.resolve() or data_dir.resolve() in target_dir.parents:
        raise EmlekError(ErrorCode.INVALID_INPUT, "備份資料夾不能放在資料夾裡面，請放到別的位置")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"emlek-{_stamp()}.db"
    db.backup_to(target)
    info = inspect_database(target)
    with db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_backup_at', ?)",
            (utc_now_iso(),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_backup_file', ?)",
            (target.name,),
        )
    same_drive = bool(target_dir.drive) and data_dir.resolve().drive == target_dir.drive
    return {
        "file": str(target),
        "bytes": target.stat().st_size,
        "records": info["records"],
        "revisions": info["revisions"],
        "schema_version": info["schema_version"],
        "same_drive_as_data": same_drive,
        "encrypted": False,
    }


def _sidecars(path: Path) -> list[Path]:
    return [p for p in (Path(f"{path}-wal"), Path(f"{path}-shm")) if p.exists()]


def restore_backup(caller: Caller, data_dir: Path, source: Path) -> dict[str, Any]:
    """Replace the live database with a verified backup. The old one is kept, renamed."""
    require(caller, "restore")
    config = load_config(data_dir)
    target = config.db_path
    if source.resolve() == target.resolve():
        raise EmlekError(ErrorCode.INVALID_INPUT, "備份檔不能是目前使用中的資料庫")
    info = inspect_database(source)
    latest = len(load_migrations())
    if info["schema_version"] > latest:
        raise EmlekError(ErrorCode.INVALID_INPUT, "這份備份來自較新版本的 emlek，請先升級程式")

    staged = data_dir / "emlek.db.restoring"
    for leftover in (staged, *_sidecars(staged)):
        leftover.unlink(missing_ok=True)
    shutil.copyfile(source, staged)
    try:
        upgrade = Database(staged)
        try:
            upgrade.apply_migrations(load_migrations(), data_dir / "pre-migration")
        finally:
            upgrade.close()
        verified = inspect_database(staged)
        if (verified["records"], verified["revisions"]) != (info["records"], info["revisions"]):
            raise EmlekError(ErrorCode.INTERNAL, "還原前的檢查發現筆數不一致，未做任何替換")
    except BaseException:
        for leftover in (staged, *_sidecars(staged)):
            leftover.unlink(missing_ok=True)
        raise

    kept = data_dir / f"emlek.db.before-restore-{_stamp()}"
    moved: list[tuple[Path, Path]] = []
    try:
        if target.exists():
            for old in (target, *_sidecars(target)):
                destination = Path(str(kept) + old.name[len(target.name) :])
                os.replace(old, destination)
                moved.append((old, destination))
        os.replace(staged, target)
    except PermissionError as exc:
        for original, destination in reversed(moved):
            os.replace(destination, original)
        staged.unlink(missing_ok=True)
        raise EmlekError(
            ErrorCode.BUSY,
            "資料庫正被其他程式使用（例如 MCP 伺服器），請先關閉再還原",
            retryable=True,
        ) from exc

    try:
        result = inspect_database(target)
    except EmlekError:
        os.replace(target, Path(str(kept) + ".failed"))
        for original, destination in reversed(moved):
            os.replace(destination, original)
        raise
    return {
        "restored_from": str(source),
        "records": result["records"],
        "revisions": result["revisions"],
        "schema_version": result["schema_version"],
        "previous_database_kept_as": str(kept) if moved else None,
    }
