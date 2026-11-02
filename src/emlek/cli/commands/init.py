"""emlek init"""

from __future__ import annotations

import argparse

from emlek.cli.commands.common import cli_caller, data_dir_of, open_vault
from emlek.cli.output import Output
from emlek.core import security
from emlek.core.errors import EmlekError
from emlek.core.vault import init_vault


def run(args: argparse.Namespace) -> Output:
    caller = cli_caller()
    result = init_vault(caller, data_dir_of(args))
    lines = [
        "已建立 emLek 資料夾" if result["created"] else "emLek 資料夾已存在，設定維持原狀",
        f"位置：{result['data_dir']}",
        f"結構版本：{result['schema_version']}　日誌模式：{result['journal_mode']}",
        f"備份資料夾（第一次 emlek backup 時建立）：{result['backup_dir']}",
        "權限：只有目前使用者可存取"
        if result["permissions_restricted"]
        else "權限：未能自動限制，請執行 emlek doctor 檢查",
    ]
    result["pin_state"] = _pin_step(args, caller.interactive, lines)
    return Output(result, "\n".join(lines))


def _pin_step(args: argparse.Namespace, interactive: bool, lines: list[str]) -> str:
    from emlek.cli.commands.trust import RECOVERY_NOTE, set_pin_interactively

    data_dir = data_dir_of(args)
    db = open_vault(args)
    try:
        current = security.state(db.conn, data_dir)
        if current == security.UNSET and interactive:
            lines.append("接著設定 PIN（保護還原、改觸發語句等危險命令）：")
            try:
                code = set_pin_interactively(db, data_dir)
            except EmlekError as error:
                lines.append(f"未能設定 PIN：{error.message}　請稍後執行 emlek pin set")
                return security.UNSET
            lines.append("已設定 PIN。\n" + RECOVERY_NOTE.format(code=code))
            return security.SET
        if current == security.UNSET:
            lines.append(
                "尚未設定 PIN：請在你自己的終端機執行 emlek pin set（在那之前危險命令一律拒絕）"
            )
        return current
    finally:
        db.close()
