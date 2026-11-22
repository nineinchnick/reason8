"""The ``reason8`` command line."""

from __future__ import annotations

import argparse
import sys

from reason8 import download, sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reason8")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, module, summary in (
        ("download", download, "download replays of the selected matches"),
        ("sync", sync, "copy the data directory to or from the S3 bucket"),
    ):
        command_parser = commands.add_parser(
            name,
            help=summary,
            description=module.__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        module.add_arguments(command_parser)
        command_parser.set_defaults(run=module.run)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
