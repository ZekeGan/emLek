"""emlek get"""

from __future__ import annotations

import argparse

from emlek.cli.commands.common import cli_caller, open_vault
from emlek.cli.output import Output
from emlek.core import service


def run(args: argparse.Namespace) -> Output:
    db = open_vault(args)
    try:
        result = service.get(
            db,
            cli_caller(),
            ref=args.ref,
            version=args.version,
            include_hidden=args.include_hidden,
            offset=args.offset,
        )
    finally:
        db.close()
    header = f"{result['revision_ref']}　{result['kind']}　存入 {result['created_at']}"
    if result["event_time"]:
        header += f"　事件時間 {result['event_time']}（{result['event_time_precision']}）"
    if result["source"]:
        header += f"　來源 {result['source']}"
    notes = [f"狀態 {result['status']}"]
    if result["invalidated"]:
        notes.append("衍生自被隱藏的記錄，暫不可用")
    if result["superseded_by"]:
        notes.append(
            "被 " + "、".join(i["revision_ref"] for i in result["superseded_by"]) + " 推翻"
        )
    if result["linked_from"]:
        notes.append(
            "被連結："
            + "、".join(
                f"{i['revision_ref']}（{i['relation'] or '未指定'}）" for i in result["linked_from"]
            )
        )
    if result["truncated"]:
        notes.append(f"內容已截斷，用 --offset {result['next_offset']} 讀其餘")
    return Output(result, f"{header}\n{'；'.join(notes)}\n-----\n{result['body']}")
