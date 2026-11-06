"""Local development workflow. No model calls, vault access, tags or force pushes."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
STATES = ("進行中", "待驗收", "待決定", "待排程")
ENTRY_BUDGET = 2600


def inside(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if re.match(r"^[A-Za-z]:", name) or not path.is_relative_to(root.resolve()):
        raise ValueError(f"路徑必須在工作區內：{name}")
    return path


def git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, encoding="utf-8", check=True, timeout=60
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise ValueError((exc.stderr or exc.stdout or str(exc)).strip()) from exc


def registry(root: Path) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads(
        inside(root, "docs/areas.json").read_text(encoding="utf-8")
    )["areas"]
    return data


def files(root: Path) -> list[Path]:
    result = [
        root / n
        for n in (
            "AGENTS.md",
            "CLAUDE.md",
            "README.md",
            "CHANGELOG.md",
            "pyproject.toml",
            "uv.lock",
            ".gitignore",
        )
        if (root / n).is_file()
    ]
    for folder in ("src", "tests", "scripts", "docs"):
        for path in (root / folder).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                inside(root, path.relative_to(root).as_posix())
                result.append(path)
    for path in result:
        inside(root, path.relative_to(root).as_posix())
    return sorted(result)


def changed_files(root: Path) -> list[str]:
    tracked = git(root, "diff", "--name-only", "HEAD").splitlines()
    new = git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted(set(tracked + new))


def product_change(names: list[str]) -> bool:
    return any(n.startswith("src/") or n in ("pyproject.toml", "uv.lock") for n in names)


def verification_mode(names: list[str]) -> str:
    if product_change(names):
        return "full"
    workflow_only = {"scripts/workflow.py", "scripts/check.py", "tests/unit/test_workflow.py"}
    if any(n.startswith(("scripts/", "tests/")) and n not in workflow_only for n in names):
        return "quick"
    return "docs"


def prose(text: str) -> str:
    return re.sub(r"(?ms)^\s*(`{3,}|~{3,})[^\n]*\n.*?^\s*\1[^\n]*(?:\n|$)", "", text)


def anchors(text: str) -> set[str]:
    seen: dict[str, int] = {}
    result = set(re.findall(r'\b(?:id|name)=["\']([^"\']+)["\']', prose(text)))
    for heading in re.findall(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", prose(text)):
        slug = re.sub(r"[^\w -]", "", heading.lower()).replace(" ", "-")
        number = seen.get(slug, 0)
        result.add(f"{slug}-{number}" if number else slug)
        seen[slug] = number + 1
    return result


def section(root: Path, target: str) -> str:
    name, _, anchor = target.partition("#")
    text = inside(root, name).read_text(encoding="utf-8")
    if not anchor:
        return text
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if anchor in anchors(line):
            level = len(line) - len(line.lstrip("#"))
            end = next(
                (
                    i
                    for i in range(index + 1, len(lines))
                    if re.match(rf"^#{{1,{level}}} ", lines[i])
                ),
                len(lines),
            )
            return "\n".join(lines[index:end])
    raise ValueError(f"找不到章節：{target}")


def context(root: Path, area_id: str, *, read: bool = False) -> str:
    area = next((a for a in registry(root) if a["id"] == area_id), None)
    if area is None:
        raise ValueError(f"未知領域：{area_id}")
    text = (
        f"{area_id}\n規格：{', '.join(area['docs'])}\n程式：{', '.join(area['code'])}"
        f"\n測試：{' '.join(area['tests'])}"
    )
    if read:
        text += "\n\n" + "\n\n".join(section(root, target) for target in area["docs"])
    return text


def items(root: Path) -> list[dict[str, str]]:
    state = ""
    result = []
    for line in inside(root, "docs/PROGRESS.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            state = line[3:].strip()
        match = re.match(r"^- \*\*(W\d+)\*\* (.+)", line)
        if match:
            result.append({"id": match[1], "title": match[2], "state": state})
    return result


def problems(root: Path) -> list[str]:
    errors: list[str] = []
    areas = registry(root)
    names = [p.relative_to(root).as_posix() for p in files(root)]
    code = [n for n in names if n.startswith("src/")]
    area_ids = [a["id"] for a in areas]
    if len(set(area_ids)) != len(area_ids):
        errors.append("領域編號重複")
    for area in areas:
        for pattern in area["code"]:
            if not any(fnmatch.fnmatchcase(n, pattern) for n in names):
                errors.append(f"{area['id']}：程式樣式沒有匹配 {pattern}")
        for name in area["tests"]:
            if not inside(root, name).is_file():
                errors.append(f"{area['id']}：測試不存在 {name}")
        for target in area["docs"]:
            try:
                section(root, target)
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
    for name in code:
        if not any(fnmatch.fnmatchcase(name, pattern) for a in areas for pattern in a["code"]):
            errors.append(f"程式未登錄：{name}")
    for name in names:
        if not name.endswith(".md") or any(
            f"docs/{folder}/" in name for folder in ("archive", "history", "decisions")
        ):
            continue
        path = root / name
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]*\]\(([^\s)]+)\)", prose(text)):
            if "://" in target or target.startswith("mailto:"):
                continue
            destination, _, anchor = unquote(target).partition("#")
            linked = (path.parent / destination).resolve() if destination else path
            if not linked.is_relative_to(root.resolve()) or not linked.exists():
                errors.append(f"{name}：無效連結 {target}")
            elif (
                anchor
                and linked.suffix == ".md"
                and anchor not in anchors(linked.read_text(encoding="utf-8"))
            ):
                errors.append(f"{name}：無效章節 {target}")
        if name.startswith("docs/spec/") and re.search(
            r"(?m)^#+.*(?:尚未實作|待驗收|已完成審查)", text
        ):
            errors.append(f"{name}：現行規格含過時工作狀態")
    budget = sum(
        len((root / n).read_text(encoding="utf-8")) for n in ("AGENTS.md", "docs/PROGRESS.md")
    )
    if budget > ENTRY_BUDGET:
        errors.append(f"必讀入口 {budget} 字元超過 {ENTRY_BUDGET}")
    work = items(root)
    if len({i["id"] for i in work}) != len(work):
        errors.append("工作編號重複")
    for item in work:
        if item["state"] not in STATES or "領域：" not in item["title"]:
            errors.append(f"{item['id']}：缺少有效狀態或領域")
        elif any(
            a.strip() not in area_ids
            for a in item["title"].split("領域：", 1)[1].split("｜")[0].split(",")
        ):
            errors.append(f"{item['id']}：未知領域")
    pyproject = root / "pyproject.toml"
    init = root / "src/emlek/__init__.py"
    if pyproject.is_file() and init.is_file():
        expected = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
        if f'__version__ = "{expected}"' not in init.read_text(encoding="utf-8"):
            errors.append("程式版本不一致")
        lock = root / "uv.lock"
        if lock.is_file():
            packages = tomllib.loads(lock.read_text(encoding="utf-8")).get("package", [])
            if [p.get("version") for p in packages if p.get("name") == "emlek"] != [expected]:
                errors.append("uv.lock 的 emlek 版本不一致")
    return errors


def stale(root: Path, changed: list[str]) -> str:
    affected = [
        a
        for a in registry(root)
        if any(fnmatch.fnmatchcase(n, p) for n in changed for p in a["code"])
    ]
    return (
        "\n".join(f"可能需同步：{a['id']} → {', '.join(a['docs'])}" for a in affected)
        or "沒有領域程式變更。"
    )


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for path in files(root):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def write_receipt(root: Path, mode: str, *, verified: str | None = None) -> None:
    folder = inside(root, ".workflow")
    folder.mkdir(exist_ok=True)
    inside(root, ".workflow/verified.json").write_text(
        json.dumps({"fingerprint": verified or fingerprint(root), "mode": mode}), encoding="utf-8"
    )


def require_receipt(root: Path) -> None:
    path = inside(root, ".workflow/verified.json")
    if not path.exists() or json.loads(path.read_text(encoding="utf-8"))[
        "fingerprint"
    ] != fingerprint(root):
        raise ValueError("檔案已有變更或沒有驗證紀錄；請重新 verify")


def close(root: Path, ids: list[str]) -> None:
    eligible = {i["id"] for i in items(root) if i["state"] == "待驗收"}
    if not ids or not set(ids) <= eligible:
        raise ValueError("只能結案已由使用者確認通過的待驗收項目")
    path = inside(root, "docs/PROGRESS.md")
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    remove = False
    result = []
    for line in lines:
        match = re.match(r"^- \*\*(W\d+)\*\*", line)
        if match:
            remove = match[1] in ids
        elif line.startswith("## "):
            remove = False
        if not remove:
            result.append(line)
    path.write_text("".join(result), encoding="utf-8")


def bump(root: Path, kind: str) -> str:
    paths = tuple(
        inside(root, name) for name in ("pyproject.toml", "src/emlek/__init__.py", "uv.lock")
    )
    texts = [p.read_text(encoding="utf-8") for p in paths]
    old = tomllib.loads(texts[0])["project"]["version"]
    if f'__version__ = "{old}"' not in texts[1]:
        raise ValueError("程式版本不一致")
    parts = [int(n) for n in old.split(".")]
    index = {"major": 0, "minor": 1, "patch": 2}[kind]
    parts[index] += 1
    parts[index + 1 :] = [0] * (2 - index)
    new = ".".join(map(str, parts))
    project = re.search(r"(?ms)^\[project\].*?(?=^\[|\Z)", texts[0])
    if project is None:
        raise ValueError("找不到 project 區塊")
    blocks = re.findall(r"(?ms)^\[\[package\]\].*?(?=^\[\[package\]\]|\Z)", texts[2])
    owned = [b for b in blocks if tomllib.loads(b)["package"][0].get("name") == "emlek"]
    if len(owned) != 1 or tomllib.loads(owned[0])["package"][0].get("version") != old:
        raise ValueError("uv.lock 的 emlek 版本不一致")

    def replace(text: str, key: str) -> str:
        pattern = rf"(?m)^({key}\s*=\s*)([\"\']){re.escape(old)}\2"
        result, count = re.subn(pattern, lambda m: f"{m[1]}{m[2]}{new}{m[2]}", text)
        if count != 1:
            raise ValueError(f"版本指派不一致：{key}")
        return result

    updated = (
        texts[0].replace(project[0], replace(project[0], "version"), 1),
        replace(texts[1], "__version__"),
        texts[2].replace(owned[0], replace(owned[0], "version"), 1),
    )
    written = []
    try:
        for index, path in enumerate(paths):
            path.write_text(updated[index], encoding="utf-8")
            written.append(index)
    except OSError:
        for index in written:
            paths[index].write_text(texts[index], encoding="utf-8")
        raise
    return new


def push(root: Path) -> None:
    if any(i["state"] in ("進行中", "待驗收") for i in items(root)):
        raise ValueError("仍有進行中或未驗收工作；不得一併推送")
    if git(root, "branch", "--show-current") != "main":
        raise ValueError("只允許目前 main 推送 origin/main")
    if git(root, "diff", "--name-only", "HEAD"):
        raise ValueError("尚有未提交變更")
    untracked = set(git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    if untracked & {p.relative_to(root).as_posix() for p in files(root)}:
        raise ValueError("尚有未提交的專案新檔")
    require_receipt(root)
    git(root, "push", "origin", "main")


def verify(root: Path, mode: str) -> None:
    before = fingerprint(root)
    errors = problems(root)
    if errors:
        raise ValueError("\n".join(errors))
    changed = changed_files(root)
    if mode == "auto":
        mode = verification_mode(changed)
    if mode == "docs" and verification_mode(changed) != "docs":
        raise ValueError("產品、依賴或其他測試／腳本有變更，不可只做 docs 驗證")
    py = root / ".venv/Scripts/python.exe"
    python = str(py) if py.exists() else sys.executable
    commands = [[python, "scripts/check.py", "--fast"]]
    if mode == "docs":
        commands.append([python, "-m", "pytest", "tests/unit/test_workflow.py", "-q"])
    else:
        commands = [[python, "scripts/check.py", *(["--full"] if mode == "full" else [])]]
        if mode == "full":
            commands.append([python, "scripts/accept.py"])
    for command in commands:
        subprocess.run(command, cwd=root, check=True, timeout=1200)
    if fingerprint(root) != before:
        raise ValueError("驗證期間檔案有變更，不簽發驗證紀錄")
    write_receipt(root, mode, verified=before)
    print(f"verify {mode} passed；已記錄檔案雜湊，後續變更會使紀錄失效。")


def finish(root: Path, selected: list[str], message: str, mode: str) -> None:
    if not selected or not re.match(r"^(docs|feat|fix|test|refactor|chore): .+", message):
        raise ValueError("必須指定本批檔案及 type: summary 英文提交訊息")
    allowed = {p.relative_to(root).as_posix() for p in files(root)}
    for name in selected:
        path = inside(root, name)
        if path.is_dir() or (
            not path.is_file() and name not in git(root, "ls-files", "--", name).splitlines()
        ):
            raise ValueError(f"只允許本批明確檔案或已刪除的追蹤檔：{name}")
        if path.exists() and name not in allowed:
            raise ValueError(f"不在專案程式／文件提交範圍：{name}")
    staged = set(git(root, "diff", "--cached", "--name-only").splitlines())
    if staged - set(selected):
        raise ValueError("暫存區含其他檔案，先保留並分開處理")
    if mode == "quick" and product_change(changed_files(root)):
        raise ValueError("產品變更結案必須 full，quick 僅用於開發中")
    verify(root, mode)
    if set(git(root, "diff", "--cached", "--name-only").splitlines()) - set(selected):
        raise ValueError("驗證期間暫存區加入其他檔案，停止提交")
    git(root, "--literal-pathspecs", "add", "--", *selected)
    if set(git(root, "diff", "--cached", "--name-only").splitlines()) - set(selected):
        raise ValueError("暫存區含其他檔案，停止提交")
    require_receipt(root)
    git(root, "commit", "-m", message, "-m", "Co-authored-by: Codex <noreply@openai.com>")
    require_receipt(root)  # hooks must not silently change the verified files
    print("已本機提交；待使用者驗收後 close、verify、push。")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    commands.add_parser("status")
    contextual = commands.add_parser("context")
    contextual.add_argument("area", nargs="?")
    contextual.add_argument("--read", action="store_true")
    stale_parser = commands.add_parser("stale")
    stale_parser.add_argument("--base", default="HEAD")
    verification = commands.add_parser("verify")
    verification.add_argument("--mode", choices=("auto", "docs", "quick", "full"), default="auto")
    final = commands.add_parser("finish")
    final.add_argument("--files", nargs="+", required=True)
    final.add_argument("--message", required=True)
    final.add_argument("--mode", choices=("auto", "docs", "quick", "full"), default="auto")
    closing = commands.add_parser("close")
    closing.add_argument("ids", nargs="+")
    version = commands.add_parser("version")
    version.add_argument("kind", choices=("patch", "minor", "major"))
    commands.add_parser("push")
    args = parser.parse_args()
    try:
        if args.command == "check":
            errors = problems(ROOT)
            if errors:
                raise ValueError("\n".join(errors))
            print("workflow check passed")
        elif args.command == "status":
            for item in items(ROOT):
                print(f"{item['state']}：{item['id']} {item['title']}")
        elif args.command == "context":
            print(
                context(ROOT, args.area, read=args.read)
                if args.area
                else "\n".join(a["id"] for a in registry(ROOT))
            )
        elif args.command == "stale":
            changed = (
                changed_files(ROOT)
                if args.base == "HEAD"
                else git(ROOT, "diff", "--name-only", args.base).splitlines()
            )
            print(stale(ROOT, changed))
        elif args.command == "verify":
            verify(ROOT, args.mode)
        elif args.command == "finish":
            finish(ROOT, args.files, args.message, args.mode)
        elif args.command == "close":
            close(ROOT, args.ids)
            print("已移出使用者驗收通過的工作；其他未結案項目保留。")
        elif args.command == "version":
            print(bump(ROOT, args.kind))
        elif args.command == "push":
            push(ROOT)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
