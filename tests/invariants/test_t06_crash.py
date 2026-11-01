"""T06: killing the process in the middle of writing never corrupts the database."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from emlek.config import load_config

WRITER = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from emlek.core import service
    from emlek.core.db import Database
    from emlek.core.permissions import Caller, Channel

    db = Database.open(Path(sys.argv[1]))
    caller = Caller(Channel.CLI)
    n = 0
    while True:
        n += 1
        service.save(db, caller, body=f"crash-test-{n}")
        print(n, flush=True)
    """
)


@pytest.mark.slow
def test_killed_writer_leaves_a_consistent_database(data_dir: Path, tmp_path: Path) -> None:
    script = tmp_path / "writer.py"
    script.write_text(WRITER, encoding="utf-8")
    db_path = load_config(data_dir).db_path
    proc = subprocess.Popen(
        [sys.executable, str(script), str(db_path)], stdout=subprocess.PIPE, text=True
    )
    assert proc.stdout is not None
    last_printed = 0
    try:
        for line in proc.stdout:
            last_printed = int(line)
            if last_printed >= 25:
                break
    finally:
        proc.kill()
        proc.wait()

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        records = conn.execute("SELECT count(*) FROM records").fetchone()[0]
        revisions = conn.execute("SELECT count(*) FROM revisions WHERE version_no = 1").fetchone()[
            0
        ]
        assert records == revisions
        assert records >= last_printed  # everything reported as saved is really there
        assert records <= last_printed + 1  # at most one commit finished before it could print
        bodies = [r[0] for r in conn.execute("SELECT body FROM revisions ORDER BY record_id")]
        assert bodies == [f"crash-test-{i}" for i in range(1, records + 1)]
    finally:
        conn.close()
