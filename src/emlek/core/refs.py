"""Record references: r12 (latest version) or r12.v3 (a specific version)."""

from __future__ import annotations

import re

from emlek.core.errors import EmlekError, ErrorCode

_REF = re.compile(r"^r?(\d+)(?:\.v(\d+))?$")


def parse_ref(ref: str) -> tuple[int, int | None]:
    match = _REF.match(ref.strip())
    if match is None:
        raise EmlekError(ErrorCode.INVALID_INPUT, "記錄編號格式應為 r12 或 r12.v3")
    record_id, version = match.groups()
    return int(record_id), int(version) if version else None
