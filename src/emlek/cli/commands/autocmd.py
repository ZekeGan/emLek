"""emlek auto / recent: the auto-record policy and a look back at what was saved."""

from __future__ import annotations

import argparse

from emlek.cli.commands.common import authorize, cli_caller, open_vault
from emlek.cli.output import Output
from emlek.core import auto
from emlek.core.db import Database
from emlek.core.permissions import Caller

_MODE_LABEL = {"auto": "直接存（首次需全域同意）", "ask": "不自動存", "off": "關閉"}


def _status_text(result: dict[str, object]) -> str:
    lines = [
        "自動記錄：" + ("開啟" if result["enabled"] else "關閉（AI 一律照一般流程詢問）"),
        f"24 小時內已自動記錄 {result['used_24h']} 筆（上限 {result['daily_limit']}）",
    ]
    categories: list[dict[str, str]] = result["categories"]  # type: ignore[assignment]
    for item in categories:
        lines.append(f"  {item['name']}　{_MODE_LABEL[item['mode']]}　{item['description']}")
    excluded: list[str] = result["excluded_projects"]  # type: ignore[assignment]
    if excluded:
        lines.append("排除的專案：" + "、".join(str(e) for e in excluded))
    return "\n".join(lines)


def _change(db: Database, caller: Caller, args: argparse.Namespace) -> Output:
    command = args.auto_command
    if command == "on" or command == "off":
        done = auto.set_enabled(db, caller, on=command == "on")
        return Output(done, "已開啟自動記錄。" if done["enabled"] else "已關閉自動記錄。")
    if command == "set":
        done = auto.set_mode(db, caller, name=args.name, mode=args.mode)
        return Output(done, f"「{done['name']}」改為：{_MODE_LABEL[done['mode']]}")
    if command == "add":
        done = auto.add_category(db, caller, name=args.name, description=args.desc)
        return Output(done, f"已新增類別「{done['name']}」（先問）")
    if command == "remove":
        done = auto.remove_category(db, caller, name=args.name)
        return Output(done, f"已刪除類別「{done['name']}」")
    if command == "limit":
        done = auto.set_limit(db, caller, limit=args.count)
        return Output(done, f"24 小時內自動記錄上限：{done['daily_limit']}")
    done = auto.exclude(db, caller, keyword=args.keyword, remove=args.remove)
    return Output(done, "排除的專案：" + ("、".join(done["excluded_projects"]) or "（無）"))


def run_auto(args: argparse.Namespace) -> Output:
    command = args.auto_command
    if command == "status":
        db = open_vault(args)
        try:
            result = auto.policy(db, cli_caller())
        finally:
            db.close()
        return Output(result, _status_text(result))
    if command == "hide":
        caller = authorize(args, "auto_hide", pin=False)
        db = open_vault(args)
        try:
            done = auto.hide_since(db, caller, since=args.since)
        finally:
            db.close()
        text = f"已隱藏 {done['count']} 筆自動記錄的記錄（可用 unhide 恢復）。"
        if done["hidden"]:
            text += "\n" + "、".join(done["hidden"])
        return Output(done, text)
    caller = authorize(args, "auto_config")
    db = open_vault(args)
    try:
        return _change(db, caller, args)
    finally:
        db.close()


def run_recent(args: argparse.Namespace) -> Output:
    db = open_vault(args)
    try:
        result = auto.recent(
            db, cli_caller(), days=args.days, auto_only=args.auto, limit=args.limit
        )
    finally:
        db.close()
    lines = []
    for item in result["records"]:
        tag = f"[{item['category']}]" if item["category"] else ""
        hidden = "（已隱藏）" if item["hidden"] else ""
        lines.append(f"{item['ref']}　{item['created_at'][:16]}　{tag}{hidden}　{item['excerpt']}")
    return Output(result, "\n".join(lines) or "（這段期間沒有符合的記錄）")
