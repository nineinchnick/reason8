"""Download replay files politely: one connection, about one request per second, cached.

Usage::

    uv run reason8 download --limit 100              # 100 replays of the default slice
    uv run reason8 download --limit 100 --dry-run    # list them without downloading

Replays come from BAR's public object storage, which is community-funded: never ask for a file
twice, and ask BAR's infrastructure developers before downloading thousands.

Each replay is saved as ``<data dir>/replays/<replay_file_name>``: written to a ``.part`` file
first and renamed when complete, so an interrupted run leaves no truncated replays. Every match
the downloader touches gets a row in ``<data dir>/replays/manifest.parquet`` with its status:

``ok``
    the file is on disk (downloaded now or found there);
``missing``
    the server answered 404 or 410 (expired or never uploaded); not asked for again unless
    ``--retry-missing``;
``error``
    anything else (5xx, timeout, broken connection); retried by later runs until it has failed
    ``MAX_ATTEMPTS`` times.

The order in which matches are downloaded is decided by ``download_order()``.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx
import polars as pl

from reason8 import match_dumps

PROJECT_URL = "https://github.com/nineinchnick/reason8"
USER_AGENT = f"reason8/{version('reason8')} (+{PROJECT_URL})"
MANIFEST_NAME = "manifest.parquet"
MAX_ATTEMPTS = 3
#: Seconds between the starts of two requests.
DEFAULT_INTERVAL = 1.0
#: Answers that mean the replay is not there and asking again won't help.
MISSING_STATUSES = frozenset({404, 410})
#: Answers that mean the server wants fewer requests: the run stops.
SLOW_DOWN_STATUSES = frozenset({429, 503})

OK = "ok"
MISSING = "missing"
ERROR = "error"

MANIFEST_SCHEMA = {
    "match_id": pl.Int64,
    "replay_file_name": pl.String,
    "map": pl.String,
    "start_time": pl.Datetime("us"),
    "engine": pl.String,
    "game_version": pl.String,
    "status": pl.String,
    "http_status": pl.Int32,
    "bytes": pl.Int64,
    "attempts": pl.Int32,
    "error": pl.String,
    "updated_at": pl.Datetime("us", "UTC"),
}
MATCH_COLUMNS = ("match_id", "replay_file_name", "map", "start_time", "engine", "game_version")
ORDERS = ("random", "newest")


def replays_dir() -> Path:
    """Directory holding the downloaded ``.sdfz`` files and the manifest."""
    return match_dumps.data_dir() / "replays"


def download_order(selection: pl.DataFrame, order: str = "random", seed: int = 0) -> pl.DataFrame:
    """Sort matches into the order they should be downloaded in.

    Maps take turns (one match from each map in name order, then the next from each map, and
    so on), so any prefix of the result has about the same number of games per map until the
    smaller maps run out. Within a map:

    ``random``
        a fixed pseudo-random order: SHA-256 of ``"<seed>:<match_id>"``. Any prefix is a
        uniform sample of that map's games, so a larger ``limit`` extends the sample instead of
        replacing it, and matches added by a newer dump don't reorder the others.
    ``newest``
        newest game first.
    """
    if order == "random":
        sort_key = pl.col("match_id").map_elements(
            lambda match_id: _stable_hash(f"{seed}:{match_id}"), return_dtype=pl.UInt64
        )
    elif order == "newest":
        sort_key = -pl.col("start_time").cast(pl.Int64)
    else:
        raise ValueError(f"order must be one of {ORDERS}, not {order!r}")
    return (
        selection.with_columns(_sort_key=sort_key)
        .with_columns(_turn=pl.col("_sort_key").rank("ordinal").over("map"))
        .sort("_turn", "map", "_sort_key")
        .drop("_sort_key", "_turn")
    )


def _stable_hash(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


class RateLimiter:
    """Keeps at least ``interval`` seconds between the starts of consecutive requests."""

    def __init__(
        self,
        interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.interval = interval
        self.clock = clock
        self.sleep = sleep
        self.last_start: float | None = None

    def wait(self) -> None:
        if self.last_start is not None:
            remaining = self.last_start + self.interval - self.clock()
            if remaining > 0:
                self.sleep(remaining)
        self.last_start = self.clock()


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """One HTTP client with a single connection and our User-Agent."""
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        timeout=httpx.Timeout(30.0, read=120.0),
        follow_redirects=True,
        transport=transport,
    )


def read_manifest(path: Path) -> dict[int, dict[str, Any]]:
    """Manifest rows by ``match_id`` (empty if there is no manifest yet)."""
    if not path.exists():
        return {}
    return {row["match_id"]: row for row in pl.read_parquet(path).iter_rows(named=True)}


def write_manifest(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Write the manifest atomically, sorted by match id."""
    frame = pl.DataFrame(list(rows), schema=MANIFEST_SCHEMA).sort("match_id")
    temporary_path = path.with_name(path.name + ".tmp")
    frame.write_parquet(temporary_path)
    os.replace(temporary_path, path)


@dataclass
class FetchResult:
    status: str
    http_status: int | None = None
    bytes: int | None = None
    error: str | None = None


class SlowDown(Exception):
    """The server asked for fewer requests (HTTP 429 or 503)."""


def fetch(client: httpx.Client, url: str, path: Path) -> FetchResult:
    """Download ``url`` into ``path`` via a ``.part`` file that is renamed when complete."""
    temporary_path = path.with_name(path.name + ".part")
    try:
        with client.stream("GET", url) as response:
            if response.status_code in MISSING_STATUSES:
                return FetchResult(MISSING, response.status_code)
            if response.status_code != 200:
                return FetchResult(
                    ERROR, response.status_code, error=f"HTTP {response.status_code}"
                )
            received = 0
            with temporary_path.open("wb") as file:
                for chunk in response.iter_bytes(1 << 20):
                    file.write(chunk)
                    received += len(chunk)
            expected = response.headers.get("Content-Length")
            if expected is not None and int(expected) != received:
                return FetchResult(ERROR, 200, error=f"incomplete: {received} of {expected} bytes")
        os.replace(temporary_path, path)
        return FetchResult(OK, 200, received)
    except httpx.HTTPError as error:
        return FetchResult(ERROR, error=f"{type(error).__name__}: {error}"[:500])
    finally:
        temporary_path.unlink(missing_ok=True)


@dataclass
class DownloadSummary:
    on_disk: int = 0
    requests: int = 0
    bytes: int = 0
    statuses: Counter[str] = field(default_factory=Counter)
    stopped: str | None = None


def download_replays(
    queue: pl.DataFrame,
    limit: int,
    *,
    dest: Path | None = None,
    client: httpx.Client,
    limiter: RateLimiter,
    retry_missing: bool = False,
    max_attempts: int = MAX_ATTEMPTS,
    log: Callable[[str], None] = print,
) -> DownloadSummary:
    """Walk ``queue`` in order until ``limit`` of its replays are on disk.

    Replays already on disk count towards the limit without a request. Matches recorded as
    ``missing``, and those that failed ``max_attempts`` times, are skipped and the next match
    in the queue takes their place. The manifest is updated as the run goes.
    """
    dest = dest or replays_dir()
    dest.mkdir(parents=True, exist_ok=True)
    manifest_path = dest / MANIFEST_NAME
    manifest = read_manifest(manifest_path)
    summary = DownloadSummary()
    unsaved_changes = 0

    def record(match: dict[str, Any], result: FetchResult, attempts: int) -> None:
        nonlocal unsaved_changes
        manifest[match["match_id"]] = {
            **{column: match[column] for column in MATCH_COLUMNS},
            "status": result.status,
            "http_status": result.http_status,
            "bytes": result.bytes,
            "attempts": attempts,
            "error": result.error,
            "updated_at": datetime.now(UTC),
        }
        unsaved_changes += 1
        if unsaved_changes >= 10:
            write_manifest(manifest_path, manifest.values())
            unsaved_changes = 0

    try:
        for match in queue.iter_rows(named=True):
            if summary.on_disk >= limit:
                break
            file_name = match["replay_file_name"]
            previous = manifest.get(match["match_id"], {})
            attempts = previous.get("attempts") or 0
            if Path(file_name).name != file_name or file_name.startswith("."):
                record(match, FetchResult(ERROR, error="unsafe file name"), attempts)
                continue
            path = dest / file_name
            if path.exists():
                summary.on_disk += 1
                if previous.get("status") != OK:
                    record(match, FetchResult(OK, bytes=path.stat().st_size), attempts)
                continue
            if previous.get("status") == MISSING and not retry_missing:
                continue
            if previous.get("status") == ERROR and attempts >= max_attempts:
                continue

            limiter.wait()
            result = fetch(client, match_dumps.replay_url(file_name), path)
            summary.requests += 1
            summary.statuses[result.status] += 1
            record(match, result, attempts + 1)
            if result.status == OK:
                summary.on_disk += 1
                summary.bytes += result.bytes or 0
            detail = result.error or (f"{result.bytes / 1e6:.2f} MB" if result.bytes else "")
            log(f"[{summary.on_disk}/{limit}] {result.status:7} {file_name} {detail}".rstrip())
            if result.http_status in SLOW_DOWN_STATUSES:
                summary.stopped = f"server answered HTTP {result.http_status}; stopping"
                break
    finally:
        write_manifest(manifest_path, manifest.values())
    return summary


def select_for_download(since: datetime | None, until: datetime | None) -> pl.DataFrame:
    """The default training slice (ADR 0006), using the cached match dumps."""
    match_dumps.download_dumps(["matches", "match_players"])
    return match_dumps.select_matches(
        match_dumps.scan_dump("matches"),
        match_dumps.scan_dump("match_players"),
        since=since,
        until=until,
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--limit",
        type=int,
        required=True,
        help="stop once this many replays of the queue are on disk",
    )
    parser.add_argument(
        "--order",
        choices=ORDERS,
        default="random",
        help="order within each map: fixed pseudo-random (default) or newest first",
    )
    parser.add_argument("--seed", type=int, default=0, help="seed of the random order")
    parser.add_argument(
        "--since", type=datetime.fromisoformat, help="earliest match start (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--until", type=datetime.fromisoformat, help="latest match start, exclusive (YYYY-MM-DD)"
    )
    parser.add_argument("--dest", type=Path, help="output directory (default: <data dir>/replays)")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help=f"seconds between requests (default {DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--retry-missing", action="store_true", help="ask again for replays that were 404/410"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the queue's first LIMIT matches and exit"
    )


def run(args: argparse.Namespace) -> int:
    queue = download_order(select_for_download(args.since, args.until), args.order, args.seed)
    print(f"{queue.height} matches in the selection", file=sys.stderr)
    if args.dry_run:
        with pl.Config(tbl_rows=args.limit, fmt_str_lengths=80, tbl_width_chars=200):
            print(queue.head(args.limit).select(*MATCH_COLUMNS))
        return 0
    started = time.monotonic()
    with make_client() as client:
        summary = download_replays(
            queue,
            args.limit,
            dest=args.dest,
            client=client,
            limiter=RateLimiter(args.interval),
            retry_missing=args.retry_missing,
            log=lambda line: print(line, file=sys.stderr),
        )
    elapsed = time.monotonic() - started
    statuses = ", ".join(f"{count} {status}" for status, count in sorted(summary.statuses.items()))
    print(
        f"{summary.on_disk} replays on disk; {summary.requests} requests ({statuses or 'none'}), "
        f"{summary.bytes / 1e6:.1f} MB in {elapsed:.0f} s",
        file=sys.stderr,
    )
    if summary.stopped:
        print(summary.stopped, file=sys.stderr)
        return 1
    return 0
