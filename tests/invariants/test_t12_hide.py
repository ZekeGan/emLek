"""T12: hiding is reversible and reaches reads, searches, summaries and derivatives."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from emlek.core import notice, purge, search, service, stats, tags, versions
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel


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


@pytest.mark.parametrize("channel", [Channel.MCP, Channel.MCP_READONLY])
def test_invalidated_content_is_withheld_from_ai(
    db: Database, caller: Caller, channel: Channel
) -> None:
    source = service.save(db, caller, body="合成來源")["ref"]
    derived = service.save(
        db,
        caller,
        body="紫色河馬",
        kind="ai_summary",
        source="紫色河馬",
        tags=["紫色河馬"],
        links=[{"ref": source, "relation": "summarizes"}],
    )["ref"]
    meta = service.save(
        db,
        caller,
        body="銀色斑馬",
        kind="inference",
        links=[{"ref": derived, "relation": "derived"}],
    )["ref"]
    versions.hide(db, caller, ref=source)
    ai = Caller(channel)
    for ref in (derived, meta):
        for version in (None, 1):
            result = service.get(db, ai, ref=ref, version=version, offset=1, max_chars=1)
            assert result["invalidated"] and result["content_withheld"]
            assert set(result) == {
                "ref",
                "revision_ref",
                "kind",
                "status",
                "invalidated",
                "content_withheld",
            }
    assert service.get(db, caller, ref=derived)["body"] == "紫色河馬"
    found = search.search(db, ai, facets=True)
    assert "紫色河馬" not in json.dumps(found, ensure_ascii=False)
    assert tags.find(db, ai, text="紫色河馬")["results"] == []
    assert "紫色河馬" not in json.dumps(tags.listing(db, ai), ensure_ascii=False)
    assert "紫色河馬" not in tags.popular_names(db.conn, "high")
    with pytest.raises(EmlekError):
        tags.listing(db, ai, tree="紫色河馬")
    service.save(db, caller, body="安全標籤基準", tags=["動物"])
    tags.link(db, caller, parent="動物", child="紫色河馬")
    expanded = search.search(db, ai, tags=["動物"], expand=True, facets=True)
    assert "紫色河馬" not in json.dumps(expanded, ensure_ascii=False)
    # A word must not find withheld content (that would read it back word by word).
    probe = search.search(db, ai, query="河馬 OR 斑馬 OR 合成")
    assert probe["total"] == 0 and probe.get("term_hits", {}).get("河馬", 0) == 0
    assert search.search(db, ai, tags=["紫色河馬"])["total"] == 0
    assert search.search(db, caller, query="河馬 OR 斑馬")["total"] == 2
    for compact in (False, True):
        result = search.search(
            db,
            ai,
            kinds=["ai_summary", "inference"],
            all_versions=True,
            current_only=True,
            compact=compact,
            limit=1,
        )
        assert result["total"] == 2 and result["returned_count"] == 1
        assert result["content_count"] == 0 and result["next_cursor"]
        assert "snippet" not in result["results"][0]
        assert "tags" not in result["results"][0]
        assert "source" not in result["results"][0]
        second = search.search(
            db,
            ai,
            kinds=["ai_summary", "inference"],
            all_versions=True,
            current_only=True,
            compact=compact,
            limit=1,
            cursor=result["next_cursor"],
        )
        assert second["results"][0]["content_withheld"]
    versions.unhide(db, caller, ref=source)
    assert service.get(db, ai, ref=derived)["body"] == "紫色河馬"
    assert service.get(db, ai, ref=meta)["body"] == "銀色斑馬"
    result = search.search(db, ai, query="河馬 OR 斑馬")
    assert result["returned_count"] == result["content_count"] == 2


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


@pytest.mark.parametrize("channel", [Channel.MCP, Channel.MCP_READONLY])
def test_ai_cannot_read_hidden_notes(db: Database, channel: Channel) -> None:
    """W03: hidden notes stay readable only in the user's own terminal."""
    person = Caller(Channel.CLI)
    ref = str(service.save(db, person, body="隠したい記録 京都")["ref"])
    versions.hide(db, person, ref=ref)
    ai = Caller(channel)
    with pytest.raises(EmlekError) as found:
        search.search(db, ai, query="京都", include_hidden=True)
    assert found.value.code == ErrorCode.NOT_PERMITTED
    with pytest.raises(EmlekError) as read:
        service.get(db, ai, ref=ref, include_hidden=True)
    assert read.value.code == ErrorCode.NOT_PERMITTED
    with pytest.raises(EmlekError) as plain:
        service.get(db, ai, ref=ref)
    assert plain.value.code == ErrorCode.NOT_FOUND
    assert ref in _refs(db, person, "京都", include_hidden=True)
    assert service.get(db, person, ref=ref, include_hidden=True)["hidden"] is True


def test_a_hidden_note_is_gone_for_an_ai(db: Database) -> None:
    """D103: unhide is the terminal's; every AI action on a hidden note answers as if deleted."""
    person = Caller(Channel.CLI)
    ai = Caller(Channel.MCP)
    notice.acknowledge(db.conn)  # past first consent, so only the hidden check can refuse
    secret = str(service.save(db, person, body="被隱藏的原文", tags=["秘密"])["ref"])
    visible = str(
        service.save(db, person, body="可見筆記", links=[{"ref": secret, "relation": "supports"}])[
            "ref"
        ]
    )
    versions.hide(db, person, ref=secret)
    attempts: tuple[Callable[[], object], ...] = (
        lambda: versions.unhide(db, ai, ref=secret),
        lambda: versions.hide(db, ai, ref=secret),
        lambda: service.amend(db, ai, ref=secret, body="改寫"),
        lambda: tags.set_tags(db, ai, ref=secret, add=["新標籤"]),
        lambda: purge.preview(db, ai, [secret]),
    )
    codes = []
    for attempt in attempts:
        with pytest.raises(EmlekError) as found:
            attempt()
        codes.append(found.value.code)
    assert codes[0] == ErrorCode.NOT_PERMITTED
    assert codes[1:] == [ErrorCode.NOT_FOUND] * 4
    assert service.get(db, ai, ref=visible)["links_out"] == []
    shown = service.get(db, person, ref=visible)["links_out"]
    assert [link["ref"] for link in shown] == [secret]
    assert purge.preview(db, person, [secret])["records"][0]["hidden"] is True
    assert versions.unhide(db, person, ref=secret)["changed"] is True


@pytest.mark.parametrize("channel", [Channel.MCP, Channel.MCP_READONLY])
def test_hidden_and_missing_look_the_same_to_an_ai(db: Database, channel: Channel) -> None:
    """Re-review of D103: wording, derivative lists, preview counts and stats must not let an AI
    tell a hidden note apart from one that never existed."""
    person = Caller(Channel.CLI)
    ai = Caller(channel)
    notice.acknowledge(db.conn)
    source = str(service.save(db, person, body="可見來源")["ref"])
    summary = str(
        service.save(
            db,
            person,
            body="隱藏的摘要",
            kind="ai_summary",
            links=[{"ref": source, "relation": "summarizes"}],
        )["ref"]
    )
    versions.hide(db, person, ref=summary)
    missing = "r99"

    def message(attempt: Callable[[], object]) -> tuple[ErrorCode, str]:
        with pytest.raises(EmlekError) as found:
            attempt()
        return found.value.code, str(found.value).replace(summary, "rX").replace(missing, "rX")

    assert message(lambda: service.get(db, ai, ref=summary)) == message(
        lambda: service.get(db, ai, ref=missing)
    )
    if channel is Channel.MCP:
        assert message(lambda: purge.preview(db, ai, [summary])) == message(
            lambda: purge.preview(db, ai, [missing])
        )
        shown = purge.preview(db, ai, [source])
        assert [item["ref"] for item in shown["records"]] == [source]
        assert shown["revisions"] == 1 and "links" not in shown and "tags_removed" not in shown
        assert summary not in json.dumps(versions.hide(db, ai, ref=source))
        versions.unhide(db, person, ref=source)
    counted = stats.stats(db, ai)
    assert "hidden_records" not in counted and counted["revisions"] == counted["records"] == 1
    assert stats.stats(db, person)["hidden_records"] == 1
