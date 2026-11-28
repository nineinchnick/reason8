"""Tests for `reason8 bot export-next-order` (no engine, no data needed)."""

import polars as pl
import pytest

from reason8.bot import next_order
from reason8.game.unitdefs import UnitDef


def decision_rows(rows: list[tuple[str, str, float]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=["builder_unit", "answer", "time_s"], orient="row")


def test_stand_in_shares_per_builder_and_minute(monkeypatch):
    monkeypatch.setattr(next_order, "MIN_ROWS", 4)
    rows = [("armcom", "armmex", 10.0)] * 3 + [("armcom", "armwin", 20.0)]
    rows += [("armcom", "armwin", 70.0)] * 2  # minute 1 has too few rows: the whole window
    rows += [("armcom", "assist", 600.0)] * 4  # past the window: its last minute
    rows += [("armck", "armmex", 5.0)] * 3  # too few rows in all: no answers
    rows += [("armcom", None, 5.0)]
    table = {
        (row["builder"], row["minute"]): row
        for row in next_order.stand_in_rows(decision_rows(rows))
    }
    assert {unit for unit, _ in table} == {"armcom"}
    assert table[("armcom", 0)]["answers"] == {"armmex": 0.75, "armwin": 0.25}
    assert not table[("armcom", 0)]["whole_window"] and table[("armcom", 0)]["rows"] == 4
    assert table[("armcom", 1)]["whole_window"] and table[("armcom", 1)]["rows"] == 10
    assert list(table[("armcom", 1)]["answers"]) == ["assist", "armmex", "armwin"]
    assert table[("armcom", next_order.MINUTES - 1)]["answers"] == {"assist": 1.0}


def test_stand_in_keeps_likely_answers_only(monkeypatch):
    monkeypatch.setattr(next_order, "MIN_ROWS", 1)
    rows = [("armlab", "armck", 1.0)] * 200 + [("armlab", "armpw", 1.0)]
    (row, *_) = next_order.stand_in_rows(decision_rows(rows))
    assert row["answers"] == {"armck": 0.995}  # armpw is below MIN_PROBABILITY


def extractor_order(match_id: int, seq_idx: int, x: float, z: float, position: str = "P1") -> dict:
    return {
        "match_id": match_id,
        "player_slot": 0,
        "seq_idx": seq_idx,
        "x": x,
        "z": z,
        "map": "Some Map",
        "position": position,
    }


def test_usual_metal_spots_in_the_usual_order():
    orders, openings = [], []
    for match_id in range(40):
        spot_a = (1000 + (match_id % 3) * 8.0, 1000)  # a little off the spot's centre
        spot_b = (500, 500)
        # three players in four take A first
        first, second = (spot_a, spot_b) if match_id % 4 else (spot_b, spot_a)
        orders.append(extractor_order(match_id, 1, *first))
        orders.append(extractor_order(match_id, 2, *second))
        orders.append(extractor_order(match_id, 3, *second))  # again: not a new spot
        if match_id < 5:  # one player in eight: not usual
            orders.append(extractor_order(match_id, 4, 3000, 3000))
        openings.append(
            {"match_id": match_id, "player_slot": 0, "map": "Some Map", "position": "P1"}
        )
    for match_id in range(40, 45):  # too few openings for P2
        orders.append(extractor_order(match_id, 1, 500, 500, "P2"))
        openings.append(
            {"match_id": match_id, "player_slot": 0, "map": "Some Map", "position": "P2"}
        )
    starts = {("Some Map", "P1"): (700.0, 700.0), ("Some Map", "P2"): (9.0, 9.0)}
    (row,) = next_order.usual_metal_spots(pl.DataFrame(orders), pl.DataFrame(openings), starts)
    assert (row["map"], row["position"], row["start"], row["openings"]) == (
        "Some Map",
        "P1",
        [700, 700],
        40,
    )
    assert [(spot["x"], spot["z"]) for spot in row["spots"]] == [(1008, 1000), (500, 500)]
    assert [spot["median_rank"] for spot in row["spots"]] == [1.0, 2.0]
    assert all(spot["share"] == 1.0 for spot in row["spots"])


def test_openings_built_away_from_their_start_are_left_out():
    openings = pl.DataFrame(
        {
            "match_id": [1, 2, 3],
            "player_slot": [0, 0, 0],
            "first_places_distance": [150.0, 900.0, None],
        }
    )
    assert next_order.near_their_start(openings)["match_id"].to_list() == [1, 3]
    # a dataset built before it had the column: the distances are given
    without = openings.drop("first_places_distance")
    distances = openings.filter(pl.col("first_places_distance").is_not_null())
    assert next_order.near_their_start(without, distances)["match_id"].to_list() == [1, 3]
    with pytest.raises(ValueError, match="first_places_distance"):
        next_order.near_their_start(without)


def test_spot_centres_merge_orders_of_one_spot():
    points = pl.DataFrame(
        {"x": [100.0, 110.0, 130.0, 160.0, 900.0], "z": [100.0, 96.0, 104.0, 100.0, 900.0]}
    )
    centres = next_order._spot_centres(points)
    assert len(centres) == 2
    assert centres[0] == pytest.approx((120.0, 100.0))
    assert next_order._nearest_spot(points, [])["spot"].null_count() == points.height


def test_structure_tasks():
    unit_defs = {
        "armmex": UnitDef("armmex", {"extractsmetal": 0.001}),
        "armwin": UnitDef("armwin", {"windgenerator": 25}),
        "armpw": UnitDef("armpw", {"speed": 80, "weapons": [{}]}),
        "armdrag": UnitDef("armdrag", {}),
    }
    assert next_order.structure_tasks(unit_defs) == {"armmex": "mex", "armwin": "energy"}
    assert next_order.extractor_names(unit_defs) == ["armmex"]
