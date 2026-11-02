"""T13: supersedes / supports / amend behave as DESIGN "版本與連結語意" says."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

import pytest

from emlek.core import search, service, versions
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel


def _new(db: Database, caller: Caller, body: str, **links: Any) -> str:
    wanted = [{"ref": ref, "relation": rel} for ref, rel in links.items()]
    return str(service.save(db, caller, body=body, links=wanted)["ref"])


def _status(db: Database, caller: Caller, ref: str) -> str:
    return str(service.get(db, caller, ref=ref)["status"])


def test_a_chain_of_changed_minds_and_a_reaffirmation(db: Database, caller: Caller) -> None:
    a = _new(db, caller, "我覺得該留在日本")
    b = _new(db, caller, "我改變主意，應該回台灣", **{a: "supersedes"})
    c = _new(db, caller, "再想想，還是回台灣不對", **{b: "supersedes"})
    d = service.save(
        db,
        caller,
        body="結論：留在日本",
        links=[{"ref": c, "relation": "supersedes"}, {"ref": a, "relation": "supports"}],
    )["ref"]

    assert [_status(db, caller, r) for r in (a, b, c, d)] == [
        "reaffirmed",
        "superseded",
        "superseded",
        "current",
    ]
    assert [i["ref"] for i in service.get(db, caller, ref=a)["superseded_by"]] == [b]
    assert [i["ref"] for i in service.get(db, caller, ref=b)["superseded_by"]] == [c]
    assert {i["ref"]: i["relation"] for i in service.get(db, caller, ref=a)["linked_from"]} == {
        b: "supersedes",
        d: "supports",
    }
    out = service.get(db, caller, ref=d)["links_out"]
    assert {(i["ref"], i["relation"]) for i in out} == {(c, "supersedes"), (a, "supports")}


def test_current_only_drops_superseded_but_keeps_reaffirmed(db: Database, caller: Caller) -> None:
    a = _new(db, caller, "共通 旧説")
    b = _new(db, caller, "共通 新説", **{a: "supersedes"})
    _new(db, caller, "共通 再確認", **{b: "supersedes", a: "supports"})

    def refs(*, current_only: bool = False) -> set[str]:
        found = search.search(db, caller, query="共通", current_only=current_only)
        return {r["ref"] for r in found["results"]}

    assert b in refs()
    assert b not in refs(current_only=True)
    assert a in refs(current_only=True)  # reaffirmed
    by_ref = {r["ref"]: r["status"] for r in search.search(db, caller, query="共通")["results"]}
    assert by_ref[a] == "reaffirmed" and by_ref[b] == "superseded"


def test_a_hidden_superseder_no_longer_supersedes(db: Database, caller: Caller) -> None:
    old = _new(db, caller, "旧い考え")
    new = _new(db, caller, "新しい考え", **{old: "supersedes"})
    assert _status(db, caller, old) == "superseded"
    versions.hide(db, caller, ref=new)
    assert _status(db, caller, old) == "current"
    versions.unhide(db, caller, ref=new)
    assert _status(db, caller, old) == "superseded"


def test_bad_links_are_rejected_and_nothing_is_saved(db: Database, caller: Caller) -> None:
    first = _new(db, caller, "最初の記録")
    hidden = _new(db, caller, "隠す記録")
    versions.hide(db, caller, ref=hidden)
    cases: list[tuple[list[dict[str, Any]], ErrorCode]] = [
        ([{"ref": "r999", "relation": "supports"}], ErrorCode.NOT_FOUND),
        ([{"ref": hidden, "relation": "supports"}], ErrorCode.NOT_FOUND),
        ([{"ref": first, "relation": "likes"}], ErrorCode.INVALID_INPUT),
        ([{"ref": "不明"}], ErrorCode.INVALID_INPUT),
        ([{"ref": first, "relation": "supports", "extra": 1}], ErrorCode.INVALID_INPUT),
        ([{"ref": first}] * 21, ErrorCode.INVALID_INPUT),
    ]
    before = db.conn.execute("SELECT count(*) FROM records").fetchone()[0]
    for links, code in cases:
        with pytest.raises(EmlekError) as info:
            service.save(db, caller, body="新しい記録", links=links)
        assert info.value.code is code
    assert db.conn.execute("SELECT count(*) FROM records").fetchone()[0] == before


def test_a_record_cannot_link_to_itself_and_duplicates_are_idempotent(
    db: Database, caller: Caller
) -> None:
    first = _new(db, caller, "最初")
    with pytest.raises(EmlekError) as info:
        service.amend(db, caller, ref=first, body="修正版", links=[{"ref": first}])
    assert info.value.code is ErrorCode.INVALID_INPUT
    assert service.get(db, caller, ref=first)["version"] == 1  # the failed amend left no version

    second = service.save(
        db, caller, body="二番目", links=[{"ref": first, "relation": "supports"}] * 2
    )
    assert second["links_added"] == 1
    again = service.amend(
        db,
        caller,
        ref=second["ref"],
        body="二番目 修正",
        links=[{"ref": first, "relation": "supports"}],
    )
    assert again["links_added"] == 1  # a new revision is a new source, so it is a new link
    assert db.conn.execute("SELECT count(*) FROM links").fetchone()[0] == 2


def test_links_are_write_once(db: Database, caller: Caller) -> None:
    first = _new(db, caller, "最初")
    _new(db, caller, "二番目", **{first: "supports"})
    with pytest.raises(sqlite3.Error):
        db.conn.execute("UPDATE links SET relation = 'supersedes'")
    with pytest.raises(sqlite3.Error):
        db.conn.execute("DELETE FROM links")


def test_linked_from_is_capped_and_marked(db: Database, caller: Caller) -> None:
    target = _new(db, caller, "人気の記録")
    for i in range(versions.MAX_LINKED_FROM + 3):
        _new(db, caller, f"言及 {i}", **{target: "supplements"})
    got = service.get(db, caller, ref=target)
    assert len(got["linked_from"]) == versions.MAX_LINKED_FROM
    assert got["linked_from_truncated"] is True


def test_amend_carries_over_and_clears_fields(db: Database, caller: Caller) -> None:
    ref = str(
        service.save(
            db, caller, body="元の文", source="手帳", event_time="2026-03-05", kind="original"
        )["ref"]
    )
    kept = service.amend(db, caller, ref=ref, body="直した文")
    assert kept["version"] == 2
    latest = service.get(db, caller, ref=ref)
    assert (latest["event_time"], latest["source"], latest["kind"]) == (
        "2026-03-05",
        "手帳",
        "original",
    )
    assert service.get(db, caller, ref=f"{ref}.v1")["body"] == "元の文"  # history untouched

    service.amend(db, caller, ref=ref, body="日付と出典を消した", clear=["event_time", "source"])
    cleared = service.get(db, caller, ref=ref)
    assert cleared["event_time"] is None and cleared["source"] is None and cleared["version"] == 3

    service.amend(db, caller, ref=ref, body="日付を入れ直す", event_time="2026-04", source="メモ")
    final = service.get(db, caller, ref=ref)
    assert (final["event_time"], final["event_time_precision"]) == ("2026-04", "month")


def test_amend_refusals(db: Database, caller: Caller) -> None:
    ref = str(service.save(db, caller, body="元")["ref"])
    cases: list[tuple[dict[str, Any], ErrorCode]] = [
        ({"body": "元"}, ErrorCode.INVALID_INPUT),  # nothing changed
        ({"body": "新", "expected_version": 7}, ErrorCode.CONFLICT),
        ({"body": "新", "clear": ["body"]}, ErrorCode.INVALID_INPUT),
        ({"body": "新", "event_time_precision": "day"}, ErrorCode.INVALID_INPUT),
        ({"body": "  "}, ErrorCode.INVALID_INPUT),
    ]
    for kwargs, code in cases:
        with pytest.raises(EmlekError) as info:
            service.amend(db, caller, ref=ref, **kwargs)
        assert info.value.code is code
    with pytest.raises(EmlekError) as info:
        service.amend(db, caller, ref="r404", body="新")
    assert info.value.code is ErrorCode.NOT_FOUND
    assert service.amend(db, caller, ref=ref, body="新", expected_version=1)["version"] == 2

    versions.hide(db, caller, ref=ref)
    with pytest.raises(EmlekError) as info:
        service.amend(db, caller, ref=ref, body="さらに新")
    assert info.value.code is ErrorCode.CONFLICT


def test_read_only_callers_cannot_amend_or_hide(db: Database) -> None:
    ref = str(service.save(db, Caller(Channel.CLI), body="元")["ref"])
    readonly = Caller(Channel.MCP_READONLY)
    actions: list[Callable[[], object]] = [
        lambda: service.amend(db, readonly, ref=ref, body="新"),
        lambda: versions.hide(db, readonly, ref=ref),
        lambda: versions.unhide(db, readonly, ref=ref),
        lambda: service.save(db, readonly, body="新"),
    ]
    for action in actions:
        with pytest.raises(EmlekError) as info:
            action()
        assert info.value.code is ErrorCode.NOT_PERMITTED
