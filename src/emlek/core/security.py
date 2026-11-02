"""PIN storage, lockout and recovery. See DESIGN, "信任閘門規格（M6）".

The PIN hash and the failure counters live in `security.json` next to the database, not in it:
restoring an old backup must not roll the PIN back, and backups must not carry the hash. The
recovery code's hash and the "a PIN was set" marker live in `meta`. A marker with no valid file
is the tampered state: everything is refused except `pin reset` with the recovery code.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode

SECURITY_FILE = "security.json"
KDF_N = 2**15
KDF_R = 8
KDF_P = 1
KDF_MAXMEM = 128 * 1024 * 1024
MIN_PIN_CHARS = 6
MAX_FAILURES = 5
LOCK_SECONDS = 300
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_RECOVERY_KEYS = ("pin_initialized", "recovery_salt", "recovery_hash", "recovery_params")
# What `restore` copies from the live database into the restored one.
PRESERVED_META_KEYS = (*_RECOVERY_KEYS, "recovery_failed", "recovery_locked_until")

UNSET, SET, TAMPERED = "unset", "set", "tampered"

_log = logging.getLogger("emlek")


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _scrypt(secret: str, salt: bytes, n: int, r: int, p: int) -> str:
    return hashlib.scrypt(
        secret.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=KDF_MAXMEM, dklen=32
    ).hex()


def _meta_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row[0])


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))


def _file(data_dir: Path) -> Path:
    return data_dir / SECURITY_FILE


def _read_file(data_dir: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(_file(data_dir).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    needed = ("pin_hash", "salt", "n", "r", "p", "failed_count", "failures_since_success")
    if not isinstance(data, dict) or any(key not in data for key in needed):
        return None
    return data


def _write_file(data_dir: Path, data: dict[str, Any]) -> None:
    target = _file(data_dir)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\n")
    os.replace(temp, target)


def state(conn: sqlite3.Connection, data_dir: Path) -> str:
    if _meta_get(conn, "pin_initialized") is None:
        return UNSET
    return SET if _read_file(data_dir) is not None else TAMPERED


def _check_new_pin(pin: str) -> None:
    if not isinstance(pin, str) or len(pin) < MIN_PIN_CHARS:
        raise EmlekError(ErrorCode.INVALID_INPUT, f"PIN 至少 {MIN_PIN_CHARS} 個字元")


def _new_recovery_code() -> str:
    chars = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(20))
    return "-".join(chars[i : i + 4] for i in range(0, 20, 4))


def _normalize_code(code: str) -> str:
    return code.replace("-", "").replace(" ", "").strip().upper()


def _pin_record(pin: str) -> dict[str, Any]:
    salt = secrets.token_bytes(16)
    return {
        "version": 1,
        "n": KDF_N,
        "r": KDF_R,
        "p": KDF_P,
        "salt": salt.hex(),
        "pin_hash": _scrypt(pin, salt, KDF_N, KDF_R, KDF_P),
        "failed_count": 0,
        "failures_since_success": 0,
        "locked_until": None,
        "last_success_at": None,
    }


def _store_recovery(conn: sqlite3.Connection) -> str:
    code = _new_recovery_code()
    salt = secrets.token_bytes(16)
    _meta_set(conn, "recovery_salt", salt.hex())
    _meta_set(conn, "recovery_params", f"{KDF_N},{KDF_R},{KDF_P}")
    _meta_set(conn, "recovery_hash", _scrypt(_normalize_code(code), salt, KDF_N, KDF_R, KDF_P))
    _meta_set(conn, "recovery_failed", "0")
    conn.execute("DELETE FROM meta WHERE key = 'recovery_locked_until'")
    return code


def set_pin(db: Database, data_dir: Path, pin: str) -> str:
    """First-time PIN. Returns the recovery code, which is shown once and never stored."""
    if state(db.conn, data_dir) != UNSET:
        raise EmlekError(ErrorCode.CONFLICT, "已設定過 PIN；要更換請用 pin change")
    _check_new_pin(pin)
    _write_file(data_dir, _pin_record(pin))  # file first: a crash leaves "unset", never "tampered"
    with db.transaction() as conn:
        code = _store_recovery(conn)
        _meta_set(conn, "pin_initialized", _iso(_now()))
    _log.info("security pin set")
    return code


def _remaining(until: str) -> int:
    return max(1, int((_parse(until) - _now()).total_seconds()))


def ensure_available(conn: sqlite3.Connection, data_dir: Path) -> None:
    """Raise unless a PIN may be asked for right now (set, not tampered, not locked)."""
    current = state(conn, data_dir)
    if current != SET:
        raise not_ready(current)
    data = _read_file(data_dir)
    assert data is not None
    locked = data.get("locked_until")
    if locked and _parse(locked) > _now():
        raise EmlekError(
            ErrorCode.NOT_PERMITTED,
            f"PIN 錯誤次數過多，已鎖定；約 {_remaining(locked)} 秒後再試",
            data={"locked_for_seconds": _remaining(locked)},
        )


def verify_pin(db: Database, data_dir: Path, pin: str) -> None:
    """Check a PIN, counting the attempt before looking at the answer."""
    current = state(db.conn, data_dir)
    if current != SET:
        raise not_ready(current)
    data = _read_file(data_dir)
    assert data is not None
    now = _now()
    locked = data.get("locked_until")
    if locked and _parse(locked) > now:
        raise EmlekError(
            ErrorCode.NOT_PERMITTED,
            f"PIN 錯誤次數過多，已鎖定；約 {_remaining(locked)} 秒後再試",
            data={"locked_for_seconds": _remaining(locked)},
        )
    data["failed_count"] += 1
    data["failures_since_success"] += 1
    _write_file(data_dir, data)  # counted before the comparison: killing us mid-way still costs
    candidate = _scrypt(pin, bytes.fromhex(data["salt"]), data["n"], data["r"], data["p"])
    if hmac.compare_digest(candidate, data["pin_hash"]):
        data.update(
            failed_count=0, failures_since_success=0, locked_until=None, last_success_at=_iso(now)
        )
        _write_file(data_dir, data)
        return
    left = MAX_FAILURES - data["failed_count"]
    if left <= 0:
        data["locked_until"] = _iso(now + timedelta(seconds=LOCK_SECONDS))
        data["failed_count"] = 0
        _write_file(data_dir, data)
        _log.warning("security pin locked after repeated failures")
        raise EmlekError(
            ErrorCode.NOT_PERMITTED,
            "PIN 不正確；錯誤次數過多，已鎖定 5 分鐘",
            data={"locked_for_seconds": LOCK_SECONDS},
        )
    raise EmlekError(ErrorCode.NOT_PERMITTED, f"PIN 不正確（再錯 {left} 次會鎖定）")


def not_ready(current: str) -> EmlekError:
    if current == UNSET:
        return EmlekError(
            ErrorCode.NOT_PERMITTED, "尚未設定 PIN；請先在自己的終端機執行 emlek pin set"
        )
    return EmlekError(
        ErrorCode.NOT_PERMITTED,
        "PIN 設定檔不見或損壞；只能用 emlek pin reset 以復原碼重設",
    )


def change_pin(db: Database, data_dir: Path, old: str, new: str) -> None:
    _check_new_pin(new)
    verify_pin(db, data_dir, old)
    data = _read_file(data_dir)
    assert data is not None
    fresh = _pin_record(new)
    fresh["last_success_at"] = _iso(_now())
    _write_file(data_dir, fresh)
    _log.info("security pin changed")


def reset_pin(db: Database, data_dir: Path, recovery_code: str, new: str) -> str:
    """Set a new PIN using the recovery code. Returns a new recovery code."""
    current = state(db.conn, data_dir)
    if current == UNSET:
        raise EmlekError(ErrorCode.CONFLICT, "尚未設定 PIN；請用 pin set")
    _check_new_pin(new)
    with db.transaction() as conn:
        locked = _meta_get(conn, "recovery_locked_until")
        if locked and _parse(locked) > _now():
            raise EmlekError(
                ErrorCode.NOT_PERMITTED,
                f"復原碼錯誤次數過多，已鎖定；約 {_remaining(locked)} 秒後再試",
            )
        failed = int(_meta_get(conn, "recovery_failed") or "0") + 1
        _meta_set(conn, "recovery_failed", str(failed))  # counted before the comparison
    params = (_meta_get(db.conn, "recovery_params") or f"{KDF_N},{KDF_R},{KDF_P}").split(",")
    n, r, p = (int(x) for x in params)
    salt = bytes.fromhex(_meta_get(db.conn, "recovery_salt") or "")
    stored = _meta_get(db.conn, "recovery_hash") or ""
    candidate = _scrypt(_normalize_code(recovery_code), salt, n, r, p)
    if not hmac.compare_digest(candidate, stored):
        with db.transaction() as conn:
            if failed >= MAX_FAILURES:
                _meta_set(conn, "recovery_failed", "0")
                _meta_set(
                    conn, "recovery_locked_until", _iso(_now() + timedelta(seconds=LOCK_SECONDS))
                )
        raise EmlekError(ErrorCode.NOT_PERMITTED, "復原碼不正確")
    _write_file(data_dir, _pin_record(new))
    with db.transaction() as conn:
        code = _store_recovery(conn)
    _log.info("security pin reset with recovery code")
    return code


def status(conn: sqlite3.Connection, data_dir: Path) -> dict[str, Any]:
    """What `doctor` shows. Never includes the hash."""
    current = state(conn, data_dir)
    info: dict[str, Any] = {
        "state": current,
        "locked": False,
        "locked_until": None,
        "failures_since_success": 0,
        "last_success_at": None,
    }
    data = _read_file(data_dir) if current == SET else None
    if data is not None:
        locked = data.get("locked_until")
        info.update(
            locked=bool(locked and _parse(locked) > _now()),
            locked_until=locked,
            failures_since_success=data["failures_since_success"],
            last_success_at=data.get("last_success_at"),
        )
    return info
