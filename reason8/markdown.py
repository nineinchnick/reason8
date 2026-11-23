"""Markdown for the tables that the measurement commands print into docs/."""

from __future__ import annotations

from collections.abc import Iterable, Sequence


def table(header: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    """The lines of a Markdown table (`mdformat` aligns the columns in the docs)."""
    lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines
