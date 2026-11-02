"""emlek tag … / emlek tags …: tag the records, link and alias tags, find and audit them.

`tag merge` and `tag remove` change the shared vocabulary for good, so they need a person at a
real terminal and the PIN, like the other dangerous commands.
"""

from __future__ import annotations

import argparse
import sys

from emlek.cli.commands.common import authorize, cli_caller, open_vault
from emlek.cli.output import Output
from emlek.core import tags as tagmod
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, require


def _confirm(prompt: str) -> None:
    sys.stderr.write(prompt + "輸入「是」繼續：\n")
    sys.stderr.flush()
    if sys.stdin.readline().strip() != "是":
        raise EmlekError(ErrorCode.NEEDS_CONFIRMATION, "已取消，沒有做任何變更")


def run_tag(args: argparse.Namespace) -> Output:
    action = args.tag_command
    if action in ("merge", "remove"):
        return _dangerous(args, action)
    caller = cli_caller()
    db = open_vault(args)
    try:
        if action == "add":
            result = tagmod.set_tags(
                db, caller, ref=args.ref, add=args.names, allow_new=args.allow_new or ()
            )
            names = "、".join(t["name"] for t in result["tags"]) or "（無）"
            text = f"{result['ref']} 的標籤：{names}"
            for item in result["tags_pending"]:
                near = "、".join(item["similar"])
                text += (
                    f"\n未新增「{item['name']}」：與既有標籤相近（{near}）；"
                    "確定要新增請加 --allow-new"
                )
        elif action == "rm":
            result = tagmod.set_tags(db, caller, ref=args.ref, remove=args.names)
            text = f"{result['ref']} 已移除：{'、'.join(result['removed']) or '（沒有符合的）'}"
        elif action == "link":
            result = tagmod.link(db, caller, parent=args.parent, child=args.child)
            text = f"{result['parent']} 包含 {result['child']}"
        else:
            result = tagmod.alias(db, caller, alias_text=args.alias, tag=args.tag)
            text = f"別名「{result['alias']}」→ {result['tag']}"
    finally:
        db.close()
    return Output(result, text)


def _dangerous(args: argparse.Namespace, action: str) -> Output:
    caller = authorize(args, "tag_merge" if action == "merge" else "tag_remove")
    db = open_vault(args)
    try:
        if action == "merge":
            _confirm(f"將把標籤「{args.old}」併入「{args.new}」，舊名稱會變成別名，無法復原。")
            result = tagmod.merge(db, caller, old=args.old, new=args.new)
            text = (
                f"已合併「{result['merged']}」→「{result['into']}」，"
                f"轉移 {result['records_moved']} 筆記錄"
            )
            if result["links_skipped"]:
                text += f"；因會形成循環而略過：{'、'.join(result['links_skipped'])}"
        else:
            info = tagmod.usage(db, name=args.name)
            _confirm(
                f"將刪除標籤「{info['name']}」（{info['uses']} 筆記錄使用），"
                "記錄本身不受影響，無法復原。"
            )
            result = tagmod.remove(db, caller, name=args.name)
            text = (
                f"已刪除標籤「{result['removed']}」，{result['records_untagged']} 筆記錄不再帶有它"
            )
    finally:
        db.close()
    return Output(result, text)


def run_tags(args: argparse.Namespace) -> Output:
    action = args.tags_command
    caller = cli_caller()
    db = open_vault(args)
    try:
        if action == "find":
            result = tagmod.find(db, caller, text=args.text, limit=args.limit)
            lines = [
                f"{item['name']}（{item['type']}，{item['uses']} 筆"
                + (f"，別名：{'、'.join(item['aliases'])}" if item["aliases"] else "")
                + f"）←{item['matched_via']}"
                for item in result["results"]
            ]
            return Output(result, "\n".join(lines) or "找不到相近的標籤")
        if action == "list":
            result = tagmod.listing(
                db,
                caller,
                tree=args.tree,
                related_to=args.related_to,
                type_=args.type,
                limit=args.limit,
            )
            if "tree" in result:
                return Output(result, _render_tree(result["tree"], 0))
            if "related" in result:
                text = "\n".join(
                    f"{r['name']}　一起出現 {r['together']} 次" for r in result["related"]
                )
                return Output(result, text or "沒有常一起出現的標籤")
            lines = [f"{t['name']}（{t['type']}，{t['uses']} 筆）" for t in result["tags"]]
            return Output(result, "\n".join(lines) or "（還沒有標籤）")
        if action == "backfill":
            return _backfill(db, caller, args)
        report = tagmod.audit(db, caller)
    finally:
        db.close()
    lines = [
        f"標籤 {report['tags']} 個；{report['records_with_tags']}／{report['records']} 筆記錄有標籤"
        + (f"（{report['coverage_percent']}%）" if report["coverage_percent"] is not None else ""),
    ]
    for label, key in (
        ("疑似重複", "possible_duplicates"),
        ("只用過一次", "used_once"),
        ("使用過度、失去區辨力", "too_common"),
        ("沒人使用", "unused"),
    ):
        items = report[key]
        if items:
            shown = ["／".join(i) if isinstance(i, list) else i for i in items[:10]]
            lines.append(f"{label}：{'、'.join(shown)}")
    return Output(report, "\n".join(lines))


def _backfill(db: Database, caller: Caller, args: argparse.Namespace) -> Output:
    if args.undo:
        require(caller, "tags_backfill_apply")
        _confirm("將移除所有由回補規則加上的標籤（你或 AI 自己加的不受影響）。")
        done = tagmod.backfill_undo(db, caller)
        return Output(done, f"已移除 {done['removed']} 個由規則加上的標籤關聯")
    plan = tagmod.backfill_plan(db, caller, only=args.only)
    lines = []
    for item in plan["plan"]:
        examples = "；".join(f"{s['ref']} {s['text']}" for s in item["samples"])
        lines.append(f"{item['tag']}：{item['records']} 筆　例：{examples}")
    for item in plan["skipped"]:
        lines.append(f"略過 {item['tag']}：{item['reason']}")
    lines.append(
        f"共 {plan['new_links']} 個新的標籤關聯"
        + ("（只是預覽，加 --apply 才會套用）" if not args.apply else "")
    )
    if not args.apply:
        return Output(plan, "\n".join(lines))
    require(caller, "tags_backfill_apply")
    if not plan["new_links"]:
        return Output(plan, "\n".join(lines))
    sys.stderr.write("\n".join(lines) + "\n")
    _confirm(f"將套用 {plan['new_links']} 個標籤關聯（來源標記為 rule，可用 --undo 全部復原）。")
    done = tagmod.backfill_apply(db, caller, only=args.only)
    return Output(done, f"已套用 {done['new_links']} 個標籤關聯")


def _render_tree(node: dict[str, object], depth: int) -> str:
    lines = [f"{'  ' * depth}{node['name']}（{node['uses']}）"]
    for child in node.get("children", []):  # type: ignore[attr-defined]
        lines.append(_render_tree(child, depth + 1))
    return "\n".join(lines)
