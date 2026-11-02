"""emlek search / emlek reindex"""

from __future__ import annotations

import argparse

from emlek.cli.commands.common import cli_caller, data_dir_of, open_vault
from emlek.cli.output import Output
from emlek.config import load_config
from emlek.core import search as core_search


def run(args: argparse.Namespace) -> Output:
    timezone = load_config(data_dir_of(args)).timezone
    db = open_vault(args)
    try:
        result = core_search.search(
            db,
            cli_caller(),
            query=args.query,
            kinds=args.kinds,
            date_field=args.date_field,
            date_from=args.date_from,
            date_to=args.date_to,
            order=args.order,
            direction=args.dir,
            limit=args.limit,
            cursor=args.cursor,
            all_versions=args.all_versions,
            include_hidden=args.include_hidden,
            current_only=args.current_only,
            tags=args.tags,
            match=args.match,
            tag_types=args.tag_types,
            expand=not args.no_expand,
            facets=args.facets,
            max_sensitivity=args.max_sensitivity,
            timezone=timezone,
        )
    finally:
        db.close()
    lines = []
    for item in result["results"]:
        when = item["event_time"] or "（無事件時間）"
        lines.append(f"{item['revision_ref']}　{item['kind']}　{when}　{item['snippet']}")
    lines.append(
        f"-----\n共 {result['total']} 筆（排序：{result['order']} {result['dir']}）"
        + (f"，另有 {result['undated']} 筆沒有事件時間" if result["undated"] else "")
        + (f"，{result['withheld']} 筆因敏感度上限未顯示" if result["withheld"] else "")
    )
    if result.get("expanded_tags") and len(result["expanded_tags"]) > 1:
        lines.append("標籤展開：" + "、".join(result["expanded_tags"]))
    if result.get("tag_coverage"):
        share = result["tag_coverage"]
        lines.append(
            f"標籤覆蓋：{share['tagged']} 筆有標籤、{share['untagged']} 筆沒有"
            "（沒標的不會被標籤搜尋找到）"
        )
    if result.get("unknown_tags"):
        lines.append("找不到的標籤：" + "、".join(result["unknown_tags"]))
    if result.get("similar_tags"):
        lines.append("相近的標籤：" + "、".join(result["similar_tags"]))
    if result.get("facets"):
        lines.append(
            "常見標籤：" + "、".join(f"{f['name']} {f['count']}" for f in result["facets"])
        )
    summary = result.get("summary")
    if summary:
        spread = summary.get("by_month") or summary.get("by_year") or {}
        lines.append(
            f"摘要：{summary['total']} 筆，{summary['first']} ～ {summary['last']}；"
            + "、".join(f"{k} {v}" for k, v in spread.items())
            + f"（{summary['note']}）"
        )
    if result["next_cursor"]:
        lines.append(f"下一頁：--cursor {result['next_cursor']}")
    for hint in result["hints"]:
        lines.append(f"提示：{hint}")
    if "index_stale" in result["warnings"]:
        lines.append("注意：搜尋索引與資料不一致，已改用完整掃描，請執行 emlek reindex")
    return Output(result, "\n".join(lines))


def run_reindex(args: argparse.Namespace) -> Output:
    db = open_vault(args)
    try:
        result = core_search.reindex(db, cli_caller())
    finally:
        db.close()
    return Output(result, f"已重建索引：{result['indexed']} / {result['revisions']} 個版本")
