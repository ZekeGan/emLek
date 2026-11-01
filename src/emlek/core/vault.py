"""Creating the data folder: permissions, config, database."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from emlek import __version__
from emlek.config import (
    DB_NAME,
    default_backup_dir,
    load_config,
    write_default_config,
)
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, require
from emlek.core.timeutil import utc_now_iso
from emlek.log import setup_logging


def current_user_principal() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    user = os.environ.get("USERNAME", "")
    return f"{domain}\\{user}" if domain else user


def restrict_to_current_user(path: Path) -> bool:
    """Remove inherited permissions and grant only the current user (Windows, no admin needed)."""
    if sys.platform != "win32":
        return False
    result = subprocess.run(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"{current_user_principal()}:(OI)(CI)F",
        ],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def acl_principals(path: Path) -> list[str]:
    """Names that have an access entry on the folder (Windows only)."""
    if sys.platform != "win32":
        return []
    result = subprocess.run(["icacls", str(path)], capture_output=True, check=False)
    text = result.stdout.decode("utf-8", errors="replace")
    names: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(str(path)):
            line = line[len(str(path)) :].strip()
        head, sep, _ = line.partition(":(")
        if sep and head:
            names.append(head.strip())
    return names


def init_vault(caller: Caller, data_dir: Path) -> dict[str, Any]:
    require(caller, "init")
    data_dir.mkdir(parents=True, exist_ok=True)
    acl_ok = restrict_to_current_user(data_dir)
    config_path = data_dir / "config.toml"
    if not config_path.exists():
        write_default_config(data_dir, default_backup_dir(data_dir))
    config = load_config(data_dir)
    setup_logging(data_dir)
    created = not config.db_path.exists()
    try:
        db = Database.open(config.db_path, must_exist=False)
    except EmlekError:
        raise
    try:
        with db.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('created_at', ?)",
                (utc_now_iso(),),
            )
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('created_with', ?)",
                (__version__,),
            )
        schema_version = db.user_version
        journal_mode = db.journal_mode
    finally:
        db.close()
    if created and not acl_ok and sys.platform == "win32":
        raise EmlekError(ErrorCode.INTERNAL, "無法限制資料夾權限，請確認資料夾位置可寫")
    return {
        "created": created,
        "data_dir": str(data_dir),
        "db_path": str(config.db_path),
        "db_name": DB_NAME,
        "schema_version": schema_version,
        "journal_mode": journal_mode,
        "backup_dir": str(config.backup_dir) if config.backup_dir else None,
        "permissions_restricted": acl_ok,
    }
