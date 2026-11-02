"""T12: hiding is reversible and reaches reads, searches, summaries and derivatives."""

from __future__ import annotations

import pytest

from emlek.core import search, service, versions
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller


def _refs(db: Database, caller: Caller, query: str, **kwargs: object) -> set[str]:
    return {r["ref"] for r in search.search(db, caller, query=query, **kwargs)["results"]}  # type: ignore[arg-type]


def test_hide_removes_from_search_and_get_and_unhide_brings_back(
    db: Database, caller: Caller
) -> None:
    ref = str(service.save(db, caller, body="隠したい記録 京都")["ref"])
    keep = str(service.save(db, caller, body="残す記録 京都")["ref"])
    assert _refs(db, caller, "京都") == {ref, keep}

    done = versions.hide(db, caller, ref=ref)
    assert done["changed"] is True and done["hidden"] is True
    assert _refs(db, caller, "京都") == {keep}
    assert ref in _refs(db, caller, "京都", include_hidden=True)
    with pytest.raises(EmlekError) as info:
        service.get(db, caller, ref=ref)
    assert info.value.code is ErrorCode.NOT_FOUND
    assert service.get(db, caller, ref=ref, include_hidden=True)["hidden"] is True

    back = versions.unhide(db, caller, ref=ref)
    assert back["changed"] is True
    assert _refs(db, caller, "京都") == {ref, keep}
    assert service.get(db, caller, ref=ref)["body"] == "隠したい記録 京都"


def test_hide_and_unhide_are_idempotent_and_keep_the_text(db: Database, caller: Caller) -> None:
    ref = str(service.save(db, caller, body="本文")["ref"])
    assert versions.unhide(db, caller, ref=ref)["changed"] is False
    assert versions.hide(db, caller, ref=ref)["changed"] is True
    assert versions.hide(db, caller, ref=ref)["changed"] is False
    versions.unhide(db, caller, ref=ref)
    assert service.get(db, caller, ref=ref)["body"] == "本文"
    with pytest.raises(EmlekError) as info:
        versions.hide(db, caller, ref="r404")
    assert info.value.code is ErrorCode.NOT_FOUND


def test_derived_records_become_invalid_while_their_source_is_hidden(
    db: Database, caller: Caller
) -> None:
    source = str(service.save(db, caller, body="元の日記")["ref"])
    summary = str(
        service.save(
            db,
            caller,
            body="日記の要約",
            kind="ai_summary",
            links=[{"ref": source, "relation": "summarizes"}],
        )["ref"]
    )
    meta = str(
        service.save(
            db,
            caller,
            body="要約からの推論",
            kind="inference",
            links=[{"ref": summary, "relation": "derived"}],
        )["ref"]
    )
    assert service.get(db, caller, ref=meta)["invalidated"] is False

    done = versions.hide(db, caller, ref=source)
    assert done["affected_derivatives"] == [summary, meta]
    assert service.get(db, caller, ref=summary)["invalidated"] is True
    assert service.get(db, caller, ref=meta)["invalidated"] is True  # transitive
    flagged = {
        r["ref"]: r["invalidated"] for r in search.search(db, caller, query="要約")["results"]
    }
    assert flagged[summary] is True

    versions.unhide(db, caller, ref=source)
    assert service.get(db, caller, ref=meta)["invalidated"] is False


def test_supersedes_and_supports_do_not_carry_hiding_down(db: Database, caller: Caller) -> None:
    old = str(service.save(db, caller, body="旧")["ref"])
    new = str(
        service.save(db, caller, body="新", links=[{"ref": old, "relation": "supersedes"}])["ref"]
    )
    done = versions.hide(db, caller, ref=old)
    assert done["affected_derivatives"] == []
    assert service.get(db, caller, ref=new)["invalidated"] is False


def test_hidden_records_are_not_counted_in_the_summary(db: Database, caller: Caller) -> None:
    refs = [
        str(service.save(db, caller, body=f"共通語 {i}", event_time="2026-05-01")["ref"])
        for i in range(versions_threshold() + 10)
    ]
    for ref in refs[:5]:
        versions.hide(db, caller, ref=ref)
    result = search.search(db, caller, query="共通語")
    assert result["total"] == len(refs) - 5
    assert result["summary"]["total"] == len(refs) - 5
    assert sum(result["summary"]["by_month"].values()) == len(refs) - 5
    assert result["withheld"] == 0  # hiding must not leak through the sensitivity counter


def versions_threshold() -> int:
    return search.AGGREGATE_THRESHOLD
