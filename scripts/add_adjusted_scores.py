"""Add the missing `adjusted_score` to old AI-layer result files, without touching the originals.

    python scripts/add_adjusted_scores.py

Reads every `benchmark-output/*.json`, scores the saved answers again with the current rules
(`tests/benchmark/scoring.py`, no model calls), and writes a copy to `benchmark-output/rescored/`
with `adjusted_score` and `score_current_rule` added to each question row. The stored `score` is
never changed. A row whose current-rule raw score differs from the stored one was graded under an
older rule or another corpus; its adjusted score is marked `adjusted_comparable: false` and should
not be averaged with the others.

Prints counts only, never question or answer text.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests" / "benchmark"))

import bank  # noqa: E402
import scoring  # noqa: E402
import synth  # noqa: E402


def main() -> int:
    out_dir = ROOT / "benchmark-output"
    target = out_dir / "rescored"
    target.mkdir(exist_ok=True)
    corpora = {600: synth.build_corpus(), bank.SCALE_FILLER: synth.build_corpus(bank.SCALE_FILLER)}
    totals = {"files": 0, "already": 0, "rows": 0, "comparable": 0, "different": 0, "skipped": 0}
    for path in sorted(out_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data.get("questions")
        if not isinstance(rows, list):
            continue
        totals["files"] += 1
        if any("adjusted_score" in row for row in rows if isinstance(row, dict)):
            totals["already"] += 1
            continue
        for row in rows:
            if not isinstance(row, dict) or "answer" not in row or row.get("id") not in bank.SPECS:
                totals["skipped"] += 1
                continue
            corpus = corpora[bank.SCALE_FILLER if row["id"] in bank.SCALE_IDS else 600]
            now = scoring.score_spec(bank.SPECS[row["id"]], corpus, row["answer"])
            totals["rows"] += 1
            row["score_current_rule"] = now["score"]
            row["adjusted_score"] = now["adjusted_score"]
            row["adjusted_comparable"] = now["score"] == row.get("score")
            totals["comparable" if row["adjusted_comparable"] else "different"] += 1
        data["adjusted_added"] = "adjusted_score added by scripts/add_adjusted_scores.py"
        (target / path.name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(totals)
    print(f"copies are in {target}; the originals were not modified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
