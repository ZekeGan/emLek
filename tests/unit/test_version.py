"""The two places that carry the program version must agree."""

from __future__ import annotations

import tomllib
from pathlib import Path

import emlek


def test_package_and_project_versions_match() -> None:
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert emlek.__version__ == project["version"]
