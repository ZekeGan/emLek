"""emlek import: preview by default, write only with --apply (a person at a terminal)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from emlek.cli.commands.common import authorize, cli_caller, data_dir_of, open_vault
from emlek.cli.output import Output
from emlek.config import load_config
from emlek.core import importer
from emlek.core.errors import EmlekError, ErrorCode

SHOW = 40
LABELS = {
    "failed": "失敗",
    "high": "含最高風險，已略過",
    "duplicate": "重複",
    "already_hidden": "已匯入但被隱藏",
    "changed": "已變更",
}


def _ask(question: str) -> None:
    sys.stderr.write(question + "輸入「是」繼續：\n")
    sys.stderr.flush()
    if sys.stdin.readline().strip() != "是":
        raise EmlekError(ErrorCode.NEEDS_CONFIRMATION, "已取消，沒有做任何變更")


def _describe(plan: importer.Plan) -> list[str]:
    s = plan.summary()
    changed = f"（另有 {s['changed_since_last_import']} 個自上次匯入後已變更）"
    lines = [
        f"可匯入 {s['to_import'] + s['changed_since_last_import']} 個檔案"
        + (changed if s["changed_since_last_import"] else ""),
        f"已匯入過 {s['already_imported']}、重複 {s['duplicates']}、"
        f"含最高風險略過 {s['high_left_out']}、失敗 {s['failed']}、"
        f"略過其他檔案 {s['skipped_other_files']}",
    ]
    if s["medium"]:
        lines.append(f"其中 {s['medium']} 個含個人資料，匯入後會標為 medium")
    if s["undated"]:
        lines.append(f"{s['undated']} 個檔名沒有日期，事件時間會留空")
    if s["ambiguous_dates"]:
        lines.append(f"{s['ambiguous_dates']} 個檔名有多個不同日期，事件時間留空")
    if s["skipped_links"]:
        lines.append(f"略過 {s['skipped_links']} 個連結／雲端預留檔")
    if s["skipped_own_folders"]:
        lines.append("略過 emLek 自己的檔案：" + "、".join(s["skipped_own_folders"]))
    problems = [i for i in plan.items if i.status in LABELS]
    for item in problems[:SHOW]:
        lines.append(f"  [{LABELS[item.status]}] {item.file_name}　{item.reason}")
    if len(problems) > SHOW:
        lines.append(f"  …還有 {len(problems) - SHOW} 個")
    return lines


def run(args: argparse.Namespace) -> Output:
    if args.list:
        db = open_vault(args)
        try:
            batches = importer.list_batches(db, cli_caller())
        finally:
            db.close()
        if not batches:
            return Output({"batches": []}, "還沒有匯入過。")
        lines = [
            f"批次 {b['batch']}　{b['created_at']}　{b['files']} 個檔案，可見 {b['visible']} 筆"
            + ("　（已整批隱藏）" if b["undone_at"] else "")
            for b in batches
        ]
        return Output({"batches": batches}, "\n".join(lines))
    if args.undo is not None:
        return _undo(args)
    if not args.path:
        raise EmlekError(ErrorCode.INVALID_INPUT, "請指定要匯入的檔案或資料夾，或用 --list／--undo")
    return _import(args)


def _undo(args: argparse.Namespace) -> Output:
    caller = authorize(args, "import_undo", pin=False)
    db = open_vault(args)
    try:
        info = importer.undo_preview(db, caller, args.undo)
        if info["already_undone"]:
            raise EmlekError(ErrorCode.CONFLICT, "這個批次已經整批隱藏過了")
        note = (
            f"其中 {info['amended_since_import']} 筆在匯入後被修改過，修改的版本也會一起隱藏。"
            if info["amended_since_import"]
            else ""
        )
        _ask(
            f"將隱藏批次 {info['batch']} 的 {info['visible']} 筆記錄"
            f"（可用 unhide 逐筆恢復）。{note}"
        )
        result = importer.undo(db, caller, args.undo)
    finally:
        db.close()
    return Output(result, f"已隱藏批次 {result['batch']} 的 {result['hidden']} 筆記錄。")


def _import(args: argparse.Namespace) -> Output:
    data_dir = data_dir_of(args)
    config = load_config(data_dir)
    root = Path(args.path)
    options: dict[str, Any] = {
        "include_high": bool(args.include_high),
        "allow_duplicates": bool(args.allow_duplicates),
    }
    caller = authorize(args, "import_apply", pin=False) if args.apply else cli_caller()
    db = open_vault(args)
    try:
        plan = importer.plan_import(
            db,
            caller,
            root,
            data_dir=data_dir,
            backup_dir=config.backup_dir,
            include_high=bool(args.include_high),
            allow_duplicates=bool(args.allow_duplicates),
        )
        lines = _describe(plan)
        if not args.apply:
            lines.append(
                "這只是預覽，沒有寫入任何東西。要寫入請加 --apply（必須在你自己的終端機）。"
            )
            preview = {"preview": True, **plan.summary(), "items": [i.public() for i in plan.items]}
            return Output(preview, "\n".join(lines))
        todo = [i for i in plan.items if i.status in importer.IMPORTABLE]
        if not todo:
            return Output(
                {"imported": 0, **plan.summary()}, "\n".join([*lines, "沒有需要匯入的檔案。"])
            )
        sys.stderr.write("\n".join(lines) + "\n")
        high = [i for i in todo if i.level == "high"]
        if high:
            caller = authorize(args, "import_apply_high")  # terminal and PIN
            sys.stderr.write("以下檔案含最高風險內容（只列檔名與類別），將以明文存入：\n")
            for item in high:
                sys.stderr.write(f"  {item.file_name}　{'、'.join(item.categories)}\n")
        _ask(f"將寫入 {len(todo)} 筆記錄（整批一次完成，出錯會全部回復）。")
        result = importer.apply_import(db, caller, plan, options=options)
    finally:
        db.close()
    text = (
        f"已匯入 {result['imported']} 筆，批次編號 {result['batch']}。"
        f"匯入錯了可用 emlek import --undo {result['batch']} 整批隱藏。"
    )
    return Output({**result, **plan.summary()}, text)
