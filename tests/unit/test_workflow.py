"""Repository workflow guards use synthetic files, never a real vault or remote."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from scripts import workflow as w


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs/spec.md").write_text("# 規格\n\n## 日期\n正確處理日期。\n", encoding="utf-8")
    (tmp_path / "src/example.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "tests/test_example.py").write_text("", encoding="utf-8")
    registry = {
        "areas": [
            {
                "id": "search",
                "docs": ["docs/spec.md#日期"],
                "code": ["src/*.py"],
                "tests": ["tests/test_example.py"],
            }
        ]
    }
    (tmp_path / "docs/areas.json").write_text(json.dumps(registry), encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("工作規則", encoding="utf-8")
    (tmp_path / "docs/PROGRESS.md").write_text(
        "# 工作\n\n## 待驗收\n\n- **W01** 日期查詢｜領域：search\n  驗收：日期正確。\n",
        encoding="utf-8",
    )
    return tmp_path


def test_git_failure_preserves_hook_reason(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise subprocess.CalledProcessError(
            1, ["git", "commit"], stderr="hook: marked item blocked"
        )

    monkeypatch.setattr(subprocess, "run", blocked)
    with pytest.raises(ValueError, match="marked item blocked"):
        w.git(repo, "commit")


def test_context_returns_only_the_requested_section(repo: Path) -> None:
    path = repo / "docs/spec.md"
    path.write_text(
        "# 規格\n## 其他\n不應讀取\n## 日期\n日期內容\n## 隱私\n不應讀取\n", encoding="utf-8"
    )
    result = w.context(repo, "search", read=True)
    assert "日期內容" in result and "不應讀取" not in result
    assert "src/*.py" in result and "tests/test_example.py" in result
    with pytest.raises(ValueError, match="未知領域"):
        w.context(repo, "missing", read=True)


def test_registry_rejects_missing_files_and_unowned_code(repo: Path) -> None:
    assert not w.problems(repo)
    (repo / "src/example.py").unlink()
    assert any("沒有匹配" in p for p in w.problems(repo))
    (repo / "src/new.txt").write_text("", encoding="utf-8")
    assert any("未登錄" in p for p in w.problems(repo))


def test_missing_heading_and_markdown_link_are_errors(repo: Path) -> None:
    (repo / "docs/spec.md").write_text("# 規格\n[不存在](missing.md)\n", encoding="utf-8")
    errors = w.problems(repo)
    assert any("日期" in p for p in errors)
    assert any("missing.md" in p for p in errors)


def test_links_ignore_fenced_examples_but_check_explicit_anchors(repo: Path) -> None:
    (repo / "docs/spec.md").write_text(
        '# 規格\n## 日期\n<a id="old"></a>\n[舊](#old)\n```md\n[示例](missing.md)\n```\n',
        encoding="utf-8",
    )
    assert not w.problems(repo)


def test_work_items_have_one_state_and_close_preserves_other_items(repo: Path) -> None:
    progress = repo / "docs/PROGRESS.md"
    progress.write_text(
        progress.read_text(encoding="utf-8")
        + "\n- **W02** 同意流程｜領域：search\n  不得提早關閉。\n",
        encoding="utf-8",
    )
    assert w.items(repo)[0]["state"] == "待驗收"
    w.close(repo, ["W01"])
    text = progress.read_text(encoding="utf-8")
    assert "W01" not in text and "W02" in text and "不得提早關閉" in text
    with pytest.raises(ValueError, match="待驗收"):
        w.close(repo, ["W02", "W99"])
    assert "W02" in progress.read_text(encoding="utf-8")  # all-or-nothing validation


def test_duplicate_items_and_entry_growth_are_errors(repo: Path) -> None:
    progress = repo / "docs/PROGRESS.md"
    progress.write_text(
        progress.read_text(encoding="utf-8") + "\n- **W01** 重複｜領域：search\n", encoding="utf-8"
    )
    assert any("重複" in p for p in w.problems(repo))
    (repo / "AGENTS.md").write_text("字" * 2601, encoding="utf-8")
    assert any("2600" in p for p in w.problems(repo))


def test_paths_cannot_escape_workspace(repo: Path) -> None:
    for path in ("../private.md", "D:/outside.md", "/etc/passwd"):
        with pytest.raises(ValueError, match="工作區"):
            w.inside(repo, path)


def test_push_never_runs_with_pending_work(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git = Mock()
    monkeypatch.setattr(w, "git", git)
    with pytest.raises(ValueError, match="未驗收"):
        w.push(repo)
    git.assert_not_called()


def test_push_requires_matching_receipt_and_main(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w.close(repo, ["W01"])
    calls: list[tuple[str, ...]] = []

    def git(root: Path, *args: str) -> str:
        calls.append(args)
        return "other" if args == ("branch", "--show-current") else ""

    monkeypatch.setattr(w, "git", git)
    with pytest.raises(ValueError):
        w.push(repo)
    assert not any(c[0] == "push" for c in calls)


def test_receipt_invalidates_after_content_changes(repo: Path) -> None:
    w.write_receipt(repo, "docs")
    w.require_receipt(repo)
    (repo / "src/example.py").write_text("value = 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="變更"):
        w.require_receipt(repo)


def test_stale_points_to_related_spec(repo: Path) -> None:
    result = w.stale(repo, ["src/example.py"])
    assert "docs/spec.md#日期" in result
    assert "可能" in result


def test_version_changes_both_sources_and_refuses_mismatch(repo: Path) -> None:
    (repo / "pyproject.toml").write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
    (repo / "src/emlek").mkdir()
    init = repo / "src/emlek/__init__.py"
    init.write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    (repo / "uv.lock").write_text(
        '[[package]]\nname = "emlek"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    assert w.bump(repo, "patch") == "0.1.1"
    assert '"0.1.1"' in init.read_text(encoding="utf-8")
    init.write_text('__version__ = "0.1.9"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="不一致"):
        w.bump(repo, "patch")
    assert '"0.1.1"' in (repo / "pyproject.toml").read_text(encoding="utf-8")


def test_version_preserves_comments_and_other_package_versions(repo: Path) -> None:
    (repo / "pyproject.toml").write_text(
        '# old "0.1.0"\n[project]\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (repo / "src/emlek").mkdir()
    init = repo / "src/emlek/__init__.py"
    init.write_text('# old "0.1.0"\n__version__ = "0.1.0"\n', encoding="utf-8")
    (repo / "uv.lock").write_text(
        '[[package]]\nname = "other"\nversion = "0.1.0"\n\n'
        '[[package]]\nname = "emlek"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    assert w.bump(repo, "minor") == "0.2.0"
    assert '# old "0.1.0"' in init.read_text(encoding="utf-8")
    assert 'name = "other"\nversion = "0.1.0"' in (repo / "uv.lock").read_text(encoding="utf-8")


def test_verify_does_not_certify_files_changed_during_checks(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(w, "git", lambda root, *args: "")

    def changed(*args: object, **kwargs: object) -> None:
        (repo / "src/example.py").write_text("changed during verification", encoding="utf-8")

    monkeypatch.setattr(subprocess, "run", changed)
    with pytest.raises(ValueError, match="驗證期間"):
        w.verify(repo, "docs")
    assert not (repo / ".workflow/verified.json").exists()


def test_new_source_file_selects_full_and_cannot_use_docs(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(w, "git", lambda root, *args: "src/new.py" if args[0] == "ls-files" else "")
    assert w.changed_files(repo) == ["src/new.py"]
    assert w.verification_mode(w.changed_files(repo)) == "full"
    with pytest.raises(ValueError, match="不可只做 docs"):
        w.verify(repo, "docs")
    assert w.verification_mode(["tests/unit/test_other.py"]) == "quick"
    assert w.verification_mode(["pyproject.toml"]) == "full"


def test_finish_rejects_directory_before_staging(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git = Mock()
    monkeypatch.setattr(w, "git", git)
    with pytest.raises(ValueError, match="明確檔案"):
        w.finish(repo, ["."], "docs: update", "docs")
    git.assert_not_called()


def test_receipt_cannot_follow_external_symlink(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    # A sibling is outside the intended repository, even though still pytest-owned.
    real_repo = repo / "nested"
    real_repo.mkdir()
    try:
        (real_repo / ".workflow").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    with pytest.raises(ValueError, match="工作區"):
        w.write_receipt(real_repo, "docs")
    assert not (outside / "verified.json").exists()


def test_finish_rechecks_staging_after_verification(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = {"value": ""}
    calls: list[tuple[str, ...]] = []

    def git(root: Path, *args: str) -> str:
        calls.append(args)
        return stage["value"] if args == ("diff", "--cached", "--name-only") else ""

    def verify(root: Path, mode: str) -> None:
        stage["value"] = "other.md"

    monkeypatch.setattr(w, "git", git)
    monkeypatch.setattr(w, "verify", verify)
    with pytest.raises(ValueError, match="其他檔案"):
        w.finish(repo, ["docs/spec.md"], "docs: update", "docs")
    assert not any(c[0] in ("add", "commit") for c in calls)


def test_push_uses_only_normal_origin_main_after_acceptance(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    w.close(repo, ["W01"])
    w.write_receipt(repo, "full")
    calls: list[tuple[str, ...]] = []

    def git(root: Path, *args: str) -> str:
        calls.append(args)
        return "main" if args == ("branch", "--show-current") else ""

    monkeypatch.setattr(w, "git", git)
    w.push(repo)
    assert calls[-1] == ("push", "origin", "main")


def test_push_refuses_untracked_project_file(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    w.close(repo, ["W01"])
    w.write_receipt(repo, "full")
    calls: list[tuple[str, ...]] = []

    def git(root: Path, *args: str) -> str:
        calls.append(args)
        if args == ("branch", "--show-current"):
            return "main"
        return "src/example.py" if args[0] == "ls-files" else ""

    monkeypatch.setattr(w, "git", git)
    with pytest.raises(ValueError, match="專案新檔"):
        w.push(repo)
    assert not any(c[0] == "push" for c in calls)


@pytest.mark.parametrize("operation", ["close", "bump"])
def test_writers_do_not_follow_external_links(repo: Path, operation: str) -> None:
    target = repo / "outside.txt"
    original = (repo / "docs/PROGRESS.md").read_text(encoding="utf-8")
    target.write_text(original, encoding="utf-8")
    nested = repo / "nested"
    (nested / "docs").mkdir(parents=True)
    link = nested / ("docs/PROGRESS.md" if operation == "close" else "pyproject.toml")
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Windows symlink privilege unavailable")
    with pytest.raises(ValueError, match="工作區"):
        if operation == "close":
            w.close(nested, ["W01"])
        else:
            w.bump(nested, "patch")
    assert target.read_text(encoding="utf-8") == original
