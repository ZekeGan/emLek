"""T03/T04 (storage part): text comes back exactly as saved, normalized copy is separate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from emlek.core import service
from emlek.core.db import Database
from emlek.core.permissions import Caller, Channel

EXAMPLES = [
    "日本語のテスト",
    "emoji 😀 👨‍👩‍👧 🇯🇵",
    "é (組合字元) vs é",
    "line1\r\nline2\nline3\r",
    "﻿BOM 在開頭",
    "Ｆｕｌｌｗｉｄｔｈ ＡＢＣ １２３",
    "tab\tand  double  space",
    "繁體字與简体字",
    "  前後有空白  ",
]


@pytest.mark.parametrize("text", EXAMPLES)
def test_examples_come_back_byte_identical(db: Database, caller: Caller, text: str) -> None:
    saved = service.save(db, caller, body=text)
    got = service.get(db, caller, ref=saved["ref"])
    assert got["body"].encode("utf-8") == text.encode("utf-8")


@settings(max_examples=150, deadline=None)
@given(
    st.text(
        alphabet=st.characters(blacklist_categories=["Cs"], blacklist_characters="\x00"),
        min_size=1,
        max_size=500,
    ).filter(lambda s: s.strip() != "")
)
def test_any_unicode_roundtrips(shared_db: Database, text: str) -> None:
    cli = Caller(Channel.CLI)
    saved = service.save(shared_db, cli, body=text)
    got = service.get(shared_db, cli, ref=saved["ref"])
    assert got["body"] == text


def test_search_copy_is_separate_from_original(db: Database, caller: Caller) -> None:
    text = "Ｒａｍｅｎ ＴＯＫＹＯ"
    service.save(db, caller, body=text)
    body, norm = db.conn.execute("SELECT body, body_norm FROM revisions").fetchone()
    assert body == text
    assert norm == "ramen tokyo"


def test_cli_roundtrip_survives_a_cp950_environment(data_dir: Path) -> None:
    """Pipes on Chinese Windows default to cp950; the CLI must still read and write UTF-8."""
    text = "﻿日本語😀\r\n第二行\r\n"
    env = {**os.environ, "PYTHONIOENCODING": "cp950", "PYTHONUTF8": "0"}
    base = [sys.executable, "-m", "emlek", "--data-dir", str(data_dir), "--json"]
    saved = subprocess.run(
        [*base, "save", "--body-file", "-"],
        input=text.encode("utf-8"),
        capture_output=True,
        env=env,
        check=True,
    )
    ref = json.loads(saved.stdout.decode("utf-8"))["result"]["ref"]
    got = subprocess.run([*base, "get", ref], capture_output=True, env=env, check=True)
    assert json.loads(got.stdout.decode("utf-8"))["result"]["body"] == text
