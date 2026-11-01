"""One table decides which entry points may call which operation.

Adapters (CLI, MCP) never decide permissions themselves; they only build a Caller.
Unknown operations are refused (fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from emlek.core.errors import EmlekError, ErrorCode


class Channel(StrEnum):
    CLI = "cli"
    MCP = "mcp"
    MCP_READONLY = "mcp-readonly"


@dataclass(frozen=True)
class Caller:
    channel: Channel
    interactive: bool = False


_CLI = frozenset({Channel.CLI})
_ANY = frozenset({Channel.CLI, Channel.MCP, Channel.MCP_READONLY})
_WRITERS = frozenset({Channel.CLI, Channel.MCP})

PERMISSIONS: dict[str, frozenset[Channel]] = {
    "init": _CLI,
    "doctor": _CLI,
    "save": _WRITERS,
    "get": _ANY,
    "search": _ANY,
    "reindex": _CLI,
}


def require(caller: Caller, operation: str) -> None:
    allowed = PERMISSIONS.get(operation, frozenset())
    if caller.channel not in allowed:
        raise EmlekError(ErrorCode.NOT_PERMITTED, f"此入口不能執行 {operation}")
