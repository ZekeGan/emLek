"""Turning results and errors into text or JSON for the terminal."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any

from emlek.core.errors import EmlekError


@dataclass(frozen=True)
class Output:
    result: dict[str, Any]
    text: str


def print_output(output: Output, *, as_json: bool) -> None:
    if as_json:
        sys.stdout.write(json.dumps({"ok": True, "result": output.result}, ensure_ascii=False))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(output.text)
        if not output.text.endswith("\n"):
            sys.stdout.write("\n")


def print_error(error: EmlekError, *, as_json: bool) -> None:
    if as_json:
        sys.stdout.write(json.dumps({"ok": False, "error": error.to_dict()}, ensure_ascii=False))
        sys.stdout.write("\n")
    else:
        sys.stderr.write(f"錯誤（{error.code.value}）：{error.message}\n")
        for key in ("confirm_token", "notice_token"):
            if key in error.data:
                sys.stderr.write(
                    f"{key}：{error.data[key]}（{error.data.get('expires_in', 600)} 秒內有效）\n"
                )
