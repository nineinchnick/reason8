"""The games of a cloud batch: queue messages, and where their files are in the bucket.

One message is one game: the replay's path in the bucket's ``replays`` area
(``date=YYYY-MM-DD/<name>.sdfz``) and the batch's settings, as JSON::

    {
        "replay": "date=2026-11-01/<name>.sdfz",
        "out_area": "state",
        "max_frame": 36000,
        "snapshot_seconds": 5.0,
        "timeout": 3600.0,
        "settings": []
    }

A game's results are its state file and Parquet tables in ``out_area``, with the layout
`reason8 headless batch` writes locally (``state/date=.../<name>.jsonl.gz`` and
``<name>.<table>.parquet``), so `reason8 sync pull <out_area>` brings them home. The
``game`` table is uploaded last, so a game is done when its ``game`` table is there.
Everything else of the cloud runs is under ``cloud/``: a failed try's record
(``cloud/failures/<out_area>/date=.../<name>.json``), the workers' logs
(``cloud/logs/<instance>/``) and a record of every batch (``cloud/batches/<time>.json``).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

from reason8.data.download import REPLAYS_DIRECTORY
from reason8.data.sync import is_state_area_name
from reason8.headless import tables
from reason8.headless.state import state_path
from reason8.paths import partition, partitioned_name

#: Everything of the cloud runs that is not a result.
CLOUD_AREA = "cloud"
FAILURES_DIRECTORY = f"{CLOUD_AREA}/failures"
LOGS_DIRECTORY = f"{CLOUD_AREA}/logs"
BATCHES_DIRECTORY = f"{CLOUD_AREA}/batches"
DEFAULT_OUT_AREA = "state"


class MessageError(ValueError):
    """A queue message that is not a game of a batch."""


@dataclass(frozen=True)
class BatchSettings:
    """What is the same for every game of a batch."""

    #: The area the results go to: ``state`` or ``state-<name>``.
    out_area: str = DEFAULT_OUT_AREA
    #: Stop at this frame (0: play the whole game).
    max_frame: int = 0
    snapshot_seconds: float = 5.0
    #: Kill the engine after this many seconds.
    timeout: float = 3600.0
    #: Engine settings, ``KEY=VALUE``.
    settings: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if not is_state_area_name(self.out_area):
            raise MessageError(f"not a state area: {self.out_area!r}")


@dataclass(frozen=True)
class GameMessage:
    #: The replay's path in the ``replays`` area: ``date=YYYY-MM-DD/<name>.sdfz``.
    replay: str
    batch: BatchSettings = field(default_factory=BatchSettings)

    def __post_init__(self) -> None:
        name = PurePosixPath(self.replay).name
        if not name.endswith(".sdfz") or self.replay != partitioned_name(name):
            raise MessageError(f"not a replay in its date partition: {self.replay!r}")

    def to_json(self) -> str:
        batch = {**asdict(self.batch), "settings": list(self.batch.settings)}
        return json.dumps({"replay": self.replay, **batch}, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> GameMessage:
        try:
            fields = json.loads(text)
            batch = BatchSettings(
                out_area=fields["out_area"],
                max_frame=int(fields["max_frame"]),
                snapshot_seconds=float(fields["snapshot_seconds"]),
                timeout=float(fields["timeout"]),
                settings=tuple(str(setting) for setting in fields["settings"]),
            )
            return cls(replay=fields["replay"], batch=batch)
        except (ValueError, KeyError, TypeError) as error:
            raise MessageError(f"not a game message: {text[:200]!r} ({error})") from error

    @property
    def replay_name(self) -> str:
        return PurePosixPath(self.replay).name

    @property
    def replay_path(self) -> str:
        """The replay's path relative to the bucket's location."""
        return f"{REPLAYS_DIRECTORY}/{self.replay}"

    @property
    def result_path(self) -> str:
        """The path that tells the game is done: its ``game`` table in the out area."""
        return result_path(self.batch.out_area, self.replay_name)

    @property
    def failure_path(self) -> str:
        stem = PurePosixPath(self.replay_name).stem
        return f"{FAILURES_DIRECTORY}/{self.batch.out_area}/{partition(stem)}/{stem}.json"


def state_relative_path(replay_name: str) -> str:
    """A replay's state file relative to its area: ``date=.../<name>.jsonl.gz``."""
    return state_path(Path("."), Path(replay_name)).as_posix()


def result_path(out_area: str, replay_name: str) -> str:
    """The ``game`` table of a replay, relative to the bucket's location."""
    table = tables.table_path(state_relative_path(replay_name), tables.LAST_TABLE)
    return f"{out_area}/{table.as_posix()}"


def result_files(state_file: Path) -> list[Path]:
    """The files of a played game in the order they are uploaded: the state file, its tables,
    and the ``game`` table last, so that a game is done only when all of them are there."""
    table_files = [
        tables.table_path(state_file, table)
        for table in sorted(tables.TABLES, key=lambda table: table == tables.LAST_TABLE)
    ]
    return [state_file, *(path for path in table_files if path.is_file())]


@dataclass
class BatchPlan:
    messages: list[GameMessage]
    #: Games of the list whose ``game`` table is already in the out area.
    done: int = 0
    #: Games whose replay is not in the bucket's ``replays`` area.
    missing_replay: int = 0
    #: Games listed more than once.
    repeated: int = 0


def plan_batch(
    replays: Iterable[Path],
    batch: BatchSettings,
    results: Iterable[str],
    replays_in_bucket: Iterable[str] | None = None,
) -> BatchPlan:
    """The messages of a batch: one per game of `replays` (paths of a list file, of which only
    the names count), with the settings of `batch`, without the games whose result is
    in `results` (paths relative to the out area) or whose replay is not in
    `replays_in_bucket` (paths relative to the ``replays`` area; ``None``: don't check)."""
    done = set(results)
    available = set(replays_in_bucket) if replays_in_bucket is not None else None
    plan = BatchPlan(messages=[])
    seen = set()
    for replay in replays:
        relative_path = partitioned_name(replay.name)
        if relative_path in seen:
            plan.repeated += 1
            continue
        seen.add(relative_path)
        message = GameMessage(relative_path, batch)
        if message.result_path.removeprefix(batch.out_area + "/") in done:
            plan.done += 1
        elif available is not None and relative_path not in available:
            plan.missing_replay += 1
        else:
            plan.messages.append(message)
    return plan
