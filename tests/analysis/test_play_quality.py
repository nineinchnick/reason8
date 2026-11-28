"""Tests for `reason8 analysis play-quality` (small frames made by hand; no data needed)."""

from datetime import datetime

import numpy as np
import polars as pl
import pytest

from reason8.analysis import play_quality as pq

SECOND = 30  # frames


def resources(rows):
    """A ``resources`` table of one team: (second, metal, storage, income, expense, energy,
    energy storage)."""
    return pl.DataFrame(
        [
            {
                "replay": "g",
                "frame": second * SECOND,
                "team": 0,
                "metal": metal,
                "metal_storage": storage,
                "metal_income": income,
                "metal_expense": expense,
                "energy": energy,
                "energy_storage": energy_storage,
                "energy_income": 10.0,
                "energy_expense": 5.0,
                "wind": 0.0,
            }
            for second, metal, storage, income, expense, energy, energy_storage in rows
        ]
    )


def test_resource_scores_count_floating_stalling_and_income():
    rows = [(second, 500, 1000, 2.0, 2.0, 500, 1000) for second in range(1, 61)]  # settling
    rows += [(second, 1000, 1000, 4.0, 1.0, 500, 1000) for second in range(61, 91)]  # full
    rows += [(second, 0, 1000, 4.0, 4.0, 0, 1000) for second in range(91, 121)]  # empty
    scores = pq.resource_scores(resources(rows), window_minutes=2).row(0, named=True)
    assert scores["metal_float"] == pytest.approx(0.5)
    assert scores["metal_stall"] == pytest.approx(0.5)
    assert scores["energy_stall"] == pytest.approx(0.5)
    # 30 s at 3 metal a second over the store, of 240 metal of income
    assert scores["metal_overflow"] == pytest.approx(90 / 240)
    assert scores["spend_ratio"] == pytest.approx((30 + 120) / 240)
    assert scores["metal_spent"] == pytest.approx(60 * 2 + 30 + 120)
    assert "metal_income_3" not in scores  # past the window


def test_milestone_scores_take_the_nth_extractor_and_the_first_factory():
    def finished(frame, unit_def, team=0):
        return {
            "replay": "g",
            "frame": frame,
            "kind": "finished",
            "unit_def": unit_def,
            "team": team,
        }

    events = pl.DataFrame(
        [
            finished(300, "armmex"),
            finished(600, "armlab"),
            finished(900, "armmex"),
            finished(1200, "armwin"),
            finished(1500, "armmoho"),
            finished(10 * 60 * SECOND, "armmex"),
            finished(450, "cormex", team=1),
        ]
    ).with_columns(
        pl.col("kind").cast(pl.Enum(["created", "finished", "destroyed", "given", "idle"]))
    )
    types = pl.DataFrame({"game": ["v"], "unit_def": ["armlab"], "builder_kind": [pq.FACTORY]})
    games = pl.DataFrame({"replay": ["g"], "game": ["v"]})
    scores = {
        row["team"]: row for row in pq.milestone_scores(events, types, games).iter_rows(named=True)
    }
    assert scores[0]["first_factory"] == 20
    assert scores[0]["mex_3"] == 50
    assert scores[0]["mex_6"] is None
    assert scores[0]["mexes_at_5"] == 3
    assert scores[1]["first_factory"] is None
    assert scores[1]["mex_3"] is None
    assert scores[1]["mexes_at_5"] == 1


def test_is_extractor():
    names = pl.Series(["armmex", "cormoho", "legmext15", "armamex", "armmakr", "cormexp"])
    assert pl.select(pq.is_extractor(pl.lit(names))).to_series().to_list() == [
        True,
        True,
        True,
        True,
        False,
        True,
    ]


def test_time_weighted_share_integrates_step_functions():
    steps = pl.DataFrame(
        {
            "replay": ["g", "g", "g"],
            "team": [0, 0, 0],
            "frame": [0, 100, 150],
            "idle": [0.0, 10.0, 0.0],
            "power": [10.0, 10.0, 20.0],
        }
    )
    share = pq.time_weighted_share(steps, ["idle"], ["power"], end=200)["share"].item()
    # idle 10 for 50 frames, of power 10 for 150 frames and 20 for 50
    assert share == pytest.approx(500 / (1500 + 1000))


def test_oriented_and_normalised():
    scores = pl.DataFrame(
        {
            "map": ["a"] * 4 + ["b"] * 2,
            "position": ["p"] * 6,
            "mex_3": [10.0, 20.0, 30.0, None, 100.0, 200.0],
        }
    )
    turned = pq.normalised(pq.oriented(scores, ["mex_3"]), ["mex_3"])["mex_3"].to_list()
    # faster is better; ranked within each map and position
    assert turned[:3] == pytest.approx([1 / 3, 0.0, -1 / 3])
    assert turned[3] is None
    assert turned[4:] == pytest.approx([0.25, -0.25])


def test_between_share_and_intraclass():
    groups = np.array(["a", "a", "b", "b"])
    assert pq.between_share(np.array([1.0, 1.0, 3.0, 3.0]), groups) == pytest.approx(1.0)
    assert pq.between_share(np.array([1.0, 3.0, 1.0, 3.0]), groups) == pytest.approx(0.0)
    players = np.array([1, 1, 1, 2, 2, 2, 3])
    same = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 5.0])  # player 3 has one game: left out
    assert pq.intraclass(same, players) == pytest.approx(1.0)
    rng = np.random.default_rng(1)
    many = np.repeat(np.arange(400), 5)
    assert abs(pq.intraclass(rng.normal(size=many.size), many)) < 0.05


def test_cluster_bootstrap_counts_a_cluster_drawn_twice_as_two():
    players = np.array([1, 1, 2, 2])
    values = np.array([0.0, 0.0, 1.0, 1.0])
    point, low, high = pq.cluster_bootstrap(
        players, lambda rows, labels: pq.intraclass(values[rows], labels), resamples=50
    )
    assert point == pytest.approx(1.0)
    # a resample of one player twice has no variance between players: not 1
    assert np.isnan(low) or low <= 1.0


def test_team_differences_and_leave_one_out_means():
    scores = pl.DataFrame(
        {
            "match_id": [1, 1, 1, 1, 2, 2],
            "ally_team": [0, 0, 1, 1, 0, 1],
            "user_id": [10, 11, 12, 13, 10, 12],
            "won": [True, True, False, False, False, True],
            "score": [1.0, 3.0, 0.0, 0.0, 5.0, 1.0],
        }
    )
    differences = pq.team_differences(scores, ["score"]).sort("match_id")
    assert differences["score"].to_list() == [2.0, 4.0]
    assert differences["won"].to_list() == [True, False]
    elsewhere = pq.leave_one_out_means(scores, ["score"])["score"].to_list()
    assert elsewhere == [5.0, None, 1.0, None, 1.0, 0.0]


def test_later_ratings(tmp_path):
    pl.DataFrame(
        {
            "match_id": [1, 2, 3, 4],
            "game_type": ["Large Team", "Large Team", "Duel", "Large Team"],
            "is_ranked": [True, True, True, False],
            "start_time": [datetime(2026, 1, day) for day in (1, 2, 3, 4)],
        }
    ).write_parquet(tmp_path / "matches.parquet")
    pl.DataFrame(
        {
            "match_id": [1, 2, 3, 4, 1],
            "user_id": [7, 7, 7, 7, 8],
            "new_skill": [20.0, 22.0, 40.0, 50.0, 30.0],
        }
    ).write_parquet(tmp_path / "match_players.parquet")
    scores = pl.DataFrame({"match_id": [1, 2, 1], "user_id": [7, 7, 8]})
    later = pq.later_ratings(tmp_path, scores).sort("match_id", "user_id")
    assert later.rows() == [(1, 7, 20.0, 22.0, 1), (1, 8, 30.0, 30.0, 0), (2, 7, 22.0, 22.0, 0)]
