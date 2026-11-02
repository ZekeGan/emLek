"""Encrypted backup files (format version 1, `.db.enc`).

Layout: a 40-byte header, then one or more AES-256-GCM segments of up to 1 MiB of plain text each.
The whole header is authenticated with every segment, the segment number is part of the nonce, and
the last segment carries a flag in its associated data, so changing a byte, swapping two segments,
cutting the file (even exactly between segments) or appending data all fail to decrypt.
"""

from __future__ import annotations

import hashlib
import os
import struct
import unicodedata
from pathlib import Path
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from emlek.core.errors import EmlekError, ErrorCode

MAGIC = b"EMLKBK01"
KDF_SCRYPT = 1
SEGMENT_LOG2 = 20
SEGMENT = 1 << SEGMENT_LOG2
TAG = 16
HEADER = struct.Struct(">8sBBBB3x16s8sB")  # magic, kdf, log2(n), r, p, pad, salt, prefix, segment
assert HEADER.size == 40

DEFAULT_LOG2N = 17
DEFAULT_R = 8
DEFAULT_P = 1
LOG2N_RANGE = (14, 18)
R_ALLOWED = 8
P_RANGE = (1, 4)
MIN_PASSWORD_CHARS = 10
MAX_SEGMENTS = 1 << 32
_WRONG = "密碼錯誤或檔案損毀"


def is_encrypted(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def normalize_password(password: str) -> bytes:
    return unicodedata.normalize("NFC", password).encode("utf-8")


def check_new_password(password: str) -> None:
    if len(unicodedata.normalize("NFC", password)) < MIN_PASSWORD_CHARS:
        raise EmlekError(ErrorCode.INVALID_INPUT, f"備份密碼至少 {MIN_PASSWORD_CHARS} 個字元")


def _key(password: str, salt: bytes, log2n: int, r: int, p: int) -> bytes:
    n = 1 << log2n
    # memory is 128 * r * n bytes plus working space; sized from the header values, which have been
    # range-checked first, and never shared with the PIN's limit
    return hashlib.scrypt(
        normalize_password(password),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=128 * r * n + (16 << 20),
        dklen=32,
    )


def _nonce(prefix: bytes, index: int) -> bytes:
    return prefix + index.to_bytes(4, "big")


def _aad(header: bytes, last: bool) -> bytes:
    return header + (b"\x01" if last else b"\x00")


def encrypt_file(
    source: Path,
    target: Path,
    password: str,
    *,
    log2n: int = DEFAULT_LOG2N,
    r: int = DEFAULT_R,
    p: int = DEFAULT_P,
) -> str:
    """Encrypt `source` into `target`; returns the SHA-256 of the plain text."""
    check_new_password(password)
    if not (
        LOG2N_RANGE[0] <= log2n <= LOG2N_RANGE[1]
        and r == R_ALLOWED
        and P_RANGE[0] <= p <= P_RANGE[1]
    ):
        raise EmlekError(ErrorCode.INVALID_INPUT, "加密參數超出允許範圍")
    salt, prefix = os.urandom(16), os.urandom(8)
    header = HEADER.pack(MAGIC, KDF_SCRYPT, log2n, r, p, salt, prefix, SEGMENT_LOG2)
    aead = AESGCM(_key(password, salt, log2n, r, p))
    digest = hashlib.sha256()
    with source.open("rb") as reader, target.open("wb") as writer:
        writer.write(header)
        current = reader.read(SEGMENT)
        index = 0
        while True:
            following = reader.read(SEGMENT) if len(current) == SEGMENT else b""
            last = not following
            if index >= MAX_SEGMENTS:
                raise EmlekError(ErrorCode.INVALID_INPUT, "檔案過大，無法加密")
            digest.update(current)
            writer.write(aead.encrypt(_nonce(prefix, index), current, _aad(header, last)))
            if last:
                break
            current, index = following, index + 1
        writer.flush()
        os.fsync(writer.fileno())
    return digest.hexdigest()


def _read_header(reader: BinaryIO) -> tuple[bytes, bytes, bytes, int, int, int]:
    header = reader.read(HEADER.size)
    if len(header) < len(MAGIC) or header[: len(MAGIC)] != MAGIC:
        raise EmlekError(ErrorCode.INVALID_INPUT, "這不是 emLek 的加密備份")
    if len(header) != HEADER.size:
        raise EmlekError(ErrorCode.INVALID_INPUT, "加密備份的檔頭不完整")
    _, kdf, log2n, r, p, salt, prefix, segment = HEADER.unpack(header)
    if kdf != KDF_SCRYPT:
        raise EmlekError(ErrorCode.INVALID_INPUT, "不支援的加密備份版本")
    in_range = (
        LOG2N_RANGE[0] <= log2n <= LOG2N_RANGE[1]
        and r == R_ALLOWED
        and P_RANGE[0] <= p <= P_RANGE[1]
        and segment == SEGMENT_LOG2
    )
    if not in_range:
        raise EmlekError(ErrorCode.INVALID_INPUT, "加密備份的參數超出允許範圍，已拒絕")
    return header, salt, prefix, log2n, r, p


def decrypt_file(source: Path, target: Path | None, password: str) -> str:
    """Decrypt into `target` (or only verify when it is None); returns the SHA-256 of the plain
    text. A partly written target is the caller's to delete when this raises."""
    digest = hashlib.sha256()
    with source.open("rb") as reader:
        header, salt, prefix, log2n, r, p = _read_header(reader)
        aead = AESGCM(_key(password, salt, log2n, r, p))
        out = target.open("wb") if target is not None else None
        try:
            size = SEGMENT + TAG
            current = reader.read(size)
            index = 0
            while True:
                if len(current) < TAG:
                    raise EmlekError(ErrorCode.INVALID_INPUT, _WRONG)
                following = reader.read(size) if len(current) == size else b""
                if len(current) < size and reader.read(1):
                    raise EmlekError(ErrorCode.INVALID_INPUT, _WRONG)
                last = not following
                if index >= MAX_SEGMENTS:
                    raise EmlekError(ErrorCode.INVALID_INPUT, _WRONG)
                try:
                    plain = aead.decrypt(_nonce(prefix, index), current, _aad(header, last))
                except InvalidTag as exc:
                    raise EmlekError(ErrorCode.INVALID_INPUT, _WRONG) from exc
                digest.update(plain)
                if out is not None:
                    out.write(plain)
                if last:
                    break
                current, index = following, index + 1
            if out is not None:
                out.flush()
                os.fsync(out.fileno())
        finally:
            if out is not None:
                out.close()
    return digest.hexdigest()
