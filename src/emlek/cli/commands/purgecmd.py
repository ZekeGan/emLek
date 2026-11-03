"""emlek purge / cleanup: permanent removal, only by a person at a terminal with the PIN."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from emlek.cli.commands.common import (
    authorize,
    cli_caller,
    data_dir_of,
    open_vault,
    read_secret,
)
from emlek.cli.output import Output
from emlek.config import load_config
from emlek.core import cleanup as core_cleanup
from emlek.core import purge as core_purge
from emlek.core.errors import EmlekError, ErrorCode

QUESTION = "是否要從資料庫中完全刪除這筆資料？是 / 否（此操作無法再回復）"


def _describe(preview: dict[str, Any]) -> list[str]:
    lines = ["將從資料庫中完全刪除："]
    for item in preview["records"]:
        tag = "（連帶移除的衍生記錄）" if item["derived"] else ""
        hidden = "，已隱藏" if item["hidden"] else ""
        lines.append(f"  {item['ref']}　{item['versions']} 個版本{hidden}{tag}　{item['excerpt']}")
    lines.append(f"共 {preview['revisions']} 個版本、{preview['links']} 條連結")
    if preview.get("tag_names"):
        lines.append("會一併移除只因這些記錄而存在的標籤：" + "、".join(preview["tag_names"]))
    if preview.get("unused_tag_names"):
        lines.append("清除後變成沒人使用的標籤（保留）：" + "、".join(preview["unused_tag_names"]))
    kept = preview["kept_originals_that_may_mention_this"]
    if kept:
        lines.append("以下你自己的記錄會保留，但可能提到這些內容：" + "、".join(kept))
    return lines


def run(args: argparse.Namespace) -> Output:
    if args.finish:
        return _finish(args)
    if not args.refs:
        raise EmlekError(ErrorCode.INVALID_INPUT, "請指定要清除的記錄，例如 emlek purge r12")
    caller = authorize(args, "purge")
    data_dir = data_dir_of(args)
    config = load_config(data_dir)
    db = open_vault(args)
    try:
        preview = core_purge.preview(db, caller, args.refs, with_text=True)
        if not preview["purge_enabled"]:
            raise EmlekError(
                ErrorCode.NOT_PERMITTED, "徹底清除目前是關閉的（沒有啟用中的 purge 語句）"
            )
        sys.stderr.write("\n".join(_describe(preview)) + "\n" + QUESTION + "\n")
        sys.stderr.flush()
        if sys.stdin.readline().strip() != "是":
            raise EmlekError(ErrorCode.NEEDS_CONFIRMATION, "已取消，沒有刪除任何東西")
        result = core_purge.purge(
            db,
            caller,
            args.refs,
            fingerprint=str(preview["fingerprint"]),
            data_dir=data_dir,
            backup_dir=config.backup_dir,
        )
    finally:
        db.close()
    return Output(result, _report(result))


def _finish(args: argparse.Namespace) -> Output:
    caller = authorize(args, "purge_finish", pin=False)
    db = open_vault(args)
    try:
        result = core_purge.finish(db, caller)
    finally:
        db.close()
    if not result["pending"]:
        return Output(result, "沒有未完成的實體擦除。")
    if result["finished"]:
        return Output(
            result,
            "實體擦除已完成（此時已無法用片段比對驗證，只能確認檢查點與整理資料庫都成功）。",
        )
    return Output(result, "實體擦除仍未完成：" + "；".join(result["notes"]))


def _report(result: dict[str, Any]) -> str:
    scrub, residue = result["scrub"], result["residue"]
    lines = [f"已從資料庫中完全刪除 {len(result['purged'])} 筆記錄、{result['revisions']} 個版本。"]
    if scrub["finished"]:
        lines.append(
            "資料庫檔案已整理並用原始位元組比對，找不到被清除的內容。"
            if scrub["verified"]
            else "資料庫檔案已整理；沒有足夠獨特的片段可比對，無法驗證。"
        )
    else:
        lines.append(
            "邏輯上已刪除，但實體擦除未完成："
            + "；".join(scrub["notes"])
            + "。請關閉 AI 應用程式後執行 emlek purge --finish。"
        )
    if residue["checked"]:
        if residue["files"]:
            lines.append("以下副本仍含被清除的內容，請自行決定是否刪除：")
            lines += [f"  {p}" for p in residue["files"]]
        else:
            lines.append(
                f"已檢查 {residue['scanned']} 個副本檔（pre-migration、exports、tmp、logs、"
                "資料庫旁的附屬檔、備份資料夾），沒有發現殘留。"
            )
        if residue["sealed"]:
            lines.append(f"另有 {len(residue['sealed'])} 份加密備份無法檢查，請自行處理舊備份。")
    else:
        lines.append("副本檔未檢查：" + str(residue["reason"]))
    if result["kept_originals_that_may_mention_this"]:
        lines.append(
            "仍保留可能提到這些內容的記錄："
            + "、".join(result["kept_originals_that_may_mention_this"])
        )
    lines.append(core_purge.LIMITS)
    return "\n".join(lines)


def run_cleanup(args: argparse.Namespace) -> Output:
    data_dir = data_dir_of(args)
    if not args.apply:
        result = core_cleanup.preview(cli_caller(), data_dir)
        lines = [f"可清理 {result['count']} 個 emLek 自己的暫存副本，共 {result['bytes']:,} 位元組"]
        lines += [f"  {p}" for p in result["files"]]
        lines.append("這只是預覽。要刪除請加 --apply（必須在你自己的終端機，並輸入 PIN）。")
        return Output(result, "\n".join(lines))
    caller = authorize(args, "cleanup_apply")
    config = load_config(data_dir)
    db = open_vault(args)
    try:
        result = core_cleanup.apply(
            db, caller, data_dir, config.backup_dir, lambda: read_secret("備份密碼：")
        )
    finally:
        db.close()
    if not result["removed"]:
        return Output(result, "沒有需要清理的副本。")
    return Output(
        result,
        f"已刪除 {result['removed']} 個副本（{result['bytes']:,} 位元組），"
        f"事先確認過備份 {result['verified_against']} 可用。",
    )
