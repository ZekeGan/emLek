"""Command line entry point."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Sequence

from emlek.cli.commands import (
    doctor,
    get,
    importcmd,
    init,
    maintenance,
    save,
    search,
    tagcmd,
    trust,
)
from emlek.cli.commands import mcp as mcp_command
from emlek.cli.commands import versions as versions_command
from emlek.cli.output import Output, print_error, print_output
from emlek.cli.parser import build_parser
from emlek.core.errors import EmlekError, ErrorCode

_HANDLERS: dict[str, Callable[..., Output | None]] = {
    "init": init.run,
    "doctor": doctor.run,
    "save": save.run,
    "get": get.run,
    "amend": versions_command.run_amend,
    "hide": versions_command.run_hide,
    "unhide": versions_command.run_unhide,
    "search": search.run,
    "reindex": search.run_reindex,
    "mcp": mcp_command.run,
    "backup": maintenance.run_backup,
    "restore": maintenance.run_restore,
    "export": maintenance.run_export,
    "import": importcmd.run,
    "stats": maintenance.run_stats,
    "pin": lambda a: {
        "set": trust.run_pin_set,
        "change": trust.run_pin_change,
        "reset": trust.run_pin_reset,
    }[a.pin_command](a),
    "phrase": trust.run_phrase,
    "tag": tagcmd.run_tag,
    "tags": tagcmd.run_tags,
    "notice": trust.run_notice,
    "sensitivity": trust.run_sensitivity,
}


def _force_utf8() -> None:
    """Windows consoles and pipes may default to cp950 or an OEM code page."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    _force_utf8()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_request:
        code = exit_request.code
        return code if isinstance(code, int) else 2
    try:
        output = _HANDLERS[args.command](args)
    except EmlekError as error:
        print_error(error, as_json=args.json)
        return error.exit_code
    except Exception:
        logging.getLogger("emlek").exception("unexpected failure in %s", args.command)
        internal = EmlekError(ErrorCode.INTERNAL, "發生未預期的錯誤，詳情見日誌")
        print_error(internal, as_json=args.json)
        return internal.exit_code
    if output is not None:  # `emlek mcp` owns stdout for the protocol and prints nothing
        print_output(output, as_json=args.json)
    return 0
