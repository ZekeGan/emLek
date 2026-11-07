"""Run the public dialogue bank on subscription Haiku; never run from pytest.

python tests/benchmark/dialogue_runner.py mcp-only --runs 3 --budget-usd .15
Run full-rules separately with the same cap (combined cap .30). Evidence is ignored.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

import dialogues
from ai_runner import claude_exe, tool_names

from emlek.config import load_config
from emlek.core import auto, notice, service, versions
from emlek.core.db import Database
from emlek.core.permissions import Caller, Channel
from emlek.core.vault import init_vault
from emlek.mcp_server.rules import prompt_for
from emlek.mcp_server.server import RULES_VERSION, build_server

ROOT = Path(__file__).resolve().parents[2]
MODEL = "claude-haiku-5-5"
PERSON = Caller(Channel.CLI, interactive=True, pin_verified=True)


def dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def fingerprint() -> str:
    paths = sorted(p for p in (ROOT / "src").rglob("*") if p.suffix in (".py", ".sql"))
    paths += [ROOT / "docs/AGENT_RULES.md", Path(__file__), Path(dialogues.__file__)]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def original_match(expected: str, actual: str) -> str:
    """Only certify exact text or conservative natural-language layout equivalents.

    Other changes need review. Never strip all punctuation or merge separated words.
    """
    if expected == actual:
        return "exact"
    if re.search(r"https?://|`|\b\w+://|\b\w+@\w+", expected):
        return "review"
    table = str.maketrans("，：；！？（）", ",:;!?()")

    def normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.translate(table)).strip()

    return "layout" if normalize(expected) == normalize(actual) else "review"


def seed(db: Database, name: str) -> None:
    if name == "inactive":
        return
    notice.acknowledge(db.conn)
    if name == "disabled":
        auto.set_enabled(db, PERSON, on=False)
    elif name == "corrected":
        ref = service.save(db, PERSON, body="今天去了京都。")["ref"]
        service.amend(db, PERSON, ref=ref, body="今天去了大阪。")
    elif name in ("hidden", "invalidated"):
        word = "金色企鵝" if name == "hidden" else "紫色河馬"
        ref = service.save(db, PERSON, body=f"合成旅遊測試暗號是{word}。")["ref"]
        if name == "invalidated":
            service.save(
                db,
                PERSON,
                body=f"合成摘要：測試暗號是{word}。",
                kind="ai_summary",
                links=[{"ref": ref, "relation": "summarizes"}],
            )
        versions.hide(db, PERSON, ref=ref)
    elif name == "years":
        for i in range(52):
            month = i % 26
            service.save(
                db,
                PERSON,
                body=f"合成散步記錄 {i}",
                event_time=f"{2023 + month // 12}-{month % 12 + 1:02d}",
                event_time_precision="month",
            )
        for i in range(3):
            service.save(db, PERSON, body=f"合成跑步記錄 {i}")
    elif name == "meal":
        service.save(db, PERSON, body="合成午餐：今天在京都吃拉麵。")
    elif name == "tags":
        service.save(db, PERSON, body="合成城市標籤", tags=["京都"])
    elif name == "limit":
        for i in range(30):
            service.save(db, PERSON, body=f"合成生活記錄 {i}", source="auto:生活點滴")


def snapshot(vault: Path) -> dict[str, Any]:
    db = Database.open(load_config(vault).db_path)
    try:
        rows = db.conn.execute(
            "SELECT rec.id,rec.hidden,r.version_no,r.body,r.kind,r.event_time,"
            "r.event_time_precision FROM records rec JOIN revisions r ON r.record_id=rec.id"
            " WHERE r.version_no=(SELECT max(v.version_no) FROM revisions v"
            " WHERE v.record_id=rec.id) ORDER BY rec.id"
        )
        names = [c[0] for c in rows.description]
        return {
            "started": not notice.is_enabled(db.conn),
            "records": [dict(zip(names, r, strict=True)) for r in rows],
            "tags": [
                list(r)
                for r in db.conn.execute(
                    "SELECT rt.record_id,t.name FROM record_tags rt JOIN tags t ON t.id=rt.tag_id"
                    " ORDER BY rt.record_id,t.name"
                )
            ],
        }
    finally:
        db.close()


def judge(
    turn: dialogues.Turn, before: dict[str, Any], after: dict[str, Any], text: str, read_only: bool
) -> dict[str, Any]:
    delta = len(after["records"]) - len(before["records"])
    checks = {
        "record_delta": delta == turn.delta,
        "answer_contains": all(s in text for s in turn.contains),
        "answer_forbids": all(s not in text for s in turn.forbids),
    }
    if turn.started is not None:
        checks["started"] = after["started"] == turn.started
    if read_only:
        checks["readonly"] = after == before
    if turn.delta == 0 and turn.version is None:
        checks["no_write"] = after["records"] == before["records"] and after.get(
            "tags"
        ) == before.get("tags")
    match = None
    if turn.original is not None:
        match = (
            original_match(turn.original, after["records"][-1]["body"])
            if after["records"]
            else "missing"
        )
        checks["original"] = match in ("exact", "layout")
        checks["original_kind"] = (
            bool(after["records"]) and after["records"][-1]["kind"] == "original"
        )
    if turn.tags_any:
        last_id = after["records"][-1]["id"] if after["records"] else None
        checks["tags_repaired"] = any(
            record_id == last_id and name in turn.tags_any for record_id, name in after["tags"]
        )
    if turn.version is not None:
        checks["version"] = (
            bool(after["records"]) and after["records"][-1]["version_no"] == turn.version
        )
    previous = {str(r["id"]): r for r in before["records"]}
    changed = {
        str(r["id"])
        for r in after["records"]
        if str(r["id"]) not in previous
        or r.get("version_no") != previous[str(r["id"])].get("version_no")
    }
    ids = {str(r["id"]) for r in after["records"]}
    markers = re.findall(r"◆ emLek｜r(\d+)\.✔️", text)
    checks["markers_exist"] = all(r in ids for r in markers)
    checks["markers_correspond_to_write"] = all(r in changed for r in markers)
    return {"checks": checks, "original_match": match, "mechanical_pass": all(checks.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=("mcp-only", "full-rules"))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--budget-usd", type=float, default=0.15)
    parser.add_argument("--out", default="dialogue-expansion-20261107")
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    if args.runs < 1 or not 0 < args.budget_usd <= 0.15:
        parser.error("runs must be positive; this batch caps each profile at US$0.15")
    base = (ROOT / "benchmark-output" / args.out).resolve()
    if not base.is_relative_to((ROOT / "benchmark-output").resolve()):
        parser.error("output must remain inside benchmark-output")
    base = base / args.profile
    base.mkdir(parents=True, exist_ok=True)
    frozen = fingerprint()
    total = sum(len(c.turns) for c in dialogues.CASES.values()) * args.runs
    estimate = total * 0.0012
    print(
        json.dumps(
            {
                "profile": args.profile,
                "scenarios": len(dialogues.CASES),
                "turns": total,
                "estimate_usd": estimate,
                "cap_usd": args.budget_usd,
            }
        ),
        flush=True,
    )
    if estimate > args.budget_usd:
        raise SystemExit("estimate exceeds cap")
    report = base / "summary.json"
    rows = json.loads(report.read_text(encoding="utf-8")) if report.exists() else []
    spent = sum(r["cost_delta"] for r in rows)
    done_keys = {r["key"] for r in rows}
    session_cost = {r["session"]: r["result"].get("total_cost_usd", 0) for r in rows}
    for run in range(1, args.runs + 1):
        for case_id, case in dialogues.CASES.items():
            folder = base / f"run-{run}" / case_id
            manifest_path = folder / "manifest.json"
            vault = folder / "vault"
            if not manifest_path.exists():
                if folder.exists():
                    raise SystemExit("partial fixture; inspect rather than replacing")
                folder.mkdir(parents=True)
                init_vault(PERSON, vault)
                db = Database.open(load_config(vault).db_path)
                try:
                    seed(db, case.seed)
                finally:
                    db.close()
                tools = asyncio.run(build_server(vault, read_only=case.read_only).list_tools())
                dump(
                    manifest_path,
                    {
                        "source_sha256": frozen,
                        "rules_version": RULES_VERSION,
                        "session": str(uuid.uuid4()),
                        "model": MODEL,
                        "profile": args.profile,
                        "holdout": case.holdout,
                        "tools": [t.name for t in tools],
                    },
                )
                dump(
                    folder / "mcp.json",
                    {
                        "mcpServers": {
                            "emlek": {
                                "command": str(ROOT / ".venv/Scripts/emlek.exe"),
                                "args": [
                                    "--data-dir",
                                    str(vault),
                                    "mcp",
                                    *(["--read-only"] if case.read_only else []),
                                ],
                            }
                        }
                    },
                )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert manifest["source_sha256"] == frozen
            if args.preflight:
                continue
            session = manifest["session"]
            for index, turn in enumerate(case.turns):
                key = f"run-{run}/{case_id}/{index + 1}"
                if key in done_keys:
                    continue
                assert fingerprint() == frozen, "source changed during run"
                if args.budget_usd - spent < 0.006:
                    raise SystemExit("budget reserve reached")
                raw = folder / f"{index + 1}.jsonl"
                request = folder / f"{index + 1}.request.json"
                if raw.exists() or request.exists():
                    raise SystemExit("request without checkpoint; inspect, do not repeat a write")
                if turn.fresh_chat:
                    session = str(uuid.uuid4())
                before = snapshot(vault)
                dump(request, {"question": turn.text, "before": before})
                cmd = [
                    claude_exe(),
                    "-p",
                    turn.text,
                    "--model",
                    MODEL,
                    "--output-format",
                    "stream-json",
                    "--verbose",
                    "--mcp-config",
                    str(folder / "mcp.json"),
                    "--strict-mcp-config",
                    "--tools",
                    "",
                    "--allowedTools",
                    *tool_names(read_only=case.read_only, allow_record_changes=True),
                    "--setting-sources",
                    "",
                    "--system-prompt-snapshot",
                    "off",
                    "--max-budget-usd",
                    str(args.budget_usd - spent),
                    "--resume" if index and not turn.fresh_chat else "--session-id",
                    session,
                ]
                if args.profile == "full-rules":
                    cmd += ["--append-system-prompt", prompt_for(read_only=case.read_only)]
                try:
                    result = subprocess.run(
                        cmd,
                        cwd=folder,
                        capture_output=True,
                        stdin=subprocess.DEVNULL,
                        timeout=240,
                        env={**os.environ, "PYTHONUTF8": "1"},
                    )
                except subprocess.TimeoutExpired as exc:
                    raw.write_bytes(exc.stdout or b"")
                    raise SystemExit("timeout; preserved evidence, no automatic retry") from exc
                raw.write_bytes(result.stdout)
                (folder / f"{index + 1}.stderr").write_bytes(result.stderr)
                events = [
                    json.loads(line)
                    for line in result.stdout.decode("utf-8").splitlines()
                    if line.startswith("{")
                ]
                final = next((e for e in reversed(events) if e.get("type") == "result"), None)
                if final is None:
                    raise SystemExit("incomplete raw evidence; do not retry")
                increments = final.get("model_usage_since_last_result")
                cost = (
                    sum(u["costUSD"] for u in increments.values())
                    if increments
                    else max(0, final.get("total_cost_usd", 0) - session_cost.get(session, 0))
                )
                session_cost[session] = final.get("total_cost_usd", 0)
                spent += cost
                after = snapshot(vault)
                text = final.get("result", "")
                rows.append(
                    {
                        "key": key,
                        "session": session,
                        "question": turn.text,
                        "answer": text,
                        "before": before,
                        "after": after,
                        "result": final,
                        "cost_delta": cost,
                        "answer_review": "pending",
                        **judge(turn, before, after, text, case.read_only),
                    }
                )
                dump(report, rows)
                print(
                    json.dumps({"key": key, "spent_usd": round(spent, 8), "complete": len(rows)}),
                    flush=True,
                )
                assert not final.get("is_error") and not final.get("permission_denials")
                assert set(final.get("modelUsage", {})) == {MODEL}
    assert args.preflight or len(rows) == total
    print(
        json.dumps(
            {
                "profile": args.profile,
                "preflight": args.preflight,
                "complete": len(rows),
                "spent_usd": spent,
                "source_sha256": frozen,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
