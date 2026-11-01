"""Error codes and the exception that carries them through the core."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    TOKEN_INVALID = "TOKEN_INVALID"
    NOT_PERMITTED = "NOT_PERMITTED"
    BUSY = "BUSY"
    INTERNAL = "INTERNAL"


EXIT_CODES: dict[ErrorCode, int] = {
    ErrorCode.INTERNAL: 1,
    ErrorCode.INVALID_INPUT: 2,
    ErrorCode.NOT_PERMITTED: 3,
    ErrorCode.NEEDS_CONFIRMATION: 3,
    ErrorCode.TOKEN_INVALID: 3,
    ErrorCode.NOT_FOUND: 4,
    ErrorCode.CONFLICT: 4,
    ErrorCode.BUSY: 5,
}


class EmlekError(Exception):
    """A failure the caller can act on. Never carries record content in its message."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.data = data or {}

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.code]

    def to_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.data:
            error["data"] = self.data
        return error
