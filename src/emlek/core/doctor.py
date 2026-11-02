"""Environment and vault health report. Read-only."""

from __future__ import annotations

import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from emlek.config import Config, load_config
from emlek.core import security
from emlek.core.db import Database, load_migrations, wal_safe
from emlek.core.errors import EmlekError
from emlek.core.permissions import Caller, require
from emlek.core.search import index_status
from emlek.core.vault import acl_principals, current_user_principal

MAX_BACKUP_AGE_DAYS = 14
_SYNC_HINT = re.compile(r"onedrive|dropbox|google ?drive|icloud|nextcloud|syncthing|box sync", re.I)
_TRUSTED_PRINCIPAL_ENDINGS = ("\\system", "\\administrators")


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # ok | warn | fail | info
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def _fts5_trigram_works() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
        conn.close()
    except sqlite3.Error:
        return False
    return True


def is_sync_folder(path: Path) -> bool:
    return bool(_SYNC_HINT.search(str(path)))


def run_checks(
    caller: Caller,
    data_dir: Path,
    *,
    sqlite_version: tuple[int, ...] | None = None,
) -> dict[str, Any]:
    require(caller, "doctor")
    version = sqlite_version or sqlite3.sqlite_version_info
    checks: list[Check] = []
    py = sys.version_info
    checks.append(
        Check("python", "ok" if py >= (3, 14) else "fail", f"{py.major}.{py.minor}.{py.micro}")
    )
    sqlite_text = ".".join(str(n) for n in version)
    if wal_safe(version):
        checks.append(Check("sqlite", "ok", f"{sqlite_text}（含 WAL 修補，使用 WAL）"))
    else:
        checks.append(
            Check("sqlite", "warn", f"{sqlite_text}（缺 WAL 修補，改用 DELETE 日誌模式）")
        )
    checks.append(
        Check("fts5_trigram", "ok", "可用")
        if _fts5_trigram_works()
        else Check("fts5_trigram", "fail", "此 SQLite 不支援 FTS5 trigram")
    )
    checks.append(_check_data_dir(data_dir))
    if data_dir.exists():
        checks.append(_check_permissions(data_dir))
        checks.extend(_check_database(data_dir))
    checks.append(
        Check(
            "disk_encryption",
            "info",
            "無法確認；Windows 家用版沒有 BitLocker，資料庫與日誌在磁碟上是明文",
        )
    )
    status = "ok"
    if any(c.status == "fail" for c in checks):
        status = "fail"
    elif any(c.status == "warn" for c in checks):
        status = "warn"
    return {"status": status, "checks": [c.to_dict() for c in checks]}


def _check_data_dir(data_dir: Path) -> Check:
    if not data_dir.exists():
        return Check("data_dir", "warn", f"{data_dir}（尚未建立，請執行 emlek init）")
    if is_sync_folder(data_dir):
        return Check(
            "data_dir", "warn", f"{data_dir}（看起來在雲端同步資料夾內，資料庫不應放在那裡）"
        )
    return Check("data_dir", "ok", str(data_dir))


def _check_permissions(data_dir: Path) -> Check:
    if sys.platform != "win32":
        return Check("permissions", "info", "僅在 Windows 檢查資料夾權限")
    me = current_user_principal().lower()
    extra = [
        name
        for name in acl_principals(data_dir)
        if name.lower() != me and not name.lower().endswith(_TRUSTED_PRINCIPAL_ENDINGS)
    ]
    if extra:
        return Check("permissions", "warn", f"資料夾對其他帳號開放：{', '.join(extra)}")
    return Check("permissions", "ok", "只有目前使用者（與系統管理帳號）能存取")


def _check_database(data_dir: Path) -> list[Check]:
    try:
        config = load_config(data_dir)
    except EmlekError as exc:
        return [Check("config", "fail", exc.message)]
    checks = [Check("config", "ok", f"timezone={config.timezone}")]
    if not config.db_path.exists():
        return [*checks, Check("database", "warn", "尚未建立資料庫，請執行 emlek init")]
    try:
        db = Database.open(config.db_path, migrate=False)
    except EmlekError as exc:
        return [*checks, Check("database", "fail", exc.message)]
    try:
        quick = str(db.conn.execute("PRAGMA quick_check").fetchone()[0])
        latest = len(load_migrations())
        if quick != "ok":
            checks.append(Check("database", "fail", "完整性檢查未通過"))
        elif db.user_version != latest:
            checks.append(Check("database", "warn", f"結構版本 {db.user_version}，最新為 {latest}"))
        else:
            checks.append(
                Check("database", "ok", f"結構版本 {db.user_version}，日誌模式 {db.journal_mode}")
            )
            status = index_status(db)
            if status["ok"]:
                checks.append(Check("search_index", "ok", f"{status['indexed']} 個版本已建立索引"))
            else:
                checks.append(
                    Check(
                        "search_index",
                        "warn",
                        f"索引 {status['indexed']} 筆與資料 {status['revisions']} 筆不一致，"
                        "請執行 emlek reindex",
                    )
                )
            checks.append(_check_backup(db, config))
            checks.append(_check_security(db, data_dir))
            checks.append(_check_tags(db))
    finally:
        db.close()
    return checks


def _check_tags(db: Database) -> Check:
    tags = db.conn.execute("SELECT count(*) FROM tags").fetchone()[0]
    indexed = db.conn.execute("SELECT count(*) FROM tags_fts_docsize").fetchone()[0]
    if tags != indexed:
        return Check(
            "tags", "warn", f"標籤 {tags} 個，索引 {indexed} 筆不一致，請執行 emlek reindex"
        )
    used = db.conn.execute("SELECT count(DISTINCT record_id) FROM record_tags").fetchone()[0]
    total = db.conn.execute("SELECT count(*) FROM records").fetchone()[0]
    share = f"，{used}／{total} 筆記錄有標籤" if total else ""
    return Check("tags", "ok", f"{tags} 個標籤{share}")


def _check_security(db: Database, data_dir: Path) -> Check:
    info = security.status(db.conn, data_dir)
    if info["state"] == security.UNSET:
        return Check(
            "pin",
            "warn",
            "尚未設定 PIN：還原、改觸發語句等危險命令目前一律拒絕。"
            "請在你自己的終端機執行 emlek pin set（先設好，再把終端機權限交給 AI）",
        )
    if info["state"] == security.TAMPERED:
        return Check("pin", "fail", "PIN 設定檔不見或損壞；只能用 emlek pin reset 以復原碼重設")
    if info["locked"]:
        return Check("pin", "warn", f"PIN 已鎖定至 {info['locked_until']}（有人連續輸入錯誤）")
    if info["failures_since_success"]:
        return Check(
            "pin",
            "warn",
            f"上次成功後有 {info['failures_since_success']} 次 PIN 錯誤嘗試；"
            "若不是你，可能有程式在猜 PIN",
        )
    last = info["last_success_at"] or "尚未使用"
    return Check("pin", "ok", f"已設定；上次通過 {last}")


def _check_backup(db: Database, config: Config) -> Check:
    last = db.conn.execute("SELECT value FROM meta WHERE key = 'last_backup_at'").fetchone()
    where = (
        f"（備份資料夾：{config.backup_dir}）" if config.backup_dir else "（尚未設定備份資料夾）"
    )
    if last is None:
        return Check("backup", "warn", f"尚無備份，請執行 emlek backup {where}")
    taken = datetime.fromisoformat(last[0].replace("Z", "+00:00"))
    age = (datetime.now(UTC) - taken).days
    if age > MAX_BACKUP_AGE_DAYS:
        return Check("backup", "warn", f"上次備份是 {age} 天前（{last[0]}）{where}")
    encrypted = db.conn.execute(
        "SELECT value FROM meta WHERE key = 'last_backup_encrypted'"
    ).fetchone()
    kind = "（已加密）" if encrypted and encrypted[0] == "1" else "（未加密）"
    return Check("backup", "ok", f"上次備份 {last[0]}{kind} {where}")
