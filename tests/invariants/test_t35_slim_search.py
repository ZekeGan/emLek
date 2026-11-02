"""T35: a compact search answer leaves out default values; a search names the tags that have
the same name or alias as a query word, counting visible records only."""

from __future__ import annotations

from emlek.core import search, service, versions
from emlek.core import tags as tagmod
from emlek.core.db import Database
from emlek.core.permissions import Caller


def test_compact_results_leave_out_defaults_and_keep_the_rest(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="京都でお茶を飲んだ", event_time="2026-10-01")
    service.save(db, caller, body="京都のメモ（日付なし）")
    full = search.search(db, caller, query="京都")["results"]
    slim = search.search(db, caller, query="京都", compact=True)["results"]
    assert len(full) == len(slim) == 2
    for before, after in zip(full, slim, strict=True):
        for key in ("hidden", "sensitivity", "source", "invalidated", "status", "latest_version"):
            assert key not in after
        assert after["ref"] == before["ref"] and after["snippet"] == before["snippet"]
        assert after["revision_ref"] == before["revision_ref"]
        assert len(str(after)) < len(str(before))
    undated = next(r for r in slim if "event_time" not in r)
    assert "event_time_precision" not in undated


def test_compact_keeps_what_differs_from_the_default(db: Database, caller: Caller) -> None:
    old = service.save(db, caller, body="京都は好き")["ref"]
    service.save(db, caller, body="京都は普通", links=[{"ref": old, "relation": "supersedes"}])
    service.amend(db, caller, ref=old, body="京都は好きだった")
    got = {r["ref"]: r for r in search.search(db, caller, query="京都", compact=True)["results"]}
    assert got[old]["status"] == "superseded"
    assert got[old]["matched_version"] == 2 and "latest_version" not in got[old]
    older = search.search(db, caller, query="好き", all_versions=True, compact=True)["results"]
    assert any(r["matched_version"] == 1 and r["latest_version"] == 2 for r in older)


def test_matching_tags_name_the_tag_a_query_word_is(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="京都でお茶", tags=["京都"])
    service.save(db, caller, body="京都駅", tags=["京都"])
    tagmod.alias(db, caller, alias_text="kyoto", tag="京都")
    got = search.search(db, caller, query="お茶 OR kyoto")
    assert got["matching_tags"] == [{"name": "京都", "records": 2}]
    assert "matching_tags" not in search.search(db, caller, query="お茶")  # no tag called that
    assert "matching_tags" not in search.search(db, caller, query="京都", tags=["京都"])


def test_matching_tags_ignore_hidden_records(db: Database, caller: Caller) -> None:
    ref = service.save(db, caller, body="秘密の旅", tags=["秘密旅行"])["ref"]
    versions.hide(db, caller, ref=ref)
    assert "matching_tags" not in search.search(db, caller, query="秘密旅行 OR 旅")
