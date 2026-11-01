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
from emlek.core.permissions import INTERACTIVE_ONLY, PERMISSIONS, Caller, Channel, require
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
    "max_sensitivity",
}


@pytest.mark.parametrize("operation", sorted(PERMISSIONS))
@pytest.mark.parametrize("channel", list(Channel))
def test_permission_matrix(operation: str, channel: Channel) -> None:
    allowed = channel in PERMISSIONS[operation]
    if allowed:
        require(Caller(channel, interactive=True), operation)
        if operation in INTERACTIVE_ONLY:  # a script or an AI is not a person at a terminal
            with pytest.raises(EmlekError) as refused:
                require(Caller(channel, interactive=False), operation)
            assert refused.value.code is ErrorCode.NOT_PERMITTED
        else:
            require(Caller(channel, interactive=False), operation)
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
    assert set(_tool_names(data_dir, read_only=False)) == {"save", "get", "search", "stats"}
    assert set(_tool_names(data_dir, read_only=True)) == {"get", "search", "stats"}


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
    }
    get_schema = tools["get"].input_schema
    assert get_schema["required"] == ["ref"] and set(get_schema["properties"]) == {"ref", "version"}
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
    return json.loads(text[text.index("{") :])


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
            assert names == {"get", "search", "stats"}
            blocked = await client.call_tool("save", {"body": "書けない"})
            assert blocked.is_error
            found = _payload(await client.call_tool("search", {"query": "共通語"}))
            assert found["result"]["total"] == 1 and found["result"]["withheld"] == 1
            assert "秘密" not in json.dumps(found, ensure_ascii=False)
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
