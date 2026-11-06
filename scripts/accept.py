"""Repeatable acceptance checks that need neither a PIN nor a person at a terminal.

    python scripts/accept.py

Everything runs against a throwaway data folder that is removed at the end. Steps that need the
PIN or a real terminal stay manual (see the acceptance lists in docs/PROGRESS.md); here they are
only checked to be *refused* when run from a script, which is the gate working as designed. The
script never passes a PIN (no argument, no environment variable, no standard input) and never
tries to get around a gate.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

NOT_PERMITTED = 3


@dataclass
class Check:
    name: str
    args: list[str]
    code: int = 0
    contains: tuple[str, ...] = ()
    absent: tuple[str, ...] = ()


def _project_python() -> str:
    """The project's own interpreter: the `python` on PATH may be another install without emlek."""
    venv = Path(__file__).resolve().parent.parent / ".venv" / "Scripts" / "python.exe"
    return str(venv) if venv.exists() else sys.executable


def _run(data_dir: Path, args: list[str]) -> tuple[int, str]:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run(
        [_project_python(), "-X", "utf8", "-m", "emlek", "--data-dir", str(data_dir), *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    return done.returncode, done.stdout + done.stderr


def _checks(work: Path) -> list[Check]:
    notes = work / "notes"
    notes.mkdir()
    (notes / "a.txt").write_text("匯入預覽用的一則筆記 IMPORT-ALFA", encoding="utf-8")
    backups = work / "bk"
    exports = work / "out"
    return [
        Check("init works without a PIN", ["init"]),
        Check("save", ["save", "--text", "今天在京都吃了拉麵 RAMEN-ONE"], contains=("r1.v1",)),
        Check("search finds it", ["search", "RAMEN-ONE"], contains=("r1",)),
        Check(
            "save with a tag",
            ["save", "--text", "第二筆 SECOND-TWO", "--tag", "美食"],
            contains=("美食",),
        ),
        Check("search by tag", ["search", "--tag", "美食"], contains=("r2",)),
        Check(
            "amend adds a version", ["amend", "r1", "--text", "補充 RAMEN-ONE v2"], contains=("v2",)
        ),
        Check("hide and unhide", ["hide", "r2"], contains=("隱藏",)),
        Check("hidden is not found", ["search", "SECOND-TWO"], absent=("r2.v1",)),
        Check("unhide", ["unhide", "r2"]),
        Check("stats", ["stats"], contains=("記錄 2 筆",)),
        Check("backup (plain)", ["backup", "--to", str(backups)], contains=("完整性檢查通過",)),
        Check("export", ["export", "--out", str(exports)]),
        Check("import previews and writes nothing", ["import", str(notes)], contains=("預覽",)),
        Check("stats unchanged after the preview", ["stats"], contains=("記錄 2 筆",)),
        Check(
            "auto-record is ready but still needs consent", ["auto", "status"], contains=("開啟",)
        ),
        Check("recent", ["recent"], contains=("r2",)),
        Check("cleanup previews", ["cleanup"], contains=("預覽",)),
        # the gates: from a script these must all be refused
        Check("auto on is refused", ["auto", "on"], code=NOT_PERMITTED),
        Check(
            "automatic save is refused before personal consent",
            ["save", "--text", "x", "--source", "auto:生活點滴"],
            code=3,
            contains=("所有個人資訊",),
        ),
        Check("purge is refused", ["purge", "r1"], code=NOT_PERMITTED),
        Check("purge --finish is refused", ["purge", "--finish"], code=NOT_PERMITTED),
        Check("cleanup --apply is refused", ["cleanup", "--apply"], code=NOT_PERMITTED),
        Check("import --apply is refused", ["import", str(notes), "--apply"], code=NOT_PERMITTED),
        Check("phrase add is refused", ["phrase", "add", "save", "記一下"], code=NOT_PERMITTED),
        Check(
            "sensitivity set is refused", ["sensitivity", "set", "r1", "high"], code=NOT_PERMITTED
        ),
        Check("everything is still there", ["stats"], contains=("記錄 2 筆",)),
    ]


def _restore_check(data_dir: Path, work: Path) -> tuple[bool, str]:
    files = sorted((work / "bk").glob("*.db"))
    if not files:
        return False, "no backup file was made"
    code, _ = _run(data_dir, ["restore", str(files[0])])
    return code == NOT_PERMITTED, f"exit {code}"


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="emlek-accept-"))
    data_dir = work / "vault"
    failures = 0
    try:
        rows: list[tuple[str, bool, str]] = []
        for check in _checks(work):
            code, text = _run(data_dir, check.args)
            problems = []
            if code != check.code:
                problems.append(f"exit {code}, wanted {check.code}")
            problems += [f"missing {s!r}" for s in check.contains if s not in text]
            problems += [f"unexpected {s!r}" for s in check.absent if s in text]
            rows.append((check.name, not problems, "; ".join(problems)))
        ok, detail = _restore_check(data_dir, work)
        rows.append(("restore is refused", ok, "" if ok else detail))
        for name, passed, detail in rows:
            print(f"[{'ok' if passed else 'FAILED'}] {name}" + (f"  ({detail})" if detail else ""))
            failures += 0 if passed else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"{len(rows) - failures}/{len(rows)} passed; the throwaway folder was removed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
