"""T36: an encrypted backup round-trips and every kind of tampering is refused."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from emlek.core import backup_crypto as crypto
from emlek.core.errors import EmlekError, ErrorCode

PASSWORD = "correct horse battery"
FAST = {"log2n": 14}


def _encrypt(tmp_path: Path, data: bytes, **kw: int) -> tuple[Path, Path, str]:
    plain = tmp_path / "plain.bin"
    plain.write_bytes(data)
    out = tmp_path / "backup.db.enc"
    digest = crypto.encrypt_file(plain, out, PASSWORD, **{**FAST, **kw})
    return plain, out, digest


def _refused(path: Path, tmp_path: Path, password: str = PASSWORD) -> EmlekError:
    with pytest.raises(EmlekError) as info:
        crypto.decrypt_file(path, tmp_path / "out.bin", password)
    assert info.value.code is ErrorCode.INVALID_INPUT
    return info.value


@pytest.mark.parametrize(
    "size",
    [0, 1, 1000, crypto.SEGMENT - 1, crypto.SEGMENT, crypto.SEGMENT + 1, 2 * crypto.SEGMENT],
)
def test_round_trip_at_every_segment_boundary(tmp_path: Path, size: int) -> None:
    data = os.urandom(size)
    _, out, digest = _encrypt(tmp_path, data)
    restored = tmp_path / "restored.bin"
    assert crypto.decrypt_file(out, restored, PASSWORD) == digest
    assert restored.read_bytes() == data
    segments = max(
        1, -(-size // crypto.SEGMENT)
    )  # a full last segment is not followed by an empty one
    assert out.stat().st_size == crypto.HEADER.size + size + crypto.TAG * segments
    assert crypto.is_encrypted(out) and not crypto.is_encrypted(tmp_path / "restored.bin")


def test_the_wrong_password_is_refused_and_looks_like_damage(tmp_path: Path) -> None:
    _, out, _ = _encrypt(tmp_path, b"secret" * 100)
    wrong = _refused(out, tmp_path, "not the password!!")
    assert "密碼錯誤或檔案損毀" in wrong.message
    assert crypto.decrypt_file(out, None, PASSWORD)  # verify-only mode


@pytest.mark.parametrize(
    "where", ["header_salt", "header_prefix", "first_cipher", "tag", "last_cipher"]
)
def test_changing_one_byte_anywhere_is_refused(tmp_path: Path, where: str) -> None:
    _, out, _ = _encrypt(tmp_path, os.urandom(crypto.SEGMENT + 500))
    raw = bytearray(out.read_bytes())
    position = {
        "header_salt": 20,
        "header_prefix": 36,
        "first_cipher": crypto.HEADER.size + 10,
        "tag": crypto.HEADER.size + crypto.SEGMENT + 3,
        "last_cipher": len(raw) - 30,
    }[where]
    raw[position] ^= 0x01
    out.write_bytes(bytes(raw))
    _refused(out, tmp_path)


def test_swapping_two_segments_is_refused(tmp_path: Path) -> None:
    _, out, _ = _encrypt(tmp_path, os.urandom(2 * crypto.SEGMENT + 10))
    raw = out.read_bytes()
    size = crypto.SEGMENT + crypto.TAG
    head, first, second = (
        raw[: crypto.HEADER.size],
        raw[crypto.HEADER.size :][:size],
        raw[crypto.HEADER.size :][size : 2 * size],
    )
    tail = raw[crypto.HEADER.size + 2 * size :]
    out.write_bytes(head + second + first + tail)
    _refused(out, tmp_path)


def test_cutting_the_file_is_refused_even_between_segments(tmp_path: Path) -> None:
    _, out, _ = _encrypt(tmp_path, os.urandom(2 * crypto.SEGMENT + 10))
    raw = out.read_bytes()
    size = crypto.SEGMENT + crypto.TAG
    for cut in (
        crypto.HEADER.size + size,
        crypto.HEADER.size + 2 * size,
        len(raw) - 1,
        crypto.HEADER.size,
        5,
    ):
        out.write_bytes(raw[:cut])
        _refused(out, tmp_path)


def test_appending_data_is_refused(tmp_path: Path) -> None:
    _, out, _ = _encrypt(tmp_path, os.urandom(crypto.SEGMENT))  # last segment is a full one
    raw = out.read_bytes()
    out.write_bytes(raw + b"\x00")
    _refused(out, tmp_path)
    out.write_bytes(raw + raw[crypto.HEADER.size :])  # a copy of the segment as a new one
    _refused(out, tmp_path)
    _, short, _ = _encrypt(tmp_path, b"abc")
    short.write_bytes(short.read_bytes() + b"junk")
    _refused(short, tmp_path)


def test_a_hostile_header_is_refused_before_any_key_derivation(tmp_path: Path) -> None:
    _, out, _ = _encrypt(tmp_path, b"data")
    raw = bytearray(out.read_bytes())
    for index, value in ((9, 30), (9, 1), (10, 9), (11, 0), (11, 99), (39, 21)):
        changed = bytearray(raw)
        changed[index] = value
        out.write_bytes(bytes(changed))
        started = time.monotonic()
        error = _refused(out, tmp_path)
        assert time.monotonic() - started < 1.0  # nothing was derived
        assert "密碼錯誤" not in error.message  # header problems say what is wrong
    wrong_version = bytearray(raw)
    wrong_version[8] = 7
    out.write_bytes(bytes(wrong_version))
    assert "版本" in _refused(out, tmp_path).message
    out.write_bytes(b"NOTEMLEK" + bytes(40))
    assert "不是 emLek" in _refused(out, tmp_path).message
    out.write_bytes(crypto.MAGIC + b"\x01")
    assert "檔頭不完整" in _refused(out, tmp_path).message


def test_password_rules_and_normalization(tmp_path: Path) -> None:
    plain = tmp_path / "p"
    plain.write_bytes(b"x")
    with pytest.raises(EmlekError):
        crypto.encrypt_file(plain, tmp_path / "o", "short", **FAST)
    composed, decomposed = "café-password", "café-password"
    out = tmp_path / "o.enc"
    crypto.encrypt_file(plain, out, composed, **FAST)
    assert crypto.decrypt_file(out, None, decomposed)  # the same text typed another way


def test_default_and_largest_parameters_work(tmp_path: Path) -> None:
    _, out, digest = _encrypt(tmp_path, b"hello", log2n=crypto.DEFAULT_LOG2N)
    assert crypto.decrypt_file(out, None, PASSWORD) == digest
    _, big, digest = _encrypt(tmp_path, b"hello", log2n=crypto.LOG2N_RANGE[1])
    assert crypto.decrypt_file(big, None, PASSWORD) == digest  # 256 MiB of key stretching
    with pytest.raises(EmlekError):
        _encrypt(tmp_path, b"x", log2n=19)
