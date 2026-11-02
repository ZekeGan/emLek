"""Argument parser for the emlek command line."""

from __future__ import annotations

import argparse

from emlek import __version__
from emlek.core.search import DEFAULT_LIMIT, MAX_LIMIT, ORDERS, SENSITIVITY_LEVELS
from emlek.core.service import CLEARABLE, KINDS
from emlek.core.versions import RELATIONS

LINK_HELP = "連到較舊的記錄，如 r12 或 r12:supersedes（關係：" + "、".join(RELATIONS) + "）；可重複"


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
    save.add_argument("--link", action="append", metavar="REF[:關係]", help=LINK_HELP)

    get = sub.add_parser("get", help="讀取一筆記憶")
    get.add_argument("ref", help="記錄編號，如 r12 或 r12.v3")
    get.add_argument("--version", type=int, help="指定版本（預設最新）")
    get.add_argument("--include-hidden", action="store_true", help="讀取已隱藏的記錄")
    get.add_argument("--offset", type=int, default=0, help="從第幾個字元開始讀（長內容分段）")

    amend = sub.add_parser("amend", help="為既有記錄新增版本（改錯字、補充）")
    amend.add_argument("ref", help="記錄編號，如 r12")
    amend.add_argument("--text", help="新版內容（較長的內容請用 --body-file 或標準輸入）")
    amend.add_argument("--body-file", help="從檔案讀取新版內容（UTF-8），- 表示標準輸入")
    amend.add_argument("--expected-version", type=int, help="與最新版本不符就拒絕，防止互相覆蓋")
    amend.add_argument("--event-time", help="新的事件時間（省略＝沿用）")
    amend.add_argument("--precision", help="事件時間精度（須同時給 --event-time）")
    amend.add_argument("--source", help="新的來源（省略＝沿用）")
    amend.add_argument("--clear", nargs="+", choices=CLEARABLE, help="清空這些欄位")
    amend.add_argument("--link", action="append", metavar="REF[:關係]", help=LINK_HELP)

    hide = sub.add_parser("hide", help="隱藏一筆記錄（可恢復）")
    hide.add_argument("ref", help="記錄編號，如 r12")
    unhide = sub.add_parser("unhide", help="恢復被隱藏的記錄")
    unhide.add_argument("ref", help="記錄編號，如 r12")

    find = sub.add_parser("search", help="搜尋（關鍵字、日期、排序、分頁）")
    find.add_argument(
        "query", nargs="?", help="關鍵字，空白分隔表示全部都要出現；可用雙引號包住片語"
    )
    find.add_argument("--kinds", nargs="+", choices=KINDS, help="只看這些種類")
    find.add_argument("--date-field", choices=("event_time", "created_at"), default="event_time")
    find.add_argument("--from", dest="date_from", help="起日：2026、2026-11 或 2026-11-01")
    find.add_argument("--to", dest="date_to", help="迄日：格式同 --from，含當天")
    find.add_argument("--order", choices=ORDERS, help="預設：有關鍵字用 relevance，否則 event_time")
    find.add_argument("--dir", choices=("asc", "desc"), default="desc", help="排序方向")
    find.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT, help=f"每頁筆數，最多 {MAX_LIMIT}"
    )
    find.add_argument("--cursor", help="上一頁回傳的游標")
    find.add_argument("--all-versions", action="store_true", help="也比對舊版本")
    find.add_argument("--include-hidden", action="store_true", help="包含已隱藏的記錄")
    find.add_argument("--current-only", action="store_true", help="排除已被推翻的記錄")
    find.add_argument("--max-sensitivity", choices=SENSITIVITY_LEVELS, default="high")

    serve = sub.add_parser("mcp", help="以 MCP（stdio）提供工具給 AI 使用")
    serve.add_argument(
        "--read-only", action="store_true", help="唯讀模式：工具清單不含任何寫入工具"
    )

    backup = sub.add_parser("backup", help="建立一致性備份（預設放 config.toml 的 backup_dir）")
    backup.add_argument("--to", help="備份資料夾（覆寫設定）")

    restore = sub.add_parser("restore", help="以備份取代目前資料庫（必須在你自己的終端機執行）")
    restore.add_argument("file", help="備份檔路徑")

    export = sub.add_parser("export", help="匯出完整 JSONL 與可閱讀的 Markdown")
    export.add_argument("--out", help="輸出資料夾（預設為資料夾內的 exports）")
    export.add_argument("--exclude-high", action="store_true", help="排除最高敏感度的記錄")

    sub.add_parser("stats", help="記錄數、日期範圍、上次備份")

    sub.add_parser("reindex", help="重建全文索引（索引與資料不一致時使用）")
    return parser
