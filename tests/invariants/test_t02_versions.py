"""T02: changing a record only ever adds the next version; earlier versions never move."""

from __future__ import annotations

import random

from hypothesis import given, settings
from hypothesis import strategies as st

from emlek.core import search, service, versions
from emlek.core.db import Database
from emlek.core.permissions import Caller

BODIES = st.text(min_size=1, max_size=200).filter(lambda t: t.strip() and "\x00" not in t)


@settings(max_examples=40, deadline=None)
@given(st.lists(BODIES, min_size=2, max_size=8, unique=True))
def test_every_amend_adds_the_next_version_and_leaves_the_rest_alone(bodies: list[str]) -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from emlek.config import load_config
    from emlek.core.permissions import Channel
    from emlek.core.vault import init_vault

    caller = Caller(Channel.CLI)
    with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        init_vault(caller, Path(tmp) / "vault")
        db = Database.open(load_config(Path(tmp) / "vault").db_path)
        try:
            ref = str(service.save(db, caller, body=bodies[0], event_time="2026-01-01")["ref"])
            for number, body in enumerate(bodies[1:], 2):
                assert service.amend(db, caller, ref=ref, body=body)["version"] == number
            for number, body in enumerate(bodies, 1):
                got = service.get(db, caller, ref=f"{ref}.v{number}")
                assert got["body"] == body and got["version"] == number
            assert service.get(db, caller, ref=ref)["body"] == bodies[-1]
            assert search.index_status(db)["ok"]
        finally:
            db.close()


def test_the_index_follows_amends_and_hiding(db: Database, caller: Caller) -> None:
    """T08 (M5 part): hide, unhide and amend keep the index equal to the data."""
    rng = random.Random(3)
    refs = [str(service.save(db, caller, body=f"記録 {i} 京都")["ref"]) for i in range(12)]
    for step in range(30):
        ref = rng.choice(refs)
        action = rng.choice(["hide", "unhide", "amend"])
        if action == "amend":
            if db.conn.execute(
                "SELECT hidden FROM records WHERE id = ?", (int(ref[1:]),)
            ).fetchone()[0]:
                continue  # a hidden record cannot be amended (covered in T13)
            service.amend(db, caller, ref=ref, body=f"改訂 {step} 京都 {rng.random()}")
        elif action == "hide":
            versions.hide(db, caller, ref=ref)
        else:
            versions.unhide(db, caller, ref=ref)
        assert search.index_status(db)["ok"]
    visible = db.conn.execute("SELECT count(*) FROM records WHERE hidden = 0").fetchone()[0]
    assert search.search(db, caller, query="京都", limit=100)["total"] == visible
    shown = search.search(db, caller, query="京都", include_hidden=True, limit=100)["total"]
    assert shown == len(refs)
