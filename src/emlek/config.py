"""Where the data lives and what config.toml says."""

from __future__ import annotations

import json
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from emlek.core.errors import EmlekError, ErrorCode

CONFIG_NAME = "config.toml"
DB_NAME = "emlek.db"
ENV_DATA_DIR = "EMLEK_DATA_DIR"


@dataclass(frozen=True)
class Config:
    data_dir: Path
    timezone: str = "local"
    backup_dir: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_NAME


def resolve_data_dir(flag: str | None) -> Path:
    """Flag, then environment variable, then the per-user default."""
    if flag:
        return Path(flag).expanduser().resolve()
    env = os.environ.get(ENV_DATA_DIR)
    if env:
        return Path(env).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    root = Path(local) if local else Path.home() / ".local" / "share"
    return (root / "emlek").resolve()


def fixed_drives() -> list[str]:
    """Roots of fixed (non-removable, non-network) drives; empty off Windows."""
    if sys.platform != "win32":
        return []
    import ctypes

    fixed = 3  # DRIVE_FIXED
    drives: list[str] = []
    for root in os.listdrives():
        if ctypes.windll.kernel32.GetDriveTypeW(root) == fixed:
            drives.append(root)
    return drives


def default_backup_dir(data_dir: Path) -> Path:
    """Prefer a folder on a different drive from the data, so one disk failure is survivable."""
    data_drive = data_dir.drive.upper()
    for root in fixed_drives():
        if root.rstrip("\\").upper() != data_drive:
            return Path(root) / "emlek-backups"
    return Path.home() / "Documents" / "emlek-backups"


def _toml_string(value: str) -> str:
    return f"'{value}'" if "'" not in value and "\n" not in value else json.dumps(value)


def write_default_config(data_dir: Path, backup_dir: Path) -> Path:
    path = data_dir / CONFIG_NAME
    path.write_text(
        f"# emLek settings\ntimezone = 'local'\nbackup_dir = {_toml_string(str(backup_dir))}\n",
        encoding="utf-8",
    )
    return path


def load_config(data_dir: Path) -> Config:
    path = data_dir / CONFIG_NAME
    raw: dict[str, object] = {}
    if path.exists():
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise EmlekError(ErrorCode.INVALID_INPUT, f"設定檔無法讀取：{CONFIG_NAME}") from exc
    timezone = raw.get("timezone", "local")
    backup = raw.get("backup_dir")
    if not isinstance(timezone, str) or not (backup is None or isinstance(backup, str)):
        raise EmlekError(ErrorCode.INVALID_INPUT, f"設定檔格式不正確：{CONFIG_NAME}")
    return Config(data_dir, timezone, Path(backup) if backup else None)
