"""Checks that the sight and radar of a game's state add up.

From format 7 the state has a row each time an enemy unit enters or leaves an ally team's
sight (``los``) or radar (``radar``) (`reason8.headless.tables`). The widget finds the ally
team of each call-in by reading every ally team's state of the unit, and counts the
call-ins where that found no ally team or several (``visibility_unmatched`` and
``visibility_multiple`` of the ``game`` row). `check()` compares the rows with each other
and with the rest of the state, on the tables of one game:

``widget``
    the widget's own counts of call-ins it could not put down to one ally team
``pairs``
    per unit, ally team and sense, every enter is followed by a leave, or the unit died,
    was given to that ally team or was still seen at the end, and no leave comes without
    an enter before it
``radar_covers_sight``
    the engine puts a unit in sight on radar too: entries into sight while the unit was
    not on radar
``hits``, ``kills``
    independent of the call-ins: a unit that an enemy team hit for the first time, or
    destroyed (not reclaimed by its own side), against what the attacker's ally team had
    of it at that frame: in sight, on radar only, or neither. Units are hit out of sight
    (artillery fired at a radar blip, splash, shots at other targets), so "neither" is
    not 0, but it should be rare

`reason8 headless tables --check` runs it with the checks of the units and the features.
"""

from __future__ import annotations

import polars as pl

#: How many examples of each kind of difference to keep.
EXAMPLES = 5


def check(game_tables: dict[str, pl.DataFrame]) -> dict:
    """The checks of the module docstring on the tables of one game; empty before format 7
    or when sight and radar were not written."""
    game = game_tables["game"].row(0, named=True)
    if not game["visibility"]:
        return {}
    visibility = game_tables["visibility"].drop("replay")
    events = game_tables["events"].drop("replay")
    # the neutral team's units (critters) are nobody's enemy
    ally_of_team = {team["team"]: team["ally_team"] for team in game["teams"] if not team["gaia"]}
    counts = visibility.group_by("sense", "entered").len().sort("sense", "entered")
    return {
        "rows": {
            f"{row['sense']}_{'enter' if row['entered'] else 'leave'}": row["len"]
            for row in counts.iter_rows(named=True)
        },
        "widget": {
            "unmatched": game["visibility_unmatched"],
            "multiple": game["visibility_multiple"],
        },
        "pairs": _pairs(visibility, events, ally_of_team),
        "radar_covers_sight": _radar_covers_sight(visibility),
        "hits": _seen_by_attacker(game_tables["hits"].drop("replay"), visibility, ally_of_team),
        "kills": _seen_by_attacker(
            events.filter(
                pl.col("kind") == "destroyed",
                pl.col("by_team").is_in(list(ally_of_team)),
                pl.col("team").is_in(list(ally_of_team)),
                pl.col("team").replace_strict(ally_of_team, default=-1)
                != pl.col("by_team").replace_strict(ally_of_team, default=-1),
            ),
            visibility,
            ally_of_team,
        ),
    }


def _pairs(visibility: pl.DataFrame, events: pl.DataFrame, ally_of_team: dict) -> dict:
    """Follow every unit, ally team and sense through its rows: how each stretch of being
    seen ended."""
    deaths: dict[int, list[int]] = {}
    gifts: dict[int, list[tuple[int, int]]] = {}  # unit -> (frame, ally team it went to)
    for row in events.filter(pl.col("kind").is_in(["destroyed", "given"])).iter_rows(named=True):
        if row["kind"] == "destroyed":
            deaths.setdefault(row["unit_id"], []).append(row["frame"])
        else:
            gifts.setdefault(row["unit_id"], []).append(
                (row["frame"], ally_of_team.get(row["team"]))
            )

    def ended(unit: int, ally: int, start: int, until: int | None) -> str | None:
        """Why a stretch from `start` ended without a leave before `until` (None: the end)."""

        def within(frame: int) -> bool:
            return frame >= start and (until is None or frame <= until)

        if any(within(frame) for frame in deaths.get(unit, ())):
            return "death"
        if any(within(frame) and to == ally for frame, to in gifts.get(unit, ())):
            return "given"
        if until is None:
            return "end"
        return None

    result = {"leave": 0, "death": 0, "given": 0, "end": 0, "unexplained": 0, "leave_first": 0}
    examples: list[dict] = []
    for (unit, ally, sense), rows in visibility.sort("frame", maintain_order=True).group_by(
        "unit_id", "ally_team", "sense", maintain_order=True
    ):
        start = None
        for frame, entered in rows.select("frame", "entered").iter_rows():
            if entered:
                if start is not None:
                    how = ended(unit, ally, start, frame)
                    result[how or "unexplained"] += 1
                    if how is None and len(examples) < EXAMPLES:
                        examples.append({"unit": unit, "ally": ally, "sense": sense, "f": frame})
                start = frame
            elif start is None:
                result["leave_first"] += 1
                if len(examples) < EXAMPLES:
                    examples.append({"unit": unit, "ally": ally, "sense": sense, "f": frame})
            else:
                result["leave"] += 1
                start = None
        if start is not None:
            result[ended(unit, ally, start, None) or "unexplained"] += 1
    return {**result, "examples": examples}


def _state_at(visibility: pl.DataFrame, rows: pl.DataFrame, sense: str) -> pl.Series:
    """Whether each of `rows` (``unit_id``, ``ally_team``, ``frame``) had its unit in
    `sense` of its ally team at its frame, after the rows of that frame."""
    changes = (
        visibility.filter(pl.col("sense") == sense)
        .with_row_index("order")
        .sort("frame", "order")
        .select("unit_id", "ally_team", "frame", "entered")
    )
    joined = (
        rows.with_row_index("row")
        .sort("frame")
        .join_asof(
            changes,
            on="frame",
            by=["unit_id", "ally_team"],
            strategy="backward",
            check_sortedness=False,  # both sorted by frame above
        )
    )
    return joined.sort("row").get_column("entered").fill_null(False)


def _radar_covers_sight(visibility: pl.DataFrame) -> dict:
    entered = visibility.filter(pl.col("sense") == "los", pl.col("entered")).select(
        "unit_id", "ally_team", "frame"
    )
    on_radar = _state_at(visibility, entered, "radar")
    return {"sight_entered": entered.height, "not_on_radar": int((~on_radar).sum())}


def _seen_by_attacker(rows: pl.DataFrame, visibility: pl.DataFrame, ally_of_team: dict) -> dict:
    """Of the units in `rows` (``unit_id``, ``frame``, ``by_team``), how many the attacker's
    ally team had in sight, only on radar, or neither."""
    attacked = rows.select(
        "unit_id",
        "frame",
        pl.col("by_team").replace_strict(ally_of_team, return_dtype=pl.Int16).alias("ally_team"),
    )
    in_sight = _state_at(visibility, attacked, "los")
    on_radar = _state_at(visibility, attacked, "radar")
    return {
        "units": attacked.height,
        "in_sight": int(in_sight.sum()),
        "on_radar_only": int((on_radar & ~in_sight).sum()),
        "neither": int((~on_radar & ~in_sight).sum()),
    }
