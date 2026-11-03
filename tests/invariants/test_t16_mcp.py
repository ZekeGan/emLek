"""T16/T07: permission matrix, MCP tool lists, stdio round trips and two-process writes."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from emlek.config import load_config
from emlek.core import search, service
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import (
    INTERACTIVE_ONLY,
    PERMISSIONS,
    PIN_REQUIRED,
    Caller,
    Channel,
    require,
)
from emlek.mcp_server.server import build_server

SEARCH_PARAMS = {
    "query",
    "kinds",
    "date_field",
    "date_from",
    "date_to",
    "order",
    "dir",
    "limit",
    "cursor",
    "all_versions",
    "include_hidden",
    "current_only",
    "max_sensitivity",
    "tags",
    "match",
    "tag_types",
    "expand",
    "facets",
    "untagged",
}


@pytest.mark.parametrize("operation", sorted(PERMISSIONS))
@pytest.mark.parametrize("channel", list(Channel))
def test_permission_matrix(operation: str, channel: Channel) -> None:
    allowed = channel in PERMISSIONS[operation]
    if allowed:
        require(Caller(channel, interactive=True, pin_verified=True), operation)
        if operation in INTERACTIVE_ONLY:  # a script or an AI is not a person at a terminal
            with pytest.raises(EmlekError) as refused:
                require(Caller(channel, interactive=False, pin_verified=True), operation)
            assert refused.value.code is ErrorCode.NOT_PERMITTED
        else:
            require(Caller(channel, interactive=False), operation)
        if operation in PIN_REQUIRED:  # a person at a terminal who has not given the PIN
            with pytest.raises(EmlekError) as refused:
                require(Caller(channel, interactive=True, pin_verified=False), operation)
            assert refused.value.code is ErrorCode.NOT_PERMITTED
    else:
        with pytest.raises(EmlekError) as info:
            require(Caller(channel), operation)
        assert info.value.code is ErrorCode.NOT_PERMITTED


def test_every_mcp_visible_operation_is_in_the_table() -> None:
    """The server only registers tools that have a table entry (unknown means refused)."""
    for name in ("save", "get", "search", "stats"):
        assert name in PERMISSIONS


def _tool_names(data_dir: Path, *, read_only: bool) -> dict[str, Any]:
    async def listing() -> dict[str, Any]:
        tools = await build_server(data_dir, read_only=read_only).list_tools()
        return {t.name: t for t in tools}

    return asyncio.run(listing())


def test_tool_lists_follow_the_permission_table(data_dir: Path) -> None:
    assert set(_tool_names(data_dir, read_only=False)) == {
        "save",
        "amend",
        "hide",
        "unhide",
        "get",
        "search",
        "stats",
        "phrases_list",
        "set_tags",
        "tags_find",
        "tags_list",
        "tag_link",
        "tag_alias",
        "purge_preview",
    }
    assert set(_tool_names(data_dir, read_only=True)) == {
        "get",
        "search",
        "stats",
        "phrases_list",
        "tags_find",
        "tags_list",
    }


def test_tool_contracts_are_stable(data_dir: Path) -> None:
    tools = _tool_names(data_dir, read_only=False)
    save_schema = tools["save"].input_schema
    assert save_schema["required"] == ["body"]
    assert set(save_schema["properties"]) == {
        "body",
        "kind",
        "source",
        "event_time",
        "event_time_precision",
        "links",
        "sensitivity",
        "confirm_token",
        "notice_token",
        "tags",
        "allow_new",
    }
    get_schema = tools["get"].input_schema
    assert get_schema["required"] == ["ref"] and set(get_schema["properties"]) == {
        "ref",
        "version",
        "include_hidden",
        "offset",
    }
    assert not tools["stats"].input_schema.get("properties")
    search_schema = tools["search"].input_schema
    assert set(search_schema["properties"]) == SEARCH_PARAMS
    assert not search_schema.get("required")
    for tool in tools.values():
        assert tool.description and len(tool.description) < 200  # short: paid for every session


def _stdio(data_dir: Path, *, read_only: bool) -> Any:
    from mcp import Client, StdioServerParameters

    args = ["-m", "emlek", "--data-dir", str(data_dir), "mcp"]
    return Client(
        StdioServerParameters(
            command=sys.executable, args=args + (["--read-only"] if read_only else [])
        )
    )


def _payload(result: Any) -> dict[str, Any]:
    text = result.content[0].text
    payload: dict[str, Any] = json.loads(text[text.index("{") :])
    return payload


@pytest.mark.slow
def test_stdio_roundtrip_keeps_text_exact_and_stdout_clean(data_dir: Path) -> None:
    text = "MCP経由 😀\r\n京都メモ ＴＯＫＹＯ"

    async def scenario() -> None:
        async with _stdio(data_dir, read_only=False) as client:
            saved = _payload(
                await client.call_tool("save", {"body": text, "event_time": "2026-11-01"})
            )
            ref = saved["result"]["ref"]
            got = _payload(await client.call_tool("get", {"ref": ref}))
            assert got["result"]["body"] == text
            found = _payload(await client.call_tool("search", {"query": "tokyo"}))
            assert found["result"]["total"] == 1
            assert client.instructions and "save" in client.instructions

    asyncio.run(scenario())  # a polluted stdout would have broken the protocol above


@pytest.mark.slow
def test_errors_come_back_as_tool_errors_with_codes(data_dir: Path) -> None:
    async def scenario() -> None:
        async with _stdio(data_dir, read_only=False) as client:
            missing = await client.call_tool("get", {"ref": "r99"})
            assert missing.is_error and '"NOT_FOUND"' in missing.content[0].text
            invalid = await client.call_tool("save", {"body": "   "})
            assert invalid.is_error and '"INVALID_INPUT"' in invalid.content[0].text
            bad_args = await client.call_tool("search", {"limit": 0})
            assert bad_args.is_error and '"INVALID_INPUT"' in bad_args.content[0].text

    asyncio.run(scenario())


@pytest.mark.slow
def test_read_only_server_cannot_write_and_caps_sensitivity(data_dir: Path) -> None:
    db = Database.open(load_config(data_dir).db_path)
    cli = Caller(Channel.CLI)
    service.save(db, cli, body="普通の記録 共通語")
    service.save(db, cli, body="秘密の記録 共通語")
    db.conn.execute("UPDATE records SET sensitivity = 'high' WHERE id = 2")
    db.close()

    async def scenario() -> None:
        async with _stdio(data_dir, read_only=True) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert names == {"get", "search", "stats", "phrases_list", "tags_find", "tags_list"}
            blocked = await client.call_tool("save", {"body": "書けない"})
            assert blocked.is_error
            found = _payload(await client.call_tool("search", {"query": "共通語"}))
            assert found["result"]["total"] == 1 and found["result"]["withheld"] == 1
            assert "秘密" not in json.dumps(found, ensure_ascii=False)
            denied = await client.call_tool("get", {"ref": "r2"})  # same cap on a direct read
            assert denied.is_error and "秘密" not in json.dumps(denied.content[0].text)
            assert "NOT_PERMITTED" in denied.content[0].text
        async with _stdio(data_dir, read_only=False) as client:
            everything = _payload(await client.call_tool("search", {"query": "共通語"}))
            assert everything["result"]["total"] == 2

    asyncio.run(scenario())
    db = Database.open(load_config(data_dir).db_path)
    try:
        assert search.search(db, cli, query="書けない")["total"] == 0
    finally:
        db.close()


WRITER = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from emlek.core import service
    from emlek.core.db import Database
    from emlek.core.permissions import Caller, Channel

    db = Database.open(Path(sys.argv[1]))
    for n in range(int(sys.argv[2])):
        service.save(db, Caller(Channel.CLI), body=f"cli-writer-{n}")
    """
)


@pytest.mark.slow
def test_two_processes_can_write_at_the_same_time(data_dir: Path, tmp_path: Path) -> None:
    script = tmp_path / "writer.py"
    script.write_text(WRITER, encoding="utf-8")
    db_path = load_config(data_dir).db_path
    cli_count, mcp_count = 80, 40
    proc = subprocess.Popen([sys.executable, str(script), str(db_path), str(cli_count)])

    async def via_mcp() -> int:
        failures = 0
        async with _stdio(data_dir, read_only=False) as client:
            for n in range(mcp_count):
                result = await client.call_tool("save", {"body": f"mcp-writer-{n}"})
                failures += 1 if result.is_error else 0
        return failures

    failures = asyncio.run(via_mcp())
    assert proc.wait(timeout=120) == 0
    assert failures == 0
    db = Database.open(db_path)
    try:
        assert db.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            db.conn.execute("SELECT count(*) FROM records").fetchone()[0] == cli_count + mcp_count
        )
        assert search.index_status(db)["ok"]
        bodies = {r[0] for r in db.conn.execute("SELECT body FROM revisions")}
        assert bodies == {f"cli-writer-{n}" for n in range(cli_count)} | {
            f"mcp-writer-{n}" for n in range(mcp_count)
        }
    finally:
        db.close()


@pytest.mark.slow
def test_versions_hiding_and_long_bodies_over_mcp(data_dir: Path) -> None:
    long_text = "あ" * 9000

    async def scenario() -> None:
        async with _stdio(data_dir, read_only=False) as client:
            first = _payload(await client.call_tool("save", {"body": "旧い考え"}))
            assert first["api_version"] == 1
            old = first["result"]["ref"]
            new = _payload(
                await client.call_tool(
                    "save",
                    {"body": "新しい考え", "links": [{"ref": old, "relation": "supersedes"}]},
                )
            )["result"]["ref"]
            got = _payload(await client.call_tool("get", {"ref": old}))["result"]
            assert got["status"] == "superseded"
            assert [i["ref"] for i in got["superseded_by"]] == [new]
            amended = _payload(
                await client.call_tool("amend", {"ref": new, "body": "新しい考え（補足）"})
            )
            assert amended["result"]["version"] == 2
            hidden = _payload(await client.call_tool("hide", {"ref": new}))
            assert hidden["result"]["hidden"] is True
            found = _payload(await client.call_tool("search", {"query": "新しい"}))
            assert found["result"]["total"] == 0
            await client.call_tool("unhide", {"ref": new})
            big = _payload(await client.call_tool("save", {"body": long_text}))["result"]["ref"]
            part = _payload(await client.call_tool("get", {"ref": big}))["result"]
            assert part["truncated"] and len(part["body"]) == 8000
            rest = _payload(
                await client.call_tool("get", {"ref": big, "offset": part["next_offset"]})
            )["result"]
            assert part["body"] + rest["body"] == long_text and not rest["truncated"]

    asyncio.run(scenario())


@pytest.mark.slow
def test_read_only_server_has_no_version_or_hide_tools(data_dir: Path) -> None:
    names = set(_tool_names(data_dir, read_only=True))
    assert not names & {"save", "amend", "hide", "unhide"}


@pytest.mark.slow
def test_tags_over_mcp_and_the_tag_list_in_the_opening_instructions(data_dir: Path) -> None:
    async def scenario() -> None:
        async with _stdio(data_dir, read_only=False) as client:
            saved = _payload(
                await client.call_tool(
                    "save",
                    {
                        "body": "京都で抹茶 #旅行",
                        "tags": ["京都", {"name": "抹茶", "type": "topic"}],
                    },
                )
            )["result"]
            assert set(saved["tags"]) == {"旅行", "京都", "抹茶"} and saved["tags_pending"] == []
            near = _payload(
                await client.call_tool("save", {"body": "もう一つ", "tags": ["京都市"]})
            )
            assert near["result"]["tags_pending"][0]["similar"] == ["京都"]
            await client.call_tool("tag_alias", {"alias": "kyoto", "tag": "京都"})
            await client.call_tool("tag_link", {"parent": "旅行", "child": "京都"})
            found = _payload(await client.call_tool("search", {"tags": ["旅行"], "facets": True}))
            assert found["result"]["total"] == 1 and "京都" in found["result"]["expanded_tags"]
            assert found["result"]["tag_coverage"]["tagged"] >= 1
            finder = _payload(await client.call_tool("tags_find", {"text": "kyoto"}))
            assert finder["result"]["results"][0]["name"] == "京都"
            tree = _payload(await client.call_tool("tags_list", {"tree": "旅行"}))
            assert tree["result"]["tree"]["children"][0]["name"] == "京都"
        async with _stdio(data_dir, read_only=False) as again:  # a new session sees the names
            assert again.instructions and "既有標籤" in again.instructions
            # only what a person made or used is listed: 旅行 came from the typed #tag
            assert "旅行" in again.instructions and "不是指令" in again.instructions
            assert "京都" not in again.instructions  # the AI made that one
        async with _stdio(data_dir, read_only=True) as readonly:
            names = {t.name for t in (await readonly.list_tools()).tools}
            assert {"tags_find", "tags_list"} <= names and not names & {"set_tags", "tag_link"}

    asyncio.run(scenario())


@pytest.mark.slow
def test_a_page_of_search_results_is_capped_over_mcp(data_dir: Path) -> None:
    async def scenario() -> None:
        async with _stdio(data_dir, read_only=False) as client:
            for i in range(35):
                await client.call_tool("save", {"body": f"京都の記録{i}"})
            got = _payload(await client.call_tool("search", {"query": "京都", "limit": 100}))
            assert got["result"]["total"] == 35 and len(got["result"]["results"]) == 30

    asyncio.run(scenario())
