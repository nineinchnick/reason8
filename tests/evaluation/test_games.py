"""Tests for `reason8 eval games` and `reason8 eval report` (no engine needed)."""

import polars as pl

from reason8.evaluation.games import (
    TEAM_SCHEMA,
    game_specs,
    parse_seeds,
    team_measures,
)
from reason8.evaluation.report import pairs, report, seeds_for, share_interval
from reason8.game.unitdefs import UnitDef
from tests.openings.test_contact import hit, state_lines, write_state

UNIT_DEFS = {
    "armcom": UnitDef("armcom", {"metalcost": 1000, "energycost": 10000}),
    "cormex": UnitDef("cormex", {"metalcost": 50, "energycost": 500}),
    "corak": UnitDef("corak", {"metalcost": 40, "energycost": 900}),
}


def test_parse_seeds():
    assert parse_seeds("3") == [1, 2, 3]
    assert parse_seeds("5-7") == [5, 6, 7]
    assert parse_seeds("2,9") == [2, 9]


def test_game_specs_swap_the_ais():
    specs = game_specs([4], "Reason8", "BARb", ("Armada", "Cortex"))
    assert [(spec.name, spec.ais) for spec in specs] == [
        ("004-a", ("Reason8", "BARb")),
        ("004-b", ("BARb", "Reason8")),
    ]


def snapshot(frame, teams, units):
    return {"t": "s", "f": frame, "wind": 3.0, "teams": teams, "units": units}


def resources(team, metal_income, energy_income):
    return [team, 100, 1000, metal_income, 5.0, 500, 1000, energy_income, 20.0]


def test_team_measures(tmp_path):
    lines = state_lines([hit(3000, 0, "armcom", 2, "corak")])
    lines[1:2] = [
        snapshot(
            2850,
            [resources(0, 3.0, 30.0), resources(2, 4.0, 40.0)],
            [
                [1, 1, 0, 0, 0, 100, 100],  # armcom, finished
                [2, 4, 0, 0, 0, 100, 100],  # cormex of team 0, finished
                [3, 4, 0, 0, 0, 50, 40],  # cormex still being built
                [4, 5, 2, 0, 0, 100, 100],  # corak of team 2
            ],
        ),
        snapshot(3150, [resources(0, 9.0, 90.0), resources(2, 8.0, 80.0)], []),
    ]
    measures = team_measures(write_state(tmp_path / "s.jsonl.gz", lines), UNIT_DEFS)
    # team 0 met the enemy at frame 3000: the snapshot before it counts
    assert measures[0] == {
        "contact_frame": 3000,
        "measured_frame": 2850,
        "metal_income": 3.0,
        "energy_income": 30.0,
        "built_metal": 1050.0,
        "built_energy": 10500.0,
        "units": 2,
    }
    # team 2 had no contact: its opening runs to the window, past the last snapshot
    assert measures[2]["contact_frame"] is None and measures[2]["measured_frame"] == 3150
    assert measures[2]["units"] == 0


def team_rows(seed, built):
    """The 4 team rows of the two games of a seed: positions P1 (ally 0) and P9 (ally 1).
    `built` gives the evaluated AI's and the opponent's built metal."""
    ours, theirs = built
    rows = []
    for game in ("a", "b"):
        for ally_team, position, faction in ((0, "P1", "Armada"), (1, "P9", "Cortex")):
            evaluated = (game == "a") == (ally_team == 0)
            value = ours if evaluated else theirs
            rows.append(
                {
                    "seed": seed,
                    "game": game,
                    "team": ally_team,
                    "ally_team": ally_team,
                    "ai": "Reason8" if evaluated else "BARb",
                    "faction": faction,
                    "position": position,
                    "contact_frame": 4000,
                    "measured_frame": 3900,
                    "metal_income": 10.0,
                    "energy_income": 100.0,
                    "built_metal": value,
                    "built_energy": 1000.0,
                    "units": 10,
                }
            )
    return rows


def test_pairs_and_shares():
    rows = team_rows(1, (1100.0, 1000.0)) + team_rows(2, (900.0, 1000.0))
    teams = pl.DataFrame(rows, schema=TEAM_SCHEMA)
    paired = pairs(teams)
    assert paired.height == 4
    assert set(paired["ai"]) == {"Reason8"} and set(paired["opponent"]) == {"BARb"}
    share, low, high = share_interval(paired, "built_metal")
    assert share == 1.0 and low <= 1.0 <= high
    assert share_interval(paired, "metal_income")[0] == 1.0
    assert seeds_for(paired, "built_metal") is None  # too few seeds to tell
    assert "| built_metal |" in report(teams)


def test_seeds_for_grows_with_the_spread():
    narrow = [team_rows(seed, (1000.0 + seed, 1000.0)) for seed in range(1, 9)]
    wide = [team_rows(seed, (1000.0 + 100 * (-1) ** seed, 1000.0)) for seed in range(1, 9)]
    narrow_pairs = pairs(pl.DataFrame(sum(narrow, []), schema=TEAM_SCHEMA))
    wide_pairs = pairs(pl.DataFrame(sum(wide, []), schema=TEAM_SCHEMA))
    assert seeds_for(narrow_pairs, "built_metal") < seeds_for(wide_pairs, "built_metal")


def test_team_measures_at_a_fixed_frame(tmp_path):
    lines = state_lines([hit(3000, 0, "armcom", 2, "corak")])
    lines[1:2] = [
        snapshot(2850, [resources(0, 3.0, 30.0), resources(2, 4.0, 40.0)], []),
        snapshot(3150, [resources(0, 9.0, 90.0), resources(2, 8.0, 80.0)], []),
    ]
    measures = team_measures(write_state(tmp_path / "s.jsonl.gz", lines), UNIT_DEFS, at_frame=3200)
    # every team at the same frame, whatever its contact
    assert measures[0]["measured_frame"] == measures[2]["measured_frame"] == 3150
    assert measures[0]["contact_frame"] == 3000 and measures[0]["metal_income"] == 9.0
