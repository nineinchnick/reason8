#!/usr/bin/env python3
"""Download what a headless run needs into one data dir: engine, game, map.

    python tools/headless/setup.py --data-dir data/bar --engine 2026.09.03 \\
        --game "Beyond All Reason test-32018-ad135b9" --map "Supreme Isthmus v2.1"
    python tools/headless/setup.py --data-dir data/bar --replay REPLAY.sdfz ...

--replay reads the replay's header and fetches the exact engine, game version
and map it was played on. Everything fetched before is skipped (the list is
kept in <data-dir>/headless_setup.json), so the command is safe to repeat.
`--game byar:test` fetches the current game.

Layout written (the engine's own):
    <data-dir>/engine/recoil_<version>/   engine release from GitHub (needs `7z`)
    <data-dir>/pool, packages, rapid/     game versions (rapid, content-addressed)
    <data-dir>/maps/                      map archives

Games and maps are fetched by the engine's pr-downloader from BAR's CDN.
Prints one JSON object with what was fetched and how many bytes it added.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo  # noqa: E402

ENGINE_URL = (
    "https://github.com/beyond-all-reason/RecoilEngine/releases/download/"
    "{tag}/recoil_{tag}_amd64-linux.7z"
)
# pr-downloader defaults to the old Spring servers; these point it at BAR's.
PR_DOWNLOADER_ENV = {
    "PRD_HTTP_SEARCH_URL": "https://files-cdn.beyondallreason.dev/find",
    "PRD_RAPID_USE_STREAMER": "false",
    "PRD_RAPID_REPO_MASTER": "https://repos-cdn.beyondallreason.dev/repos.gz",
    "PRD_MAX_HTTP_REQS_PER_SEC": "20",
}
USER_AGENT = "reason8-headless-setup"
INDEX_NAME = "headless_setup.json"


def tree_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def engine_dir(data_dir: Path, tag: str) -> Path:
    return data_dir / "engine" / f"recoil_{tag}"


def install_engine(data_dir: Path, version: str) -> dict:
    tag = version.split()[0]
    install_dir = engine_dir(data_dir, tag)
    if (install_dir / "spring-headless").is_file():
        return {"engine": tag, "skipped": True}
    if shutil.which("7z") is None:
        raise SystemExit("7z is needed to unpack the engine (apt install p7zip-full)")
    archive = data_dir / "dl" / f"recoil_{tag}_amd64-linux.7z"
    archive.parent.mkdir(parents=True, exist_ok=True)
    start_time = time.monotonic()
    if not archive.is_file():
        request = urllib.request.Request(
            ENGINE_URL.format(tag=tag), headers={"User-Agent": USER_AGENT}
        )
        partial_archive = archive.with_suffix(".part")
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            partial_archive.open("wb") as file,
        ):
            shutil.copyfileobj(response, file)
        partial_archive.rename(archive)
    install_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["7z", "x", "-y", f"-o{install_dir}", str(archive)], check=True, capture_output=True
    )
    return {
        "engine": tag,
        "download_bytes": archive.stat().st_size,
        "installed_bytes": tree_bytes(install_dir),
        "seconds": round(time.monotonic() - start_time, 1),
    }


def pr_downloader(data_dir: Path) -> Path:
    found = sorted((data_dir / "engine").glob("*/pr-downloader"))
    if not found:
        raise SystemExit("install an engine first (--engine): it ships pr-downloader")
    return found[-1]


def load_index(data_dir: Path) -> dict:
    """Names already fetched into this data dir, so nothing is downloaded twice.

    pr-downloader skips game files it already has, but downloads a map again
    even when the archive is there, so we keep our own list.
    """
    path = data_dir / INDEX_NAME
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"game": [], "map": []}


def fetch(data_dir: Path, kind: str, name: str, index: dict) -> dict:
    """Run pr-downloader for one game or map and report the bytes it added."""
    is_tag = ":" in name  # a rapid tag like byar:test moves, so always ask
    if name in index[kind] and not is_tag:
        return {kind: name, "ok": True, "skipped": True}
    watched = [data_dir / "pool", data_dir / "packages"] if kind == "game" else [data_dir / "maps"]
    before = sum(tree_bytes(directory) for directory in watched)
    start_time = time.monotonic()
    process = subprocess.run(
        [
            str(pr_downloader(data_dir)),
            "--filesystem-writepath",
            str(data_dir),
            f"--download-{kind}",
            name,
        ],
        env={**os.environ, **PR_DOWNLOADER_ENV},
        capture_output=True,
        text=True,
    )
    result = {
        kind: name,
        "ok": process.returncode == 0,
        "added_bytes": sum(tree_bytes(directory) for directory in watched) - before,
        "seconds": round(time.monotonic() - start_time, 1),
    }
    if process.returncode != 0:
        result["error"] = (process.stdout + process.stderr).strip().splitlines()[-3:]
    elif not is_tag:
        index[kind].append(name)
        (data_dir / INDEX_NAME).write_text(json.dumps(index, indent=1), encoding="utf-8")
    return result


def main(argv: list[str]) -> int:
    argument_parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    argument_parser.add_argument("--data-dir", required=True)
    argument_parser.add_argument(
        "--engine", action="append", default=[], help="engine version, e.g. 2026.09.03"
    )
    argument_parser.add_argument(
        "--game", action="append", default=[], help="game name or rapid tag"
    )
    argument_parser.add_argument("--map", action="append", default=[], help="map name")
    argument_parser.add_argument(
        "--replay", action="append", default=[], help="fetch what this replay needs"
    )
    args = argument_parser.parse_args(argv)

    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    engines, games, maps = list(args.engine), list(args.game), list(args.map)
    for replay in args.replay:
        header = demo.read_header(replay)
        engines.append(header.engine_tag)
        games.append(header.game)
        maps.append(header.map)

    results = []
    ok = True
    index = load_index(data_dir)
    for version in dict.fromkeys(engines):
        results.append(install_engine(data_dir, version))
    for kind, names in (("game", games), ("map", maps)):
        for name in dict.fromkeys(names):
            result = fetch(data_dir, kind, name, index)
            ok = ok and result["ok"]
            results.append(result)
    print(json.dumps(results, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
