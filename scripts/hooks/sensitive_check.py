"""Block commits/pushes that add any term listed in .git/sensitive-terms.txt.

Only marked terms are checked (no full-text scan). Matching uses NFKC + casefold on both
sides. Local to this clone; never pushed. Usage: sensitive_check.py pre-commit|pre-push
"""

import os
import subprocess
import sys
import unicodedata

ZERO = "0" * 40


def norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout


def added_text(diff_text: str) -> str:
    keep = []
    for line in diff_text.splitlines():
        if line.startswith(("+++", "---", "diff ", "index ", "@@", "-")):
            continue
        keep.append(line[1:] if line.startswith("+") else line)
    return "\n".join(keep)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre-commit"
    git_dir = git("rev-parse", "--git-dir").strip()
    path = os.path.join(git_dir, "sensitive-terms.txt")
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as fh:
        terms = [
            (n, norm(t.strip())) for n, t in enumerate(fh, 1) if t.strip() and not t.startswith("#")
        ]
    if not terms:
        return 0
    if mode == "pre-commit":
        texts = [("staged changes", added_text(git("diff", "--cached", "-U0", "--no-color")))]
    else:
        texts = []
        for line in sys.stdin.read().splitlines():
            parts = line.split()
            if len(parts) != 4 or parts[1] == ZERO:
                continue
            ref, local, _remote_ref, remote = parts
            rng = local if remote == ZERO else f"{remote}..{local}"
            texts.append(
                (ref, added_text(git("log", "-p", "-U0", "--no-color", "--format=%B", rng)))
            )
    status = 0
    for label, text in texts:
        haystack = norm(text)
        for n, term in terms:
            if term in haystack:
                print(
                    f"{mode}: blocked. Marked term on line {n} of .git/sensitive-terms.txt "
                    f"appears in {label}.",
                    file=sys.stderr,
                )
                status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
