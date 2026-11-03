"""Mechanical checks, so "all green" is something that was run rather than something reported.

    python scripts/check.py          ruff, format check, mypy and the quick pytest set (minutes)
    python scripts/check.py --fast   ruff, format check and mypy only (what the pre-push hook runs)
    python scripts/check.py --full   everything, including the slow and scale tests

Prints each step with its exit code and the commit it ran against, and exits non-zero on the
first failure.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _steps(mode: str) -> list[tuple[str, list[str]]]:
    py = sys.executable
    steps = [
        ("ruff check", [py, "-m", "ruff", "check", "src", "tests"]),
        ("ruff format", [py, "-m", "ruff", "format", "--check", "src", "tests"]),
        ("mypy", [py, "-m", "mypy"]),
    ]
    if mode == "quick":
        steps.append(
            (
                "pytest (not slow, not scale)",
                [py, "-m", "pytest", "-q", "-m", "not slow and not scale"],
            )
        )
    elif mode == "full":
        steps.append(("pytest (everything)", [py, "-m", "pytest", "-q"]))
    return steps


def main() -> int:
    mode = "fast" if "--fast" in sys.argv else "full" if "--full" in sys.argv else "quick"
    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    print(f"checking {head}{' (+ uncommitted changes)' if dirty else ''}, mode={mode}")
    for label, command in _steps(mode):
        started = time.monotonic()
        code = subprocess.run(command, cwd=ROOT).returncode
        seconds = time.monotonic() - started
        print(f"[{'ok' if code == 0 else 'FAILED'}] {label} (exit {code}, {seconds:.0f}s)")
        if code != 0:
            return code
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
