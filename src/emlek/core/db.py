"""SQLite access: connection settings, migrations and the transaction helper."""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.timeutil import utc_now_iso

_SYNCHRONOUS_FULL = 2
_BUSY_TIMEOUT_MS = 5000


def wal_safe(version: tuple[int, ...]) -> bool:
    """True if this SQLite includes the WAL-reset fix (3.51.3+, or backports 3.50.7+ / 3.44.6+)."""
    if version >= (3, 51, 3):
        return True
    if version[:2] == (3, 50):
        return version >= (3, 50, 7)
    if version[:2] == (3, 44):
        return version >= (3, 44, 6)
    return False


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def load_migrations() -> list[Migration]:
    found: list[Migration] = []
    for entry in resources.files("emlek.core.migrations").iterdir():
        if not entry.name.endswith(".sql"):
            continue
        number, _, rest = entry.name.partition("_")
        found.append(Migration(int(number), rest.removesuffix(".sql"), entry.read_text("utf-8")))
    found.sort(key=lambda m: m.version)
    if [m.version for m in found] != list(range(1, len(found) + 1)):
        raise EmlekError(ErrorCode.INTERNAL, "遷移檔編號必須從 1 起連續")
    return found


def _map_sqlite_error(exc: sqlite3.Error) -> EmlekError:
    text = str(exc).lower()
    if "locked" in text or "busy" in text:
        return EmlekError(ErrorCode.BUSY, "資料庫忙碌中，請稍後再試", retryable=True)
    return EmlekError(ErrorCode.INTERNAL, "資料庫錯誤")


class Database:
    """One connection with emlek's required settings. Not shared between threads."""

    def __init__(self, path: Path, *, sqlite_version: tuple[int, ...] | None = None) -> None:
        self.path = path
        self._purge_mode = False
        self._version = sqlite_version or sqlite3.sqlite_version_info
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.create_function("emlek_purge_mode", 0, self._purge_flag)
        self.journal_mode = self._configure()

    def _purge_flag(self) -> int:
        return 1 if self._purge_mode else 0

    def _configure(self) -> str:
        wanted = "wal" if wal_safe(self._version) else "delete"
        try:
            actual = str(self.conn.execute(f"PRAGMA journal_mode = {wanted}").fetchone()[0]).lower()
            self.conn.execute("PRAGMA synchronous = FULL")
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
            checks = {
                "journal_mode": actual == wanted,
                "synchronous": self.conn.execute("PRAGMA synchronous").fetchone()[0]
                == _SYNCHRONOUS_FULL,
                "foreign_keys": self.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1,
                "busy_timeout": self.conn.execute("PRAGMA busy_timeout").fetchone()[0]
                == _BUSY_TIMEOUT_MS,
            }
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            raise EmlekError(ErrorCode.INTERNAL, f"資料庫設定未生效：{', '.join(failed)}")
        return actual

    @classmethod
    def open(
        cls,
        path: Path,
        *,
        must_exist: bool = True,
        migrate: bool = True,
        migrations: Sequence[Migration] | None = None,
        backup_dir: Path | None = None,
        sqlite_version: tuple[int, ...] | None = None,
    ) -> Database:
        if must_exist and not path.exists():
            raise EmlekError(ErrorCode.NOT_FOUND, "尚未初始化，請先執行 emlek init")
        db = cls(path, sqlite_version=sqlite_version)
        if not migrate:
            return db
        try:
            db.apply_migrations(
                load_migrations() if migrations is None else migrations,
                backup_dir or path.parent / "pre-migration",
            )
        except BaseException:
            db.close()
            raise
        return db

    @property
    def user_version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def apply_migrations(self, migrations: Sequence[Migration], backup_dir: Path) -> list[int]:
        current = self.user_version
        pending = [m for m in migrations if m.version > current]
        if not pending:
            return []
        if current > 0:
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = utc_now_iso().replace(":", "").replace(".", "")
            self.backup_to(backup_dir / f"pre-migration-v{current}-{stamp}.db")
        applied: list[int] = []
        for migration in pending:
            script = (
                f"BEGIN IMMEDIATE;\n{migration.sql}\n"
                f"PRAGMA user_version = {migration.version};\nCOMMIT;"
            )
            try:
                self.conn.executescript(script)
            except sqlite3.Error as exc:
                if self.conn.in_transaction:
                    self.conn.execute("ROLLBACK")
                raise EmlekError(
                    ErrorCode.INTERNAL, f"遷移 {migration.version:04d} 失敗，資料庫維持原狀"
                ) from exc
            applied.append(migration.version)
        return applied

    def backup_to(self, target: Path) -> None:
        if target.exists():
            raise EmlekError(ErrorCode.CONFLICT, "備份目標已存在")
        try:
            self.conn.execute("VACUUM INTO ?", (str(target),))
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """All-or-nothing write section (BEGIN IMMEDIATE ... COMMIT)."""
        try:
            self.conn.execute("BEGIN IMMEDIATE")
        except sqlite3.Error as exc:
            raise _map_sqlite_error(exc) from exc
        try:
            yield self.conn
        except BaseException:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise
        try:
            self.conn.execute("COMMIT")
        except sqlite3.Error as exc:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
            raise _map_sqlite_error(exc) from exc

    @contextlib.contextmanager
    def purge_mode(self) -> Iterator[None]:
        """Temporarily lets the immutability triggers pass. Only the purge routine may use it."""
        self._purge_mode = True
        try:
            yield
        finally:
            self._purge_mode = False

    def close(self) -> None:
        self.conn.close()
