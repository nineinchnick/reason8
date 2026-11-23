"""Play many replays in spring-headless, several engines at once, and keep their state.

    uv run reason8 headless batch --data-dir data/bar --out-dir data/state \\
        --jobs 4 --max-frame 21600 REPLAY.sdfz ...
    uv run reason8 headless batch --data-dir data/bar --out-dir data/state --list FILE

For every replay it fetches what the replay needs (`reason8 headless setup`), plays it
with the state export widget (`reason8 headless run`) and writes the state to
<out-dir>/<replay name>.jsonl.gz. A replay whose state file is already there is skipped,
so the command can be repeated after a failure. Content is fetched one replay at a time,
because the downloads share one pool; the engines run --jobs at once. An engine needs 5
to 6 GB of RAM (docs/research/state-extraction.md).

Prints one JSON object per replay as it finishes. A run that fails, times out or desyncs
writes no state file, and the exit code is then non-zero.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from reason8.headless import run as headless_run
from reason8.headless import setup
from reason8.headless.state import state_path
from reason8.replays import sdfz


def fetch_content(data_dir: Path, replay: Path) -> list[str]:
    """Fetch the engine, game version and map of a replay; the names that failed."""
    header = sdfz.read_header(replay)
    setup.install_engine(data_dir, header.engine_tag)
    index = setup.load_index(data_dir)
    failed = []
    for kind, name in (("game", header.game), ("map", header.map)):
        if not setup.fetch(data_dir, kind, name, index)["ok"]:
            failed.append(name)
    return failed


def play(replay: Path, target: Path, args: argparse.Namespace) -> dict:
    """Play one replay and write its state to `target`; the result of `headless_run.play()`."""
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
        run_parser = argparse.ArgumentParser()
        headless_run.add_arguments(run_parser)
        result = headless_run.play(run_parser.parse_args(arguments))
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


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("replays", nargs="*", type=Path)
    parser.add_argument("--list", type=Path, help="file with one replay path per line")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--jobs", type=int, default=4, help="engines at once")
    parser.add_argument(
        "--max-frame", type=int, default=0, help="stop at this frame (0: play the whole game)"
    )
    parser.add_argument("--snapshot-seconds", type=float, default=5)
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument(
        "--set", action="append", default=[], metavar="KEY=VALUE", help="engine setting"
    )
    parser.add_argument(
        "--no-fetch", action="store_true", help="do not download missing engines, games or maps"
    )


def run(args: argparse.Namespace) -> int:
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
