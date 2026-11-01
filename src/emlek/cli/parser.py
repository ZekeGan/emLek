"""Argument parser for the emlek command line."""

from __future__ import annotations

import argparse

from emlek import __version__
from emlek.core.service import KINDS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="emlek", description="emLek：本機個人長期文字記憶庫")
    parser.add_argument("--version", action="version", version=f"emlek {__version__}")
    parser.add_argument("--data-dir", help="資料夾位置（預設見 EMLEK_DATA_DIR 或使用者資料夾）")
    parser.add_argument("--json", action="store_true", help="以 JSON 輸出")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<命令>")

    sub.add_parser("init", help="建立資料夾、設定與資料庫")
    sub.add_parser("doctor", help="檢查環境與資料庫狀態")

    save = sub.add_parser("save", help="存入一筆記憶")
    save.add_argument("--text", help="內容（較長的內容請用 --body-file 或標準輸入）")
    save.add_argument("--body-file", help="從檔案讀取內容（UTF-8），- 表示標準輸入")
    save.add_argument("--kind", choices=KINDS, default="original")
    save.add_argument("--source", help="來源說明（不知道就不填）")
    save.add_argument("--event-time", help="事件時間，如 2026-01-15 或 2026-01-15T09:30+09:00")
    save.add_argument("--precision", help="事件時間精度：year、month、day、hour、minute、second")

    get = sub.add_parser("get", help="讀取一筆記憶")
    get.add_argument("ref", help="記錄編號，如 r12 或 r12.v3")
    get.add_argument("--version", type=int, help="指定版本（預設最新）")
    return parser
