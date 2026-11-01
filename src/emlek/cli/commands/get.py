"""emlek get"""

from __future__ import annotations

import argparse

from emlek.cli.commands.common import cli_caller, open_vault
from emlek.cli.output import Output
from emlek.core import service


def run(args: argparse.Namespace) -> Output:
    db = open_vault(args)
    try:
        result = service.get(db, cli_caller(), ref=args.ref, version=args.version)
    finally:
        db.close()
    header = f"{result['revision_ref']}　{result['kind']}　存入 {result['created_at']}"
    if result["event_time"]:
        header += f"　事件時間 {result['event_time']}（{result['event_time_precision']}）"
    if result["source"]:
        header += f"　來源 {result['source']}"
    return Output(result, f"{header}\n-----\n{result['body']}")
