"""M0: CLI 골격이 임포트되고 --help / --version 이 동작하는지 확인."""

import pytest

from tenure import __version__
from tenure.cli import build_parser, main


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "run" in out and "resume" in out and "log" in out


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_run_parses_options():
    args = build_parser().parse_args(
        ["run", "할일 CLI", "--workdir", "/tmp/x", "--mock", "--implementer", "codex", "--reviewer", "claude"]
    )
    assert args.command == "run"
    assert args.task == "할일 CLI"
    assert args.mock is True
    assert args.implementer == "codex" and args.reviewer == "claude"


def test_no_command_is_error():
    with pytest.raises(SystemExit) as e:
        main([])
    assert e.value.code == 2
