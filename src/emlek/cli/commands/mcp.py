"""emlek mcp: serve the tools over stdio for an AI client."""

from __future__ import annotations

import argparse

from emlek.cli.commands.common import data_dir_of
from emlek.config import load_config
from emlek.core.errors import EmlekError, ErrorCode


def run(args: argparse.Namespace) -> None:
    data_dir = data_dir_of(args)
    if not load_config(data_dir).db_path.exists():
        raise EmlekError(ErrorCode.NOT_FOUND, "尚未初始化，請先執行 emlek init")
    from emlek.mcp_server.server import build_server  # slow import, only needed here

    build_server(data_dir, read_only=args.read_only).run("stdio")
