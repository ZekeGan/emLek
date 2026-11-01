"""Helpers shared by command handlers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from emlek.config import load_config, resolve_data_dir
from emlek.core.db import Database
from emlek.core.permissions import Caller, Channel
from emlek.log import setup_logging


def cli_caller() -> Caller:
    interactive = all(s is not None and s.isatty() for s in (sys.stdin, sys.stdout, sys.stderr))
    return Caller(Channel.CLI, interactive=interactive)


def data_dir_of(args: argparse.Namespace) -> Path:
    return resolve_data_dir(args.data_dir)


def open_vault(args: argparse.Namespace) -> Database:
    data_dir = data_dir_of(args)
    config = load_config(data_dir)
    if data_dir.exists():
        setup_logging(data_dir)
    return Database.open(config.db_path)
