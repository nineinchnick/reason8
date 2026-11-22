#!/usr/bin/env python3
"""Play many replays in spring-headless, several engines at once, and keep their state.

    python tools/headless/batch.py --data-dir data/bar --out-dir data/state \\
        --jobs 4 --max-frame 21600 REPLAY.sdfz ...
    python tools/headless/batch.py --data-dir data/bar --out-dir data/state --list FILE

For every replay it fetches what the replay needs (setup.py), plays it with the state
export widget (run.py) and writes the state to <out-dir>/<replay name>.jsonl.gz. A replay
whose state file is already there is skipped, so the command can be repeated after a
failure. Content is fetched one replay at a time, because the downloads share one pool;
the engines run --jobs at once. An engine needs 5 to 6 GB of RAM (docs/state-extraction.md).

Prints one JSON object per replay as it finishes. A run that fails, times out or desyncs
writes no state file, and the exit code is then non-zero.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sys
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo  # noqa: E402
import run  # noqa: E402
import setup  # noqa: E402

STATE_SUFFIX = ".jsonl.gz"


def state_path(out_dir: Path, replay: Path) -> Path:
    """Where the state of a replay is kept: the replay's name, as JSON lines, gzipped."""
    return out_dir / (replay.stem + STATE_SUFFIX)


def fetch_content(data_dir: Path, replay: Path) -> list[str]:
    """Fetch the engine, game version and map of a replay; the names that failed."""
    header = demo.read_header(replay)
    setup.install_engine(data_dir, header.engine_tag)
    index = setup.load_index(data_dir)
    failed = []
    for kind, name in (("game", header.game), ("map", header.map)):
        if not setup.fetch(data_dir, kind, name, index)["ok"]:
            failed.append(name)
    return failed


def play(replay: Path, target: Path, args: argparse.Namespace) -> dict:
    """Play one replay and write its state to `target`; the result of run.py."""
    with tempfile.TemporaryDirectory(prefix="state-", dir=target.parent) as scratch:
        plain = Path(scratch) / "state.jsonl"
        arguments = [
            str(replay),
            "--data-dir",
            str(args.data_dir),
            "--threads",
            "1",
            "--snapshots",
            "--snapshot-seconds",
            str(args.snapshot_seconds),
            "--max-frame",
            str(args.max_frame),
            "--timeout",
            str(args.timeout),
            "--out",
            str(plain),
        ]
        for setting in args.set:
            arguments += ["--set", setting]
        result = run.run(run.parse_args(arguments))
        result["ok"] = (
            result["exit_code"] == 0
            and not result["timed_out"]
            and not result["desyncs"]
            and plain.is_file()
        )
        if result["ok"]:
            partial = target.with_name(target.name + ".part")
            # no file name or time in the gzip header: the same state gives the same bytes
            with (
                plain.open("rb") as source,
                partial.open("wb") as raw,
                gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as packed,
            ):
                shutil.copyfileobj(source, packed)
            partial.rename(target)
        result["state_file"] = str(target) if result["ok"] else None
    return result


def main(argv: list[str]) -> int:
    argument_parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    argument_parser.add_argument("replays", nargs="*", type=Path)
    argument_parser.add_argument("--list", type=Path, help="file with one replay path per line")
    argument_parser.add_argument("--data-dir", required=True, type=Path)
    argument_parser.add_argument("--out-dir", required=True, type=Path)
    argument_parser.add_argument("--jobs", type=int, default=4, help="engines at once")
    argument_parser.add_argument(
        "--max-frame", type=int, default=0, help="stop at this frame (0: play the whole game)"
    )
    argument_parser.add_argument("--snapshot-seconds", type=float, default=5)
    argument_parser.add_argument("--timeout", type=float, default=3600)
    argument_parser.add_argument(
        "--set", action="append", default=[], metavar="KEY=VALUE", help="engine setting"
    )
    argument_parser.add_argument(
        "--no-fetch", action="store_true", help="do not download missing engines, games or maps"
    )
    args = argument_parser.parse_args(argv)
    args.data_dir = args.data_dir.resolve()
    args.out_dir = args.out_dir.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    replays = list(args.replays)
    if args.list:
        replays += [Path(line) for line in args.list.read_text().splitlines() if line.strip()]

    ok = True

    def finished(future: Future) -> None:
        nonlocal ok
        result = future.result()
        ok = ok and result["ok"]
        print(json.dumps(result), flush=True)

    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for replay in replays:
            target = state_path(args.out_dir, replay)
            if target.exists():
                print(json.dumps({"target": replay.name, "ok": True, "skipped": True}), flush=True)
                continue
            failed = [] if args.no_fetch else fetch_content(args.data_dir, replay)
            if failed:
                ok = False
                print(json.dumps({"target": replay.name, "ok": False, "missing": failed}))
                continue
            pool.submit(play, replay.resolve(), target, args).add_done_callback(finished)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
