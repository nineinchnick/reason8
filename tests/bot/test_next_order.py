"""Tests for `reason8 bot export-next-order` and the log of the model's orders (no engine, no
data needed)."""

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


ORDER_LINES = [
    "model stand-in (NOT the learned model: a fixed answer per builder unit and minute), "
    "464 rows for 58 builder units from reason8/stand_in.txt",
    "map 'M', start 711 7215: position P1 (start 681 7376), 9 usual metal spots",
    "frame 25: armcom 18284 commander: model chose armmex 0.40; 2 of 9 possible of 9 at 10% "
    "or more: armwin 0.40 armmex 0.29",
    "frame 25: armcom 18284: armmex on usual spot 1 of 9, BARb's spot 84 at 4888 11320",
    "frame 900: armcom 18284 commander: model chose assist 0.20; 3 of 9 possible of 9 at 10% "
    "or more: armwin 0.40",
    "frame 900: armcom 18284 commander: cannot carry out assist: BARb has no assist task for it; "
    "left to BARb",
    "frame 1900: armlab 3 factory: below threshold, best armck 0.08; 0 of 12 possible of 12 "
    "at 10% or more: armck 0.08; left to BARb",
    "frame 2000: armnanotc 7 tower: no answers; 0 of 0 possible of 0 at 10% or more; left to BARb",
    "frame 2100: armcom 18284 commander: model chose armmex 0.30; 1 of 1 possible of 4 at 10% "
    "or more: armmex 1.00",
    "frame 2100: armcom 18284: armmex on BARb's metal spot",
    "frame 2500: armcom 18284 commander: cannot carry out armmex: its task ended unfinished; "
    "left to BARb",
    "model orders ended at frame 6450, contact: first contact at frame 6433, armflash by corak; "
    "BARb takes over",
]


def test_model_orders_log_counts():
    teams: dict[int, dict] = {}
    for line in ORDER_LINES:
        next_order.count_line(teams, 4, line)
    team = next_order.summary(teams[4])
    assert (team["model"], team["model_rows"], team["position"], team["usual_spots"]) == (
        "stand-in",
        464,
        "P1",
        9,
    )
    assert team["idle_builders"] == 5
    assert team["outcomes"] == {
        "model chose": 3,
        "below threshold": 1,
        "nothing possible": 0,
        "no answers": 1,
    }
    assert team["not_given"] == 1 and team["unfinished"] == 1
    assert team["not_given_reasons"] == {"BARb has no assist task for it": 1}
    assert team["decided_by_model"] == 2 and team["decided_by_model_share"] == 0.4
    assert team["left_to_barb"] == 3 and team["left_to_barb_share"] == 0.6
    assert team["by_kind"]["commander"] == {"idle_builders": 3, "model_chose": 3}
    assert team["by_kind"]["factory"] == {"idle_builders": 1, "model_chose": 0}
    assert team["by_minute"] == [
        {"idle_builders": 2, "left_to_barb": 1},
        {"idle_builders": 3, "left_to_barb": 2},
    ]
    assert team["orders_chosen"] == {"armmex": 2, "assist": 1}
    assert team["extractors"] == {"usual spot": 1, "BARb's metal spot": 1}
    assert team["ended"]["reason"] == "contact" and team["ended"]["frame"] == 6450


def test_model_orders_that_ended_at_once_by_kind_of_answer():
    lines = [
        # an extractor whose task ended at once (a log of the library that says so)
        "frame 100: armcom 1 commander: model chose armmex 0.50; 1 of 9 possible of 9 at 10% "
        "or more: armmex 0.50",
        "frame 104: armcom 1 commander: armmex ended unfinished after 4 frames",
        "frame 104: armcom 1 commander: cannot carry out armmex: its task ended at once, "
        "unfinished; left to BARb",
        # an assist decided again within a second (an older log: no task ends)
        "frame 400: armcom 1 commander: model chose assist 0.50; 1 of 9 possible of 9 at 10% "
        "or more: assist 0.50",
        "frame 410: armcom 1 commander: model chose assist 0.50; 1 of 9 possible of 9 at 10% "
        "or more: assist 0.50",
        # that one carried out: the next decision is minutes later
        "frame 450: armcom 1 commander: carried out assist, chosen at frame 410",
        # a factory helped build, carried out
        "frame 5000: armcom 1 commander: model chose armlab 0.50; 1 of 9 possible of 9 at 10% "
        "or more: armlab 0.50",
        "frame 5000: armcom 1: armlab: helps build the one the team is building",
        "frame 5030: armcom 1 commander: carried out armlab, chosen at frame 5000",
        # a repair with no target: not given, not "ended at once"
        "frame 6000: armck 2 construction: model chose repair 0.50; 1 of 9 possible of 9 at "
        "10% or more: repair 0.50",
        "frame 6000: armck 2 construction: cannot carry out repair: no target for repair; left "
        "to BARb",
        "frame 6010: armck 2 construction: model chose armwin 0.50; 1 of 9 possible of 9 at "
        "10% or more: armwin 0.50",
        # a unit, by a factory, carried out
        "frame 7000: armlab 3 factory: model chose armck 0.50; 1 of 9 possible of 9 at 10% or "
        "more: armck 0.50",
    ]
    teams: dict[int, dict] = {}
    for line in lines:
        next_order.count_line(teams, 1, line)
    team = next_order.summary(teams[1])
    assert "events" not in team
    assert team["idle_builders"] == 7 and team["carried_out"] == 2 and team["helped_build"] == 1
    assert team["unfinished"] == 1 and team["not_given"] == 1
    assert team["ended_at_once"] == 2 and team["ended_at_once_share"] == round(2 / 7, 3)
    assert team["left_to_barb"] == 1
    assert team["by_answer"] == {
        "assist": {"chosen": 2, "not_given": 0, "ended_at_once": 1},
        "repair": {"chosen": 1, "not_given": 1, "ended_at_once": 0},
        "extractor": {"chosen": 1, "not_given": 0, "ended_at_once": 1},
        "factory": {"chosen": 1, "not_given": 0, "ended_at_once": 0},
        "other structure": {"chosen": 1, "not_given": 0, "ended_at_once": 0},
        "unit": {"chosen": 1, "not_given": 0, "ended_at_once": 0},
    }


def test_answer_kinds():
    tasks = {"armmex": "mex", "armlab": "factory", "armwin": "energy"}
    assert next_order.answer_kind("reclaim", "commander", tasks) == "reclaim"
    assert next_order.answer_kind("armmex", "commander", tasks) == "extractor"
    assert next_order.answer_kind("armlab", "construction", tasks) == "factory"
    assert next_order.answer_kind("armwin", "construction", tasks) == "other structure"
    assert next_order.answer_kind("armck", "factory", tasks) == "unit"


def test_model_orders_log_without_idle_builders():
    team = next_order.summary(next_order.new_team())
    assert team["idle_builders"] == 0 and team["decided_by_model_share"] is None


def test_learned_model_log_counts():
    teams: dict[int, dict] = {}
    for line in [
        "model builder_v1 (the learned trees) from reason8/builder_model.json: 28900 trees, "
        "489020 nodes, 281 inputs, read in 2.8 s, 13.7 MB; skill 43.894001 (the 0.9 quantile "
        "of training)",
        "map 'M', start 711 7215: position P1 (start 681 7376), role sea, 10 usual metal spots",
        "frame 25: armcom 18284 commander: model chose armmex 0.98; 1 of 29 possible of 414 at "
        "10% or more: armmex 0.98",
        "frame 25: armcom 18284 commander: inputs faction=Armada; position=P1; time_s=0.833",
        "frame 2417: armcom 18284 commander: BARb ordered armlab",
    ]:
        next_order.count_line(teams, 0, line)
    team = next_order.summary(teams[0])
    assert (team["model"], team["model_trees"], team["model_rows"]) == ("builder_v1", 28900, None)
    assert team["skill"] == "skill 43.894001 (the 0.9 quantile of training)"
    assert (team["position"], team["role"], team["usual_spots"]) == ("P1", "sea", 10)
    assert team["idle_builders"] == 1 and team["inputs_logged"] == 1 and team["barb_orders"] == 1
