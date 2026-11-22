"""The ``reason8`` command line."""

from __future__ import annotations

import argparse
import sys

from reason8 import download


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reason8")
    commands = parser.add_subparsers(dest="command", required=True)
    download_parser = commands.add_parser(
        "download",
        help="download replays of the selected matches",
        description=download.__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    download.add_arguments(download_parser)
    download_parser.set_defaults(run=download.run)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
