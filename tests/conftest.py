"""Shared fixtures. All data is synthetic and lives under pytest's temp folders."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from emlek.config import load_config
from emlek.core import service
from emlek.core.db import Database
from emlek.core.permissions import Caller, Channel
from emlek.core.vault import init_vault


@pytest.fixture
def caller() -> Caller:
    return Caller(Channel.CLI)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    path = tmp_path / "vault"
    init_vault(Caller(Channel.CLI), path)
    return path


@pytest.fixture
def db(data_dir: Path) -> Iterator[Database]:
    database = Database.open(load_config(data_dir).db_path)
    yield database
    database.close()


@pytest.fixture(scope="module")
def shared_db(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Database]:
    path = tmp_path_factory.mktemp("shared") / "vault"
    init_vault(Caller(Channel.CLI), path)
    database = Database.open(load_config(path).db_path)
    yield database
    database.close()


@pytest.fixture
def save_at(db: Database, caller: Caller) -> Callable[..., dict[str, Any]]:
    """Save with a controlled created_at, so date-based behaviour can be tested."""

    def _save(
        body: str, *, created_at: str = "2026-01-01T00:00:00.000Z", **kwargs: Any
    ) -> dict[str, Any]:
        with patch.object(service, "utc_now_iso", return_value=created_at):
            return service.save(db, caller, body=body, **kwargs)

    return _save
