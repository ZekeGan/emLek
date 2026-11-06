"""emlek pin / phrase / notice / sensitivity: the commands behind the trust gate.

Everything here needs a person at a real terminal. Commands that change what the AI may do also
need the PIN, which is typed on the console and never read from arguments, environment variables
or standard input.
"""

from __future__ import annotations

import argparse
from typing import Any

from emlek.cli.commands.common import (
    authorize,
    cli_caller,
    data_dir_of,
    open_vault,
    read_new_pin,
    read_secret,
)
from emlek.cli.output import Output
from emlek.core import notice, phrases, security, service
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import require

RECOVERY_NOTE = (
    "復原碼（只會顯示這一次，請寫在紙上或存進密碼管理器，不要貼給任何 AI）：\n  {code}\n"
    "忘記 PIN 時用 emlek pin reset 搭配復原碼重設；兩者都遺失就只能照文件手動處理。"
)


def set_pin_interactively(db: Database, data_dir: Any) -> str:
    """Ask for a new PIN twice and store it. Returns the recovery code."""
    pin = read_new_pin()
    return security.set_pin(db, data_dir, pin)


def run_pin_set(args: argparse.Namespace) -> Output:
    require(cli_caller(), "pin_set")
    data_dir = data_dir_of(args)
    db = open_vault(args)
    try:
        code = set_pin_interactively(db, data_dir)
    finally:
        db.close()
    return Output({"pin_set": True}, "已設定 PIN。\n" + RECOVERY_NOTE.format(code=code))


def run_pin_change(args: argparse.Namespace) -> Output:
    require(cli_caller(), "pin_change")
    data_dir = data_dir_of(args)
    db = open_vault(args)
    try:
        security.ensure_available(db.conn, data_dir)
        old = read_secret("目前的 PIN：")
        new = read_new_pin("新的 PIN：")
        security.change_pin(db, data_dir, old, new)
    finally:
        db.close()
    return Output({"pin_changed": True}, "已更換 PIN。")


def run_pin_reset(args: argparse.Namespace) -> Output:
    require(cli_caller(), "pin_reset")
    data_dir = data_dir_of(args)
    db = open_vault(args)
    try:
        if security.state(db.conn, data_dir) == security.UNSET:
            raise EmlekError(ErrorCode.CONFLICT, "尚未設定 PIN；請用 emlek pin set")
        recovery = read_secret("復原碼：")
        new = read_new_pin("新的 PIN：")
        code = security.reset_pin(db, data_dir, recovery, new)
    finally:
        db.close()
    return Output({"pin_reset": True}, "已重設 PIN。\n" + RECOVERY_NOTE.format(code=code))


def run_phrase(args: argparse.Namespace) -> Output:
    action = args.phrase_command
    if action == "list":
        require(cli_caller(), "phrase_list")
        db = open_vault(args)
        try:
            result = phrases.list_phrases(db, cli_caller(), kind=args.kind)
        finally:
            db.close()
        lines = []
        for kind, items in result["phrases"].items():
            for item in items:
                state = "" if item["enabled"] else "（停用）"
                lines.append(f"{item['id']:>3}  {kind:<7}{item['text']}{state}")
        if not result["purge_enabled"]:
            lines.append("注意：目前沒有啟用中的 purge 語句，徹底清除是關閉的。")
        return Output(result, "\n".join(lines) or "（沒有語句）")

    operation = {"add": "phrase_add", "set": "phrase_set", "remove": "phrase_remove"}[action]
    caller = authorize(args, operation)
    db = open_vault(args)
    try:
        if action == "add":
            done = phrases.add(db, caller, kind=args.kind, text=args.text)
            text = f"已新增語句 #{done['id']}（{done['kind']}）"
        elif action == "set":
            enabled = True if args.enable else False if args.disable else None
            done = phrases.update(db, caller, phrase_id=args.id, text=args.text, enabled=enabled)
            text = f"已更新語句 #{done['id']}（{done['kind']}）"
        else:
            done = phrases.remove(db, caller, phrase_id=args.id)
            text = f"已刪除語句 #{done['id']}（{done['kind']}）"
    finally:
        db.close()
    return Output(done, text)


def run_notice(args: argparse.Namespace) -> Output:
    if args.notice_command == "status":
        db = open_vault(args)
        try:
            result = notice.status(db, cli_caller())
        finally:
            db.close()
        state = "尚未同意（首次自動儲存時詢問）" if result["personal_notice_enabled"] else "已同意"
        return Output(result, f"所有個人資訊自動儲存：{state}")
    caller = authorize(args, "notice_enable")
    db = open_vault(args)
    try:
        result = notice.enable_medium(db, caller)
    finally:
        db.close()
    return Output(result, "已重新開啟所有個人資訊的儲存同意提醒。")


def run_sensitivity(args: argparse.Namespace) -> Output:
    caller = authorize(args, "sensitivity_set")
    db = open_vault(args)
    try:
        result = service.set_sensitivity(db, caller, ref=args.ref, level=args.level)
    finally:
        db.close()
    return Output(
        result, f"{result['ref']} 的敏感度：{result['previous']} → {result['sensitivity']}"
    )
