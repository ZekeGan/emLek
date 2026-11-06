"""Argument parser for the emlek command line."""

from __future__ import annotations

import argparse

from emlek import __version__
from emlek.core.phrases import KINDS as PHRASE_KINDS
from emlek.core.search import DEFAULT_LIMIT, MAX_LIMIT, ORDERS, SENSITIVITY_LEVELS
from emlek.core.service import CLEARABLE, KINDS
from emlek.core.tags import TYPES as TAG_TYPES
from emlek.core.versions import RELATIONS

LINK_HELP = "連到較舊的記錄，如 r12 或 r12:supersedes（關係：" + "、".join(RELATIONS) + "）；可重複"


def _tag_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--tag", dest="tags", action="append", help="加標籤（可重複）")
    command.add_argument("--allow-new", action="append", help="確定要新增這個與既有標籤相近的名稱")


def _sensitivity_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--sensitivity", choices=SENSITIVITY_LEVELS, help="宣告敏感度（只能調高）")
    command.add_argument("--confirm-token", help="最高風險內容經使用者同意後的確認碼")
    command.add_argument("--notice-token", help="個人資料提醒經使用者同意後的確認碼")


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
    _sensitivity_options(save)
    _tag_options(save)

    get = sub.add_parser("get", help="讀取一筆記憶")
    get.add_argument("ref", help="記錄編號，如 r12 或 r12.v3")
    get.add_argument("--version", type=int, help="指定版本（預設最新）")
    get.add_argument("--include-hidden", action="store_true", help="讀取已隱藏的記錄")
    get.add_argument("--max-sensitivity", choices=SENSITIVITY_LEVELS, default="high")
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
    _sensitivity_options(amend)
    _tag_options(amend)

    hide = sub.add_parser("hide", help="隱藏一筆記錄（可恢復）")
    hide.add_argument("ref", help="記錄編號，如 r12")
    unhide = sub.add_parser("unhide", help="恢復被隱藏的記錄")
    unhide.add_argument("ref", help="記錄編號，如 r12")

    find = sub.add_parser("search", help="搜尋（關鍵字、日期、排序、分頁）")
    find.add_argument(
        "query",
        nargs="?",
        help="關鍵字，空白分隔表示全部都要出現，大寫 OR 表示任一；可用雙引號包住片語",
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
    find.add_argument("--tag", dest="tags", action="append", help="只看有這個標籤的記錄（可重複）")
    find.add_argument("--match", choices=("any", "all"), default="any", help="多個標籤：任一或全部")
    find.add_argument("--tag-type", dest="tag_types", action="append", choices=TAG_TYPES)
    find.add_argument("--no-expand", action="store_true", help="標籤不往下展開")
    find.add_argument("--facets", action="store_true", help="附上結果中最常見的標籤")
    find.add_argument("--untagged", action="store_true", help="只看還沒有任何標籤的記錄")
    find.add_argument("--max-sensitivity", choices=SENSITIVITY_LEVELS, default="high")

    serve = sub.add_parser("mcp", help="以 MCP（stdio）提供工具給 AI 使用")
    serve.add_argument(
        "--read-only", action="store_true", help="唯讀模式：工具清單不含任何寫入工具"
    )

    backup = sub.add_parser("backup", help="建立一致性備份（預設放 config.toml 的 backup_dir）")
    backup.add_argument("--to", help="備份資料夾（覆寫設定）")
    backup.add_argument(
        "--encrypt",
        action="store_true",
        help="用密碼加密備份（必須在你自己的終端機執行；密碼遺失就無法還原）",
    )

    restore = sub.add_parser("restore", help="以備份取代目前資料庫（必須在你自己的終端機執行）")
    restore.add_argument("file", help="備份檔路徑")

    imp = sub.add_parser(
        "import", help="匯入 .txt／.md 檔（預設只預覽；--apply 才寫入，必須在你自己的終端機）"
    )
    imp.add_argument("path", nargs="?", help="檔案或資料夾")
    imp.add_argument("--apply", action="store_true", help="真的寫入（預設只預覽）")
    imp.add_argument(
        "--include-high", action="store_true", help="舊版相容參數；最高風險內容仍一律略過"
    )
    imp.add_argument("--allow-duplicates", action="store_true", help="內容相同的檔案也匯入")
    imp.add_argument("--list", action="store_true", help="列出匯入過的批次")
    imp.add_argument("--undo", type=int, metavar="批次編號", help="把某個批次整批隱藏")

    purge = sub.add_parser("purge", help="徹底刪除記錄（無法恢復；必須在你自己的終端機並輸入 PIN）")
    purge.add_argument("refs", nargs="*", help="記錄編號，例如 r12（一次最多 20 筆）")
    purge.add_argument("--finish", action="store_true", help="補做未完成的實體擦除")

    cleanup = sub.add_parser("cleanup", help="清理 emLek 自己的暫存副本（預設只預覽）")
    cleanup.add_argument("--apply", action="store_true", help="真的刪除（需真人終端機與 PIN）")

    export = sub.add_parser("export", help="匯出完整 JSONL 與可閱讀的 Markdown")
    export.add_argument("--out", help="輸出資料夾（預設為資料夾內的 exports）")
    export.add_argument("--exclude-high", action="store_true", help="排除最高敏感度的記錄")

    sub.add_parser("stats", help="記錄數、日期範圍、上次備份")

    tag = sub.add_parser("tag", help="標籤：加減、階層、別名、合併、刪除")
    tag_sub = tag.add_subparsers(dest="tag_command", required=True, metavar="<動作>")
    tag_add = tag_sub.add_parser("add", help="替記錄加標籤")
    tag_add.add_argument("ref")
    tag_add.add_argument("names", nargs="+")
    tag_add.add_argument("--allow-new", action="append")
    tag_rm = tag_sub.add_parser("rm", help="從記錄移除標籤")
    tag_rm.add_argument("ref")
    tag_rm.add_argument("names", nargs="+")
    tag_link = tag_sub.add_parser("link", help="宣告上層標籤包含下層標籤")
    tag_link.add_argument("parent")
    tag_link.add_argument("child")
    tag_alias = tag_sub.add_parser("alias", help="替標籤加別名")
    tag_alias.add_argument("alias")
    tag_alias.add_argument("tag")
    tag_merge = tag_sub.add_parser("merge", help="把舊標籤併入新標籤（需要 PIN）")
    tag_merge.add_argument("old")
    tag_merge.add_argument("new")
    tag_remove = tag_sub.add_parser("remove", help="刪除標籤本身（需要 PIN）")
    tag_remove.add_argument("name")

    tags = sub.add_parser("tags", help="查標籤")
    tags_sub = tags.add_subparsers(dest="tags_command", required=True, metavar="<動作>")
    tags_find = tags_sub.add_parser("find", help="模糊查標籤")
    tags_find.add_argument("text")
    tags_find.add_argument("--limit", type=int, default=10)
    tags_list = tags_sub.add_parser("list", help="列出常用標籤、階層或常一起出現的標籤")
    tags_list.add_argument("--tree")
    tags_list.add_argument("--related-to")
    tags_list.add_argument("--type", choices=TAG_TYPES)
    tags_list.add_argument("--limit", type=int, default=50)
    tags_sub.add_parser("audit", help="標籤健檢：重複、只用一次、過度使用、覆蓋率")
    backfill = tags_sub.add_parser(
        "backfill", help="把既有標籤依名稱與別名回補到舊記錄（預設只預覽）"
    )
    backfill.add_argument("--only", action="append", help="只處理這個標籤（可重複）")
    backfill.add_argument("--apply", action="store_true", help="預覽後確認並實際套用（真人終端機）")
    backfill.add_argument("--undo", action="store_true", help="移除所有由回補規則加上的標籤")

    pin = sub.add_parser("pin", help="PIN（保護危險命令；只能在你自己的終端機）")
    pin_sub = pin.add_subparsers(dest="pin_command", required=True, metavar="<動作>")
    pin_sub.add_parser("set", help="第一次設定 PIN，並顯示復原碼")
    pin_sub.add_parser("change", help="更換 PIN（需要目前的 PIN）")
    pin_sub.add_parser("reset", help="忘記 PIN 時用復原碼重設")

    phrase = sub.add_parser("phrase", help="觸發語句（AI 只能讀，增改刪須在你的終端機並輸入 PIN）")
    phrase_sub = phrase.add_subparsers(dest="phrase_command", required=True, metavar="<動作>")
    phrase_list = phrase_sub.add_parser("list", help="列出語句")
    phrase_list.add_argument("kind", nargs="?", choices=PHRASE_KINDS)
    phrase_add = phrase_sub.add_parser("add", help="新增語句")
    phrase_add.add_argument("kind", choices=PHRASE_KINDS)
    phrase_add.add_argument("text")
    phrase_set = phrase_sub.add_parser("set", help="改語句內容，或啟用、停用")
    phrase_set.add_argument("id", type=int)
    phrase_set.add_argument("--text")
    toggle = phrase_set.add_mutually_exclusive_group()
    toggle.add_argument("--enable", action="store_true")
    toggle.add_argument("--disable", action="store_true")
    phrase_remove = phrase_sub.add_parser("remove", help="刪除語句")
    phrase_remove.add_argument("id", type=int)

    notice = sub.add_parser("notice", help="所有個人資訊的首次儲存同意")
    notice_sub = notice.add_subparsers(dest="notice_command", required=True, metavar="<動作>")
    notice_sub.add_parser("status", help="目前是否會先詢問")
    notice_enable = notice_sub.add_parser("enable", help="重新開啟提醒（需要 PIN）")
    notice_enable.add_argument("level", choices=("personal", "medium"))

    sens = sub.add_parser("sensitivity", help="直接設定記錄的敏感度（需要 PIN）")
    sens_sub = sens.add_subparsers(dest="sensitivity_command", required=True, metavar="<動作>")
    sens_set = sens_sub.add_parser("set", help="設定等級（可調高或調低）")
    sens_set.add_argument("ref", help="記錄編號，如 r12")
    sens_set.add_argument("level", choices=SENSITIVITY_LEVELS)

    auto = sub.add_parser("auto", help="自動記錄政策（AI 只能讀；改動須在你的終端機並輸入 PIN）")
    auto_sub = auto.add_subparsers(dest="auto_command", required=True, metavar="<動作>")
    auto_sub.add_parser("status", help="目前的政策、類別與今天用了多少")
    auto_sub.add_parser("on", help="開啟自動記錄（需要 PIN）")
    auto_sub.add_parser("off", help="關閉自動記錄（需要 PIN）")
    auto_set = auto_sub.add_parser("set", help="設定類別的模式（需要 PIN）")
    auto_set.add_argument("name", help="類別名稱")
    auto_set.add_argument("mode", choices=("auto", "ask", "off"))
    auto_add = auto_sub.add_parser("add", help="新增類別（需要 PIN）")
    auto_add.add_argument("name")
    auto_add.add_argument("--desc", default="")
    auto_remove = auto_sub.add_parser("remove", help="刪除類別（需要 PIN）")
    auto_remove.add_argument("name")
    auto_limit = auto_sub.add_parser("limit", help="設定 24 小時內自動記錄的上限（需要 PIN）")
    auto_limit.add_argument("count", type=int)
    auto_exclude = auto_sub.add_parser("exclude", help="排除的專案路徑或名稱關鍵字（需要 PIN）")
    auto_exclude.add_argument("keyword")
    auto_exclude.add_argument("--remove", action="store_true")
    auto_hide = auto_sub.add_parser("hide", help="隱藏某日起所有自動記錄的記錄（可恢復）")
    auto_hide.add_argument("--since", required=True, help="YYYY-MM-DD（UTC）")

    recent = sub.add_parser("recent", help="最近存入的記錄（--auto 只看自動記錄的）")
    recent.add_argument("--auto", action="store_true")
    recent.add_argument("--days", type=int, default=7)
    recent.add_argument("--limit", type=int, default=50)

    sub.add_parser("reindex", help="重建全文索引（索引與資料不一致時使用）")
    return parser
