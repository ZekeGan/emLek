"""emlek init"""

from __future__ import annotations

import argparse

from emlek.cli.commands.common import cli_caller, data_dir_of
from emlek.cli.output import Output
from emlek.core.vault import init_vault


def run(args: argparse.Namespace) -> Output:
    result = init_vault(cli_caller(), data_dir_of(args))
    lines = [
        "已建立 emLek 資料夾" if result["created"] else "emLek 資料夾已存在，設定維持原狀",
        f"位置：{result['data_dir']}",
        f"結構版本：{result['schema_version']}　日誌模式：{result['journal_mode']}",
        f"備份資料夾（尚未建立，M4 起使用）：{result['backup_dir']}",
        "權限：只有目前使用者可存取"
        if result["permissions_restricted"]
        else "權限：未能自動限制，請執行 emlek doctor 檢查",
    ]
    return Output(result, "\n".join(lines))
