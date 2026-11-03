"""Make a manual-review sheet from an AI-layer result file.

    python scripts/benchmark_sample.py benchmark-output/<result>.json [--seed 1]

Picks the 5 lowest-scoring and 5 randomly chosen other questions (seeded, so the same sheet comes
back), and writes `benchmark-output/sample-sheet.md` with each question, the saved answer, the
automatic score and an empty verdict line. The sheet holds question text, so it stays in the
ignored `benchmark-output/` folder; this script prints only ids and counts.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    data = json.loads(args.result.read_text(encoding="utf-8"))
    rows = [r for r in data.get("questions", []) if "answer" in r and "score" in r]
    if len(rows) < 10:
        print("fewer than 10 scored answers; nothing to sample")
        return 1
    by_score = sorted(rows, key=lambda r: (r["score"], r["id"]))
    lowest = by_score[:5]
    rest = [r for r in rows if r not in lowest]
    picked = lowest + random.Random(args.seed).sample(rest, 5)
    lines = [f"# 評分抽樣複核（{args.result.name}，seed={args.seed}）", ""]
    for row in picked:
        adjusted = row.get("adjusted_score", "（無）")
        lines += [
            f"## {row['id']}　自動分數 {row['score']}　調整分 {adjusted}",
            "",
            f"問題：{row.get('question', '')}",
            "",
            "回答：",
            "",
            str(row["answer"]),
            "",
            "你的判斷（對 / 評分太高 / 評分太低）：＿＿＿　備註：",
            "",
        ]
    sheet = ROOT / "benchmark-output" / "sample-sheet.md"
    sheet.write_text("\n".join(lines), encoding="utf-8")
    print("sampled:", ", ".join(r["id"] for r in picked))
    print(f"sheet written to {sheet}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
