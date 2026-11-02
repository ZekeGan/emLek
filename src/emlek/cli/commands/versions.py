"""emlek amend / hide / unhide, and the --link option shared with save"""

from __future__ import annotations

import argparse

from emlek.cli.commands.common import cli_caller, open_vault, parse_links
from emlek.cli.commands.save import read_body
from emlek.cli.output import Output
from emlek.core import service
from emlek.core import versions as core_versions


def run_amend(args: argparse.Namespace) -> Output:
    body = read_body(args)
    db = open_vault(args)
    try:
        result = service.amend(
            db,
            cli_caller(),
            ref=args.ref,
            body=body,
            expected_version=args.expected_version,
            event_time=args.event_time,
            event_time_precision=args.precision,
            source=args.source,
            clear=args.clear or (),
            links=parse_links(args.link),
            sensitivity=args.sensitivity,
            confirm_token=args.confirm_token,
            notice_token=args.notice_token,
            tags=args.tags,
            allow_new=args.allow_new or (),
        )
    finally:
        db.close()
    return Output(
        result, f"已新增 {result['revision_ref']}（前一版 v{result['previous_version']}）"
    )


def _hide(args: argparse.Namespace, *, hide: bool) -> Output:
    db = open_vault(args)
    try:
        action = core_versions.hide if hide else core_versions.unhide
        result = action(db, cli_caller(), ref=args.ref)
    finally:
        db.close()
    verb = "隱藏" if hide else "恢復"
    text = (
        f"{result['ref']} 已{verb}" if result["changed"] else f"{result['ref']} 本來就是{verb}狀態"
    )
    if result["affected_derivatives"]:
        text += f"；連帶影響的衍生記錄：{', '.join(result['affected_derivatives'])}"
    return Output(result, text)


def run_hide(args: argparse.Namespace) -> Output:
    return _hide(args, hide=True)


def run_unhide(args: argparse.Namespace) -> Output:
    return _hide(args, hide=False)
