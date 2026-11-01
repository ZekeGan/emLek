"""Scale run: 36,000 realistic-length rows. Records timings; asserts only correctness."""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any

import pytest
import synth

from emlek.config import load_config
from emlek.core import search, service
from emlek.core.db import Database
from emlek.core.permissions import Caller, Channel
from emlek.core.vault import init_vault

ROWS = 36_000
REPORT_DIR = Path(__file__).resolve().parents[2] / "benchmark-output"
DISASTER_SECONDS = 15  # not a target: only catches something badly broken


@pytest.mark.scale
def test_scale_36k(tmp_path: Path) -> None:
    caller = Caller(Channel.CLI)
    path = tmp_path / "vault"
    init_vault(caller, path)
    db = Database.open(load_config(path).db_path)
    try:
        started = time.perf_counter()
        with db.transaction() as conn:
            for body, event, created in synth.bulk_rows(random.Random(5), ROWS):
                record_id = service._insert_record(conn, created)
                precision = service.infer_precision(event) if event else None
                service._insert_revision(
                    conn, record_id, 1, body, "original", created, event, precision, None
                )
        load_seconds = time.perf_counter() - started
        db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        size_mb = db.path.stat().st_size / 1e6

        timings: dict[str, Any] = {}

        def timed(label: str, **kwargs: Any) -> dict[str, Any]:
            begin = time.perf_counter()
            result = search.search(db, caller, timezone="+09:00", **kwargs)
            elapsed = time.perf_counter() - begin
            timings[label] = {"seconds": round(elapsed, 3), "total": result["total"]}
            assert elapsed < DISASTER_SECONDS, label
            return result

        needle = timed(label="fts_needle_12_chars", query="zxqvw-needle")
        short_needle = timed(label="like_2_chars_needle", query="針山")
        third_needle = timed(label="fts_3_chars_needle", query="桜の針")
        timed(label="fts_3_chars_common", query="新幹線", limit=20)
        timed(label="like_2_chars_common", query="東京", limit=20)
        timed(label="like_1_char_common", query="寺", limit=20)
        timed(label="fts_plus_like", query="新幹線 東京", limit=20)
        timed(label="absent_term_fallback", query="存在しない言葉です")
        timed(label="date_range_month_by_event", date_from="2026-05", date_to="2026-05", limit=20)
        timed(
            label="date_range_by_created",
            date_field="created_at",
            date_from="2026-03-10",
            date_to="2026-03-10",
        )
        timed(label="browse_newest_event", order="event_time", limit=20)
        deep = timed(label="browse_first_page", order="created_at", direction="asc", limit=100)
        timed(
            label="browse_second_page",
            order="created_at",
            direction="asc",
            limit=100,
            cursor=deep["next_cursor"],
        )
        timed(label="count_with_two_char_filter", query="東京", limit=1)

        assert needle["total"] == 1
        assert short_needle["total"] == 1
        assert third_needle["total"] == 1
        REPORT_DIR.mkdir(exist_ok=True)
        report = {
            "layer": "system",
            "milestone": "M2",
            "rows": ROWS,
            "load_seconds": round(load_seconds, 1),
            "db_megabytes": round(size_mb, 1),
            "queries": timings,
            "note": "synthetic text, one machine; recorded for comparison, not a target",
        }
        (REPORT_DIR / "scale-m2.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        db.close()
