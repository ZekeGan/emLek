"""One-time confirmation tokens for sensitive writes.

A token is 128 random bits shown once to the caller; only its SHA-256 is stored. It is bound to
the operation and the exact text, expires after ten minutes and can be used once. Using it is an
UPDATE inside the writer's own transaction, so a failed write does not burn the token and two
processes racing for the same token cannot both win.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta

from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode

TTL_SECONDS = 600
KINDS = ("confirm", "notice")
_KEEP_EXPIRED = timedelta(days=1)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def content_hash(operation: str, ref: str, body: str) -> str:
    material = f"{operation}\n{ref}\n{body}".encode()
    return hashlib.sha256(material).hexdigest()


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue(db: Database, kind: str, chash: str) -> str:
    token = secrets.token_urlsafe(16)
    now = _now()
    with db.transaction() as conn:
        conn.execute(
            "DELETE FROM confirm_tokens WHERE expires_at < ?", (_iso(now - _KEEP_EXPIRED),)
        )
        conn.execute(
            "INSERT INTO confirm_tokens (token_hash, kind, content_hash, created_at, expires_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                _digest(token),
                kind,
                chash,
                _iso(now),
                _iso(now + timedelta(seconds=TTL_SECONDS)),
            ),
        )
    return token


def consume(conn: sqlite3.Connection, kind: str, token: str | None, chash: str) -> None:
    """Mark the token used, or raise TOKEN_INVALID. Every failure looks the same on purpose."""
    invalid = EmlekError(
        ErrorCode.TOKEN_INVALID, "確認碼無效、已過期或已使用；不可沿用先前同意或重播確認碼"
    )
    if not isinstance(token, str) or not token:
        raise invalid
    now = _iso(_now())
    changed = conn.execute(
        "UPDATE confirm_tokens SET used_at = ? WHERE token_hash = ? AND kind = ?"
        " AND content_hash = ? AND used_at IS NULL AND expires_at > ?",
        (now, _digest(token), kind, chash, now),
    ).rowcount
    if changed != 1:
        raise invalid
