"""Consistent backups and verified restores."""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from emlek.config import load_config
from emlek.core import backup_crypto, security
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


def clean_leftovers(data_dir: Path, backup_dir: Path | None) -> None:
    """Plain-text staging files and half-written encrypted backups left by a crash."""
    tmp = data_dir / "tmp"
    if tmp.is_dir():
        for leftover in tmp.iterdir():
            if leftover.is_file():
                leftover.unlink(missing_ok=True)
    if backup_dir is not None and backup_dir.is_dir():
        for partial in backup_dir.glob("*.partial"):
            partial.unlink(missing_ok=True)


def create_backup(
    db: Database,
    caller: Caller,
    backup_dir: Path,
    data_dir: Path,
    *,
    password: str | None = None,
) -> dict[str, Any]:
    require(caller, "backup_encrypt" if password is not None else "backup")
    target_dir = backup_dir.resolve()
    if target_dir == data_dir.resolve() or data_dir.resolve() in target_dir.parents:
        raise EmlekError(ErrorCode.INVALID_INPUT, "備份資料夾不能放在資料夾裡面，請放到別的位置")
    target_dir.mkdir(parents=True, exist_ok=True)
    clean_leftovers(data_dir, target_dir)
    if password is None:
        target = target_dir / f"emlek-{_stamp()}.db"
        db.backup_to(target)
        info = inspect_database(target)
    else:
        backup_crypto.check_new_password(password)
        target = target_dir / f"emlek-{_stamp()}.db.enc"
        info = _encrypted_backup(db, data_dir, target, password)
    with db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_backup_at', ?)",
            (utc_now_iso(),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_backup_file', ?)",
            (target.name,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_backup_encrypted', ?)",
            ("1" if password is not None else "0",),
        )
    same_drive = bool(target_dir.drive) and data_dir.resolve().drive == target_dir.drive
    return {
        "file": str(target),
        "bytes": target.stat().st_size,
        "records": info["records"],
        "revisions": info["revisions"],
        "schema_version": info["schema_version"],
        "same_drive_as_data": same_drive,
        "encrypted": password is not None,
    }


def _encrypted_backup(db: Database, data_dir: Path, target: Path, password: str) -> dict[str, Any]:
    """Plain copy inside the data folder -> checked -> encrypted to .partial -> decrypted again and
    compared -> renamed. The plain copy is always removed (deleting is all that can be promised on
    an SSD)."""
    tmp_dir = data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    plain = tmp_dir / f"backup-{_stamp()}.db"
    partial = target.with_name(target.name + ".partial")
    try:
        db.backup_to(plain)
        info = inspect_database(plain)
        expected = backup_crypto.encrypt_file(plain, partial, password)
        if backup_crypto.decrypt_file(partial, None, password) != expected:
            raise EmlekError(ErrorCode.INTERNAL, "加密後的驗證不一致，已放棄這份備份")
        os.replace(partial, target)
    finally:
        plain.unlink(missing_ok=True)
        partial.unlink(missing_ok=True)
    return info


def open_backup(source: Path, data_dir: Path, password: str | None) -> tuple[Path, bool]:
    """The plain database file to restore from. An encrypted backup is decrypted to a staging
    file inside the data folder (returned with True: the caller deletes or consumes it)."""
    if not backup_crypto.is_encrypted(source):
        return source, False
    if not source.is_file():
        raise EmlekError(ErrorCode.NOT_FOUND, "找不到備份檔")
    if password is None:
        raise EmlekError(ErrorCode.INVALID_INPUT, "這是加密的備份，需要輸入備份密碼")
    staging = data_dir / "emlek.db.decrypted"
    staging.unlink(missing_ok=True)
    try:
        backup_crypto.decrypt_file(source, staging, password)
    except BaseException:
        staging.unlink(missing_ok=True)
        raise
    return staging, True


def _sidecars(path: Path) -> list[Path]:
    return [p for p in (Path(f"{path}-wal"), Path(f"{path}-shm")) if p.exists()]


def _carry_over_security(live: Path, staged: Path) -> None:
    """The restored database keeps this machine's PIN marker and recovery code, not the backup's,
    so restoring an old backup can never bring an old PIN back."""
    keys = security.PRESERVED_META_KEYS
    marks = ", ".join("?" for _ in keys)
    values: list[tuple[str, str]] = []
    if live.exists():
        conn = sqlite3.connect(f"{live.resolve().as_uri()}?mode=ro", uri=True)
        try:
            values = conn.execute(
                f"SELECT key, value FROM meta WHERE key IN ({marks})", keys
            ).fetchall()
        except sqlite3.Error:
            values = []
        finally:
            conn.close()
    conn = sqlite3.connect(staged)
    try:
        conn.execute(f"DELETE FROM meta WHERE key IN ({marks})", keys)
        conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", values)
        conn.commit()
    finally:
        conn.close()


def restore_backup(
    caller: Caller,
    data_dir: Path,
    source: Path,
    *,
    consume: bool = False,
    restored_from: Path | None = None,
) -> dict[str, Any]:
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
    if consume:
        os.replace(source, staged)  # the decrypted staging file: no second plain copy
    else:
        shutil.copyfile(source, staged)
    try:
        upgrade = Database(staged)
        try:
            upgrade.apply_migrations(load_migrations(), data_dir / "pre-migration")
        finally:
            upgrade.close()
        _carry_over_security(target, staged)
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
        "restored_from": str(restored_from or source),
        "records": result["records"],
        "revisions": result["revisions"],
        "schema_version": result["schema_version"],
        "previous_database_kept_as": str(kept) if moved else None,
    }
