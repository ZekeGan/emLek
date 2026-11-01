"""Permission table and configuration helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from emlek import config
from emlek.core import service
from emlek.core.db import Database
from emlek.core.errors import EmlekError, ErrorCode
from emlek.core.permissions import Caller, Channel, require


def test_readonly_channel_cannot_save_but_can_read(db: Database, caller: Caller) -> None:
    service.save(db, caller, body="読めるが書けない")
    readonly = Caller(Channel.MCP_READONLY)
    with pytest.raises(EmlekError) as info:
        service.save(db, readonly, body="書けない")
    assert info.value.code is ErrorCode.NOT_PERMITTED
    assert service.get(db, readonly, ref="r1")["body"] == "読めるが書けない"


def test_mcp_cannot_run_cli_only_operations() -> None:
    for operation in ("init", "doctor"):
        with pytest.raises(EmlekError) as info:
            require(Caller(Channel.MCP), operation)
        assert info.value.code is ErrorCode.NOT_PERMITTED


def test_unknown_operations_fail_closed() -> None:
    with pytest.raises(EmlekError):
        require(Caller(Channel.CLI), "purge_everything")


def test_data_dir_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path / "from_env"))
    assert config.resolve_data_dir(None) == (tmp_path / "from_env").resolve()
    assert config.resolve_data_dir(str(tmp_path / "flag")) == (tmp_path / "flag").resolve()
    monkeypatch.delenv(config.ENV_DATA_DIR)
    assert config.resolve_data_dir(None).name == "emlek"


def test_backup_dir_prefers_another_drive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "fixed_drives", lambda: ["C:\\", "D:\\"])
    assert config.default_backup_dir(Path("C:/Users/x/emlek")) == Path("D:/emlek-backups")
    monkeypatch.setattr(config, "fixed_drives", lambda: ["C:\\"])
    assert config.default_backup_dir(Path("C:/Users/x/emlek")).name == "emlek-backups"
    assert config.default_backup_dir(Path("C:/Users/x/emlek")).parent.name == "Documents"


def test_config_roundtrip_including_awkward_paths(tmp_path: Path) -> None:
    for name in ("plain", "it's quoted", "日本語"):
        folder = tmp_path / name
        folder.mkdir()
        backup = tmp_path / "backups" / name
        config.write_default_config(folder, backup)
        loaded = config.load_config(folder)
        assert loaded.backup_dir == backup
        assert loaded.timezone == "local"


def test_broken_config_is_reported_not_crashed(tmp_path: Path) -> None:
    (tmp_path / config.CONFIG_NAME).write_text("this is = = not toml", encoding="utf-8")
    with pytest.raises(EmlekError) as info:
        config.load_config(tmp_path)
    assert info.value.code is ErrorCode.INVALID_INPUT


def test_init_is_idempotent_and_keeps_data(tmp_path: Path, caller: Caller) -> None:
    from emlek.core.vault import init_vault

    folder = tmp_path / "v"
    first = init_vault(caller, folder)
    db = Database.open(config.load_config(folder).db_path)
    service.save(db, caller, body="残る")
    db.close()
    second = init_vault(caller, folder)
    assert first["created"] is True
    assert second["created"] is False
    db = Database.open(config.load_config(folder).db_path)
    try:
        assert service.get(db, caller, ref="r1")["body"] == "残る"
    finally:
        db.close()
