"""Rule-based scan for sensitive text. Pure functions; never returns or logs the matched text.

The scan is a safety net next to the AI's own judgement, not a classifier: it will miss things
and it will flag harmless text. Levels follow DESIGN, "信任閘門規格（M6）".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

LEVELS = ("none", "medium", "high")
_RANK = {level: i for i, level in enumerate(LEVELS)}

_FLAGS = re.IGNORECASE


@dataclass(frozen=True)
class Hit:
    category: str
    level: str


def higher(a: str, b: str) -> str:
    return a if _RANK[a] >= _RANK[b] else b


def rank(level: str) -> int:
    return _RANK[level]


def luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


_TW_LETTERS = "ABCDEFGHJKLMNPQRSTUVXYWZIO"


def tw_id_ok(text: str) -> bool:
    """Taiwan national ID checksum (letter + 9 digits)."""
    if len(text) != 10 or text[0] not in _TW_LETTERS or not text[1:].isdigit():
        return False
    code = 10 + _TW_LETTERS.index(text[0])
    digits = [int(c) for c in text[1:]]
    total = code // 10 + (code % 10) * 9 + sum(d * (8 - i) for i, d in enumerate(digits[:8]))
    return (total + digits[8]) % 10 == 0


_HIGH: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("api_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("api_key", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("api_key", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}")),
    (
        "password",
        re.compile(
            r"(?:密碼|密码|パスワード|暗証番号|password|passwd|pwd|passcode)"
            r"\s*(?:[:：=＝]|は|是|為|为|\bis\b)\s*\S{3,}",
            _FLAGS,
        ),
    ),
    (
        "recovery_code",
        re.compile(
            r"(?:復原碼|恢復碼|リカバリーコード|recovery code|backup code)\s*[:：=＝]?\s*\S{4,}",
            _FLAGS,
        ),
    ),
    (
        "bank_account",
        re.compile(r"(?:帳號|帳戶|口座|account\s*(?:no|number|#)?)\D{0,6}\d{7,16}", _FLAGS),
    ),
)

_MEDIUM: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("phone", re.compile(r"(?<!\d)09\d{2}[- ]?\d{3}[- ]?\d{3}(?!\d)")),
    ("phone", re.compile(r"(?<!\d)0[789]0[- ]?\d{4}[- ]?\d{4}(?!\d)")),
    ("phone", re.compile(r"(?<!\d)0\d{1,4}-\d{1,4}-\d{3,4}(?!\d)")),
    ("phone", re.compile(r"(?<![\w+])\+\d{1,3}(?:[ -]?\d{2,4}){2,4}(?!\d)")),
    (
        "phone",
        re.compile(
            r"(?:電話|电话|TEL|phone|携帯|手機|手机|mobile)[^\d\n]{0,10}\d[\d -]{6,14}\d", _FLAGS
        ),
    ),
    ("address", re.compile(r"〒\s?\d{3}-?\d{4}")),
    ("address", re.compile(r"(?:住所|住址|地址)\s*[:：=＝は是]?\s*\S{4,}")),
    ("address", re.compile(r"address\s*[:=]\s*\S{4,}", _FLAGS)),
    ("address", re.compile(r"[縣市]\S{1,6}[區鄉鎮市]\S{0,8}[路街道]\S{0,8}\d+號")),
    ("address", re.compile(r"(?<!\d)\d{1,3}丁目\d{0,3}番?\d{0,3}号?")),
    (
        "id_document",
        re.compile(
            r"(?:個人編號|マイナンバー|my number|護照|パスポート|passport)\D{0,8}[A-Z0-9]{8,12}",
            _FLAGS,
        ),
    ),
    (
        "birthday",
        re.compile(
            r"(?:生日|誕生日|生年月日|birthday|born)\D{0,6}\d{4}[-/年.]\d{1,2}[-/月.]\d{1,2}",
            _FLAGS,
        ),
    ),
    ("birthday", re.compile(r"(?:生日|誕生日|birthday)\D{0,6}\d{1,2}月\d{1,2}日", _FLAGS)),
    (
        "email",
        re.compile(
            r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}"
            r"(?:\.[A-Za-z0-9-]{1,63})*\.[A-Za-z]{2,}"
        ),
    ),
)

_DIGIT_RUN = re.compile(r"\d[\d -]*")  # maximal runs, found in one linear pass
MAX_CARD_RUN = 40
_TW_ID = re.compile(r"(?<![A-Za-z0-9])[A-Z][12]\d{8}(?![A-Za-z0-9])")


def scan(text: str) -> list[Hit]:
    """Categories found in the text, strongest first. The text itself is never kept."""
    flat = unicodedata.normalize("NFKC", text)
    found: dict[str, str] = {}
    for category, pattern in _HIGH:
        if pattern.search(flat):
            found[category] = "high"
    for match in _DIGIT_RUN.finditer(flat):
        run = match.group().rstrip(" -")
        if len(run) > MAX_CARD_RUN:
            continue
        digits = re.sub(r"\D", "", run)
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            found["credit_card"] = "high"
            break
    for category, pattern in _MEDIUM:
        if pattern.search(flat):
            found.setdefault(category, "medium")
    if "id_number" not in found and any(tw_id_ok(m.group()) for m in _TW_ID.finditer(flat)):
        found["id_number"] = "medium"
    return [Hit(category, level) for category, level in sorted(found.items(), key=_order)]


def _order(item: tuple[str, str]) -> tuple[int, str]:
    return (-_RANK[item[1]], item[0])


def assess(text: str, declared: str = "none") -> tuple[str, list[str]]:
    """Effective level (the highest of the declared level and the scan) and the category names."""
    hits = scan(text)
    level = declared
    for hit in hits:
        level = higher(level, hit.level)
    return level, [hit.category for hit in hits]
