"""emlek save"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from emlek.cli.commands.common import cli_caller, open_vault, parse_links
from emlek.cli.output import Output
from emlek.core import service
from emlek.core.errors import EmlekError, ErrorCode


def read_body(args: argparse.Namespace) -> str:
    if args.text is not None and args.body_file is not None:
        raise EmlekError(ErrorCode.INVALID_INPUT, "--text 與 --body-file 只能擇一")
    if args.text is not None:
        return str(args.text)
    try:
        if args.body_file == "-" or (args.body_file is None and not sys.stdin.isatty()):
            data = sys.stdin.buffer.read()
        elif args.body_file is not None:
            data = Path(args.body_file).read_bytes()
        else:
            raise EmlekError(ErrorCode.INVALID_INPUT, "請用 --text、--body-file 或標準輸入提供內容")
    except OSError as exc:
        raise EmlekError(ErrorCode.INVALID_INPUT, "讀不到指定的檔案") from exc
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EmlekError(ErrorCode.INVALID_INPUT, "輸入不是有效的 UTF-8") from exc


def run(args: argparse.Namespace) -> Output:
    body = read_body(args)
    db = open_vault(args)
    try:
        result = service.save(
            db,
            cli_caller(),
            body=body,
            kind=args.kind,
            source=args.source,
            event_time=args.event_time,
            event_time_precision=args.precision,
            links=parse_links(args.link),
            sensitivity=args.sensitivity,
            confirm_token=args.confirm_token,
            notice_token=args.notice_token,
            tags=args.tags,
            allow_new=args.allow_new or (),
        )
    finally:
        db.close()
    lines = [f"已存入 {result['revision_ref']}"]
    if result.get("marker"):
        lines.append(result["marker"])
    if result.get("tags"):
        lines.append("標籤：" + "、".join(result["tags"]))
    for item in result.get("tags_pending", []):
        near = "、".join(item["similar"])
        lines.append(
            f"未新增標籤「{item['name']}」：與既有標籤相近（{near}）；確定要新增請加 --allow-new"
        )
    if result.get("hashtags_skipped"):
        lines.append("略過不合格的 #標籤：" + "、".join(result["hashtags_skipped"]))
    return Output(result, "\n".join(lines))
