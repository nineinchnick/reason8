"""Markdown for the tables that the measurement commands print into docs/."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from reason8.replays.sdfz import GAME_SPEED


def table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    """The lines of a Markdown table (`mdformat` aligns the columns in the docs)."""
    lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines


def clock(frame: float) -> str:
    """Game time of a frame as minutes and seconds, e.g. ``"4:05"``; ``"none"`` for infinity."""
    if math.isinf(frame):
        return "none"
    seconds = int(frame // GAME_SPEED)
    return f"{seconds // 60}:{seconds % 60:02d}"
