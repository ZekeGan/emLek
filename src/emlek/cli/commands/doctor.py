"""emlek doctor"""

from __future__ import annotations

import argparse

from emlek.cli.commands.common import cli_caller, data_dir_of
from emlek.cli.output import Output
from emlek.core.doctor import run_checks

_MARK = {"ok": "[正常]", "warn": "[注意]", "fail": "[失敗]", "info": "[資訊]"}


def run(args: argparse.Namespace) -> Output:
    result = run_checks(cli_caller(), data_dir_of(args))
    lines = [f"{_MARK[c['status']]} {c['name']}：{c['detail']}" for c in result["checks"]]
    return Output(result, "\n".join(lines))
