"""emlek cleanup: remove emLek's own temporary plain-text copies (pre-migration copies, the
database kept by a restore, leftovers of failed operations).

Never touches the live database, the backup folder or exports. Before deleting anything it
proves a good backup newer than the newest copy exists, so cleanup can never remove the last
good copy of the data.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from emlek.core import backup, backup_crypto
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, require


def targets(data_dir: Path) -> list[Path]:
    found: list[Path] = []
    for name in ("pre-migration", "tmp"):
        folder = data_dir / name
        if folder.is_dir():
            found += [p for p in sorted(folder.rglob("*")) if p.is_file()]
    if data_dir.is_dir():
        for path in sorted(data_dir.iterdir()):
            if path.is_file() and path.name != "emlek.db" and path.name.startswith("emlek.db."):
                if path.name.endswith(("-wal", "-shm")) and not path.name.startswith(
                    "emlek.db.before-restore"
                ):
                    continue  # the live database's own journal files
                found.append(path)
    return found


def preview(caller: Caller, data_dir: Path) -> dict[str, Any]:
    require(caller, "cleanup_preview")
    files = targets(data_dir)
    return {
        "files": [str(p) for p in files],
        "count": len(files),
        "bytes": sum(p.stat().st_size for p in files),
    }


def _newest_backup(backup_dir: Path | None, newer_than: float) -> Path | None:
    if backup_dir is None or not backup_dir.is_dir():
        return None
    candidates = [
        p
        for p in backup_dir.glob("emlek-*")
        if p.name.endswith((".db", ".db.enc")) and p.stat().st_mtime > newer_than
    ]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def apply(
    db: Database,
    caller: Caller,
    data_dir: Path,
    backup_dir: Path | None,
    ask_password: Callable[[], str],
) -> dict[str, Any]:
    require(caller, "cleanup_apply")
    files = targets(data_dir)
    if not files:
        return {"removed": 0, "bytes": 0}
    if str(db.conn.execute("PRAGMA integrity_check").fetchone()[0]) != "ok":
        raise EmlekError(ErrorCode.INTERNAL, "現行資料庫的完整性檢查未通過，不清理任何副本")
    newest = max(p.stat().st_mtime for p in files)
    good = _newest_backup(backup_dir, newest)
    if good is None:
        raise EmlekError(
            ErrorCode.CONFLICT,
            "找不到比這些副本更新的備份，先執行 emlek backup 再清理（不會刪除最後一份可用的資料）",
        )
    if good.name.endswith(".enc"):
        backup_crypto.decrypt_file(good, None, ask_password())  # authenticated end to end
    else:
        backup.inspect_database(good)
    size = 0
    for path in files:
        size += path.stat().st_size
        path.unlink()
    old = data_dir / "pre-migration"
    if old.is_dir() and not any(old.iterdir()):
        old.rmdir()
    return {"removed": len(files), "bytes": size, "verified_against": good.name}
