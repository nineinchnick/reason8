"""Where the repository and the local data directory are, and how the data is laid out.

The data directory defaults to ``data/`` at the repository root and can be overridden with the
``REASON8_DATA_DIR`` environment variable (useful in git worktrees that share one cache).

Replays, parsed replays and state files are kept in daily partitions by the date the match
started, Hive style: ``replays/date=2026-11-01/<name>.sdfz``,
``parsed/date=2026-11-01/<name>.json.zst``, ``state/date=2026-11-01/<name>.jsonl.gz``. The date
is the first ten characters of the replay's file name (``YYYY-MM-DD_HH-MM-SS-mmm_<map>_<engine>``);
a file whose name does not start with a date goes to ``date=unknown``. The S3 bucket uses the
same relative paths. Bookkeeping files (``manifest.parquet``, ``_index.jsonl``) stay at the top
of their directory. This module is the one place that knows the layout.
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

#: The checkout this package runs from.
REPO_ROOT = Path(__file__).resolve().parents[1]

#: A partition directory is ``date=<YYYY-MM-DD>``, or ``date=unknown`` for undated names.
PARTITION_PREFIX = "date="
UNKNOWN_DATE = "unknown"
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


class LayoutError(Exception):
    """Data files lie outside the date partitions (an older, flat layout)."""


def data_dir() -> Path:
    """Root of the local, git-ignored data cache."""
    env = os.environ.get("REASON8_DATA_DIR")
    if env:
        return Path(env)
    return REPO_ROOT / "data"


def file_date(name: str) -> date | None:
    """The date a file name starts with (``YYYY-MM-DD``), or ``None``."""
    prefix = name[:10]
    if not _DATE_PATTERN.fullmatch(prefix):
        return None
    try:
        return date.fromisoformat(prefix)
    except ValueError:
        return None


def partition(name: str) -> str:
    """The partition directory of a file: ``date=YYYY-MM-DD`` or ``date=unknown``."""
    found = file_date(name)
    return PARTITION_PREFIX + (found.isoformat() if found else UNKNOWN_DATE)


def partitioned_name(name: str) -> str:
    """Path of a file relative to its area, e.g. ``date=2026-11-01/<name>``."""
    return f"{partition(name)}/{name}"


def partitioned_path(directory: Path, name: str) -> Path:
    """Where a file of that name is kept in ``directory`` (e.g. ``data/replays``)."""
    return directory / partition(name) / name


def partition_in_range(
    partition_name: str, since: date | None = None, until: date | None = None
) -> bool:
    """Whether a partition directory lies in ``since`` (inclusive) .. ``until`` (exclusive).

    Without bounds every partition does; with any bound ``date=unknown`` doesn't.
    """
    if not partition_name.startswith(PARTITION_PREFIX):
        return False
    if since is None and until is None:
        return True
    found = file_date(partition_name.removeprefix(PARTITION_PREFIX))
    return (
        found is not None and (since is None or found >= since) and (until is None or found < until)
    )


def find_files(
    directory: Path, pattern: str, *, since: date | None = None, until: date | None = None
) -> list[Path]:
    """Files matching ``pattern`` in ``directory``, sorted by name.

    Without a date range, every matching file at any depth, so a flat directory works too.
    With one, only the files in the partitions of that range.
    """
    if since is None and until is None:
        found = directory.rglob(pattern)
    else:
        found = (
            path
            for partition_directory in directory.glob(PARTITION_PREFIX + "*")
            if partition_directory.is_dir()
            and partition_in_range(partition_directory.name, since, until)
            for path in partition_directory.glob(pattern)
        )
    return sorted((path for path in found if path.is_file()), key=lambda path: path.name)


def unpartitioned_files(directory: Path, pattern: str) -> list[Path]:
    """Data files lying directly in ``directory`` instead of in its partitions."""
    return sorted(path for path in directory.glob(pattern) if path.is_file())


def require_partitioned(directory: Path, pattern: str) -> None:
    """Raise `LayoutError` when ``directory`` still holds data files outside the partitions."""
    flat = unpartitioned_files(directory, pattern)
    if flat:
        raise LayoutError(
            f"{len(flat)} files matching {pattern} in {directory} are not in date partitions; "
            "move them into their partitions"
        )
