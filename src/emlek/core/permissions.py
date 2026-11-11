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
    pin_verified: bool = False  # set by the CLI only after the PIN was checked in this run


_CLI = frozenset({Channel.CLI})
_ANY = frozenset({Channel.CLI, Channel.MCP, Channel.MCP_READONLY})
_WRITERS = frozenset({Channel.CLI, Channel.MCP})

PERMISSIONS: dict[str, frozenset[Channel]] = {
    "init": _CLI,
    "doctor": _CLI,
    "save": _WRITERS,
    "amend": _WRITERS,
    "hide": _WRITERS,
    "unhide": _CLI,  # D103: restoring is the user's; to an AI a hidden note is gone
    "get": _ANY,
    "read_hidden": _CLI,  # W03: hidden notes are read only in the user's own terminal
    "search": _ANY,
    "reindex": _CLI,
    "mcp": _CLI,
    "stats": _ANY,
    "backup": _CLI,
    "backup_encrypt": _CLI,
    "restore": _CLI,
    "export": _CLI,
    "phrases_list": _ANY,
    "phrase_list": _CLI,
    "phrase_add": _CLI,
    "phrase_set": _CLI,
    "phrase_remove": _CLI,
    "notice_status": _CLI,
    "notice_enable": _CLI,
    "start": _WRITERS,
    "sensitivity_set": _CLI,
    "pin_set": _CLI,
    "pin_change": _CLI,
    "pin_reset": _CLI,
    "set_tags": _WRITERS,
    "tags_find": _ANY,
    "tags_list": _ANY,
    "tag_link": _WRITERS,
    "tag_alias": _WRITERS,
    "tag_merge": _CLI,
    "tag_remove": _CLI,
    "tags_audit": _CLI,
    "tags_backfill_preview": _CLI,
    "tags_backfill_apply": _CLI,
    "import_preview": _CLI,
    "import_apply": _CLI,
    "import_apply_high": _CLI,
    "import_undo": _CLI,
    "import_list": _CLI,
    "purge_preview": _WRITERS,
    "purge": _CLI,
    "purge_finish": _CLI,
    "cleanup_preview": _CLI,
    "cleanup_apply": _CLI,
    "auto_policy": _WRITERS,
    "auto_config": _CLI,
    "auto_hide": _CLI,
    "recent": _CLI,
}

# Operations that only a person at a real terminal may run (stdin, stdout and stderr are all
# terminals).
INTERACTIVE_ONLY = frozenset(
    {
        "restore",
        "phrase_add",
        "phrase_set",
        "phrase_remove",
        "notice_enable",
        "sensitivity_set",
        "pin_set",
        "pin_change",
        "pin_reset",
        "tag_merge",
        "tag_remove",
        "tags_backfill_apply",
        "backup_encrypt",
        "import_apply",
        "import_apply_high",
        "import_undo",
        "purge",
        "purge_finish",
        "cleanup_apply",
        "auto_config",
        "auto_hide",
    }
)
# Of those, the ones that also need the PIN. `pin_set` has no PIN yet and `pin_reset` proves
# itself with the recovery code instead.
PIN_REQUIRED = frozenset(
    {
        "restore",
        "phrase_add",
        "phrase_set",
        "phrase_remove",
        "notice_enable",
        "sensitivity_set",
        "tag_merge",
        "tag_remove",
        "import_apply_high",
        "purge",
        "cleanup_apply",
        "auto_config",
    }
)


def sees_hidden(caller: Caller) -> bool:
    """D103: only the user's own terminal knows hidden notes exist; to any AI they are gone."""
    return caller.channel is Channel.CLI


def require(caller: Caller, operation: str) -> None:
    allowed = PERMISSIONS.get(operation, frozenset())
    if caller.channel not in allowed:
        raise EmlekError(ErrorCode.NOT_PERMITTED, f"此入口不能執行 {operation}")
    if operation in INTERACTIVE_ONLY and not caller.interactive:
        raise EmlekError(
            ErrorCode.NOT_PERMITTED,
            f"{operation} 必須在你自己的終端機執行，不能由管線、腳本或 AI 代跑",
        )
    if operation in PIN_REQUIRED and not caller.pin_verified:
        raise EmlekError(ErrorCode.NOT_PERMITTED, f"{operation} 需要先通過 PIN 驗證")
