"""Tests for the ``reason8`` command line: every command is there and parses its flags."""

from datetime import datetime

import pytest

from reason8 import cli


def command_lines() -> list[list[str]]:
    lines = []
    for name, *rest in cli.COMMANDS:
        if isinstance(rest[0], str):
            lines += [[name, command[0]] for command in rest[1]]
        else:
            lines.append([name])
    return lines


@pytest.mark.parametrize("command", command_lines(), ids=" ".join)
def test_every_command_has_help(command, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.make_parser().parse_args([*command, "--help"])
    assert exit_info.value.code == 0
    assert "usage: reason8 " + " ".join(command) in capsys.readouterr().out


def test_download_flags():
    args = cli.make_parser().parse_args(
        ["download", "--limit", "3", "--since", "2026-05-23", "--until", "2026-11-22", "--dry-run"]
    )
    assert args.limit == 3 and args.dry_run
    assert (args.since, args.until) == (datetime(2026, 5, 23), datetime(2026, 11, 22))
