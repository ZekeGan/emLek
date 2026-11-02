"""T15: the sensitivity scan finds the obvious, leaves ordinary text alone and stays fast.

All samples are public test values or invented; nothing here is a real credential.
"""

from __future__ import annotations

import time

import pytest

from emlek.core import sensitivity as s

HIGH = {
    "aws": "key AKIAIOSFODNN7EXAMPLE here",
    "github": "token ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
    "slack": "xoxb-1234567890-abcdefghij",
    "openai": "sk-" + "abcdefghijklmnopqrstuvwxyz0123",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r",
    "pem": "-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----",
    "visa": "card 4111 1111 1111 1111 exp 12/30",
    "visa_dashes": "4111-1111-1111-1111",
    "visa_fullwidth": "４１１１　１１１１ １１１１ １１１１".replace("　", " "),
    "password_zh": "網站密碼：abc12345",
    "password_en": "password = hunter2",
    "password_ja": "パスワードは secret99",
    "pin_ja": "暗証番号: 4821",
    "recovery": "復原碼: ABCD-EFGH-JKLM",
    "bank": "口座番号 12345678",
}

MEDIUM = {
    "tw_mobile": "小明的電話 0912-345-678",
    "tw_mobile_plain": "call 0912345678",
    "jp_mobile": "090-1234-5678",
    "landline": "TEL 03-1234-5678",
    "intl": "+81 90 1234 5678",
    "postal": "〒100-0001",
    "address_ja": "住所：東京都千代田区千代田1-1",
    "address_tw": "住址 台北市中正區重慶南路一段122號",
    "birthday": "生日：1990-03-05",
    "birthday_md": "我的生日是3月5日",
    "email": "contact me at someone@example.com",
    "tw_id": "A123456789",
    "passport": "passport no. X12345678",
}

CLEAN = {
    "plain": "今天去了淺草寺，吃了拉麵。",
    "forgot_password": "我忘記信箱密碼了，好煩，等一下去重設。",
    "ja": "来週の会議は火曜日です。",
    "date": "2026-11-02 に会った",
    "version": "version 1.2.3 released",
    "not_luhn": "number 1234 5678 9012 3456",
    "long_digits": "order 20261102123456789012345678901234567890",
    "name_only": "小明明天要來",
    "english": "please address the issue before friday",
    "bad_tw_id": "A123456788",
}


@pytest.mark.parametrize("name", sorted(HIGH))
def test_high_risk_samples_are_found(name: str) -> None:
    level, categories = s.assess(HIGH[name])
    assert level == "high", (name, categories)


@pytest.mark.parametrize("name", sorted(MEDIUM))
def test_medium_samples_are_found(name: str) -> None:
    level, categories = s.assess(MEDIUM[name])
    assert level == "medium", (name, categories)


@pytest.mark.parametrize("name", sorted(CLEAN))
def test_ordinary_text_is_left_alone(name: str) -> None:
    level, categories = s.assess(CLEAN[name])
    assert level == "none", (name, categories)


def test_the_strongest_level_wins_and_declared_levels_only_raise() -> None:
    assert s.assess("0912-345-678 and AKIAIOSFODNN7EXAMPLE")[0] == "high"
    assert s.assess("今天天氣很好", declared="medium")[0] == "medium"
    assert s.assess("今天天氣很好", declared="high")[0] == "high"
    assert s.assess("密碼：abc12345", declared="none")[0] == "high"  # a low claim cannot lower it


def test_hits_carry_categories_never_the_text() -> None:
    secret = "AKIAIOSFODNN7EXAMPLE"
    hits = s.scan(f"x {secret} y")
    assert [h.category for h in hits] == ["api_key"]
    assert secret not in repr(hits)


def test_taiwan_id_checksum_and_luhn_helpers() -> None:
    assert s.tw_id_ok("A123456789") and not s.tw_id_ok("A123456788")
    assert s.luhn_ok("4111111111111111") and not s.luhn_ok("4111111111111112")


@pytest.mark.parametrize("filler", ["x", "1", "1-", " ", "あ", "a@", "0"])
def test_a_one_mebibyte_note_is_scanned_quickly(filler: str) -> None:
    text = filler * ((1 << 20) // len(filler.encode("utf-8")))
    started = time.perf_counter()
    s.scan(text)
    assert time.perf_counter() - started < 5
