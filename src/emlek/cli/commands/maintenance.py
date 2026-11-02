"""emlek backup / restore / export / stats"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from emlek.cli.commands.common import authorize, cli_caller, data_dir_of, open_vault
from emlek.cli.output import Output
from emlek.config import load_config
from emlek.core import backup as core_backup
from emlek.core import export as core_export
from emlek.core import stats as core_stats
from emlek.core.errors import EmlekError, ErrorCode


def run_backup(args: argparse.Namespace) -> Output:
    data_dir = data_dir_of(args)
    target = Path(args.to) if args.to else load_config(data_dir).backup_dir
    if target is None:
        raise EmlekError(
            ErrorCode.INVALID_INPUT, "請用 --to 指定備份資料夾，或在 config.toml 設定 backup_dir"
        )
    db = open_vault(args)
    try:
        result = core_backup.create_backup(db, cli_caller(), target, data_dir)
    finally:
        db.close()
    lines = [
        f"已備份：{result['file']}",
        f"{result['records']} 筆記錄、{result['revisions']} 個版本"
        f"，{result['bytes']:,} 位元組，完整性檢查通過",
        "注意：這份備份沒有加密，內容是明文；請放在只有你能存取的位置。",
    ]
    if result["same_drive_as_data"]:
        lines.append("注意：備份與資料在同一顆磁碟，磁碟故障時兩者會一起消失，建議改放另一顆。")
    return Output(result, "\n".join(lines))


def run_restore(args: argparse.Namespace) -> Output:
    caller = authorize(args, "restore")  # a real terminal first, then the PIN
    data_dir = data_dir_of(args)
    source = Path(args.file)
    info = core_backup.inspect_database(source)
    sys.stderr.write(  # no bypass flag: this command is for a person at a terminal
        f"將以備份取代目前的資料庫：{info['records']} 筆記錄、{info['revisions']} 個版本。\n"
        "目前的資料庫會改名保留。輸入「是」繼續：\n"
    )
    sys.stderr.flush()
    if sys.stdin.readline().strip() != "是":
        raise EmlekError(ErrorCode.NEEDS_CONFIRMATION, "已取消，沒有做任何變更")
    result = core_backup.restore_backup(caller, data_dir, source)
    kept = result["previous_database_kept_as"]
    lines = [f"已還原：{result['records']} 筆記錄、{result['revisions']} 個版本"]
    if kept:
        lines.append(f"原本的資料庫保留為：{kept}")
    return Output(result, "\n".join(lines))


def run_export(args: argparse.Namespace) -> Output:
    data_dir = data_dir_of(args)
    out_dir = Path(args.out) if args.out else data_dir / "exports"
    db = open_vault(args)
    try:
        result = core_export.export_all(db, cli_caller(), out_dir, exclude_high=args.exclude_high)
    finally:
        db.close()
    lines = [
        f"已匯出到：{result['folder']}",
        f"{result['records']} 筆記錄、{result['revisions']} 個版本"
        f"（export.jsonl 為完整資料，markdown/ 供閱讀）",
        "注意：匯出內容是明文。",
    ]
    if result["excluded_high_records"]:
        lines.append(f"已排除 {result['excluded_high_records']} 筆最高敏感度的記錄")
    return Output(result, "\n".join(lines))


def run_stats(args: argparse.Namespace) -> Output:
    db = open_vault(args)
    try:
        result = core_stats.stats(db, cli_caller())
    finally:
        db.close()
    event = result["event_dates"]
    saved = result["saved_between"]
    lines = [
        f"記錄 {result['records']} 筆（另有 {result['hidden_records']} 筆已隱藏）"
        f"，版本 {result['revisions']} 個",
        f"事件日期範圍：{event['first'] or '（無）'} 到 {event['last'] or '（無）'}",
        f"存入時間範圍：{saved['first'] or '（無）'} 到 {saved['last'] or '（無）'}",
        f"上次備份：{result['last_backup_at'] or '尚無備份'}",
        f"資料庫 {result['database_bytes']:,} 位元組，結構版本 {result['schema_version']}，"
        f"搜尋索引{'正常' if result['search_index_ok'] else '不一致（請執行 emlek reindex）'}",
    ]
    return Output(result, "\n".join(lines))
