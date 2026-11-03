"""Install the repository's git hooks into this clone's .git/hooks.

Hooks live outside version control's reach (.git/hooks is not cloned), so run this after every
fresh clone:  python scripts/install-hooks.py

It never writes marked terms. `.git/sensitive-terms.txt` (one term per line, '#' starts a comment)
stays local; the script only creates it empty when it is missing.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HOOKS = ("pre-commit", "pre-push", "sensitive_check.py")
HEADER = "# One marked term per line. This file stays in .git and is never committed or pushed.\n"


def main() -> int:
    source = Path(__file__).resolve().parent / "hooks"
    git_dir = Path(
        subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir"],
            capture_output=True,
            text=True,
            check=True,
            cwd=source,
        ).stdout.strip()
    )
    target = git_dir / "hooks"
    target.mkdir(exist_ok=True)
    for name in HOOKS:
        shutil.copyfile(source / name, target / name)
        (target / name).chmod(0o755)
        print(f"installed {name}")
    terms = git_dir / "sensitive-terms.txt"
    if not terms.exists():
        terms.write_text(HEADER, encoding="utf-8")
        print("created an empty .git/sensitive-terms.txt: add the terms you want blocked")
    else:
        print("kept the existing .git/sensitive-terms.txt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
