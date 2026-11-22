import json
import math
from collections import Counter
from compression import zstd
from pathlib import Path

import synthetic

from reason8.map_meta import (
    OFF_META_PROBABILITY,
    PositionClassifier,
    PositionNextUnitModel,
    agreement,
    by_group,
    consistency_tables,
    distinctive_orders,
    entropy,
    folds,
    held_out_probabilities,
    load_sample,
    next_unit_scores,
    planted,
    report,
    roles,
    sides_lines,
)
from reason8.opening_shift import NextUnitModel
from reason8.openings import Opening
from reason8.positions import FROM_GAME, FROM_MAP_LIST, StartSetup

FIXTURE = Path(__file__).parent / "fixtures" / "replay.json"
MAP = "Supreme Isthmus v2.1"

BOTS = ("armmex", "armmex", "armwin", "armwin", "armlab", "armck")
AIR = ("cormex", "corwin", "corwin", "corap", "corca")
SEA = ("armmex", "armtide", "armsy", "armcs")


ROLES = {"P5": "front", "P3": "air", "P8": "sea"}


def opening(match, team, position, units, faction="Armada", side=0, skill=25.0):
    return Opening(
        match=str(match),
        team=team,
        side=side,
        faction=faction,
        start=None,
        units=tuple(units),
        position=position,
        role=ROLES.get(position),
        skill=skill,
        frames=tuple(30 * 20 * index for index in range(len(units))),
    )


def games(count=20):
    """Games where three positions each play their own opening, one side each."""
    found = []
    for match in range(count):
        found.append(opening(match, 0, "P5", BOTS))
        found.append(opening(match, 1, "P3", AIR, faction="Cortex", skill=35.0))
        found.append(opening(match, 2, "P8", SEA))
    return found


def test_roles_drop_the_faction():
    assert roles(opening(0, 0, "P5", BOTS), 3) == ("mex", "mex", "win")
    assert roles(opening(0, 0, "P3", AIR)) == ("mex", "win", "win", "ap", "ca")


def test_entropy_and_agreement():
    assert entropy(Counter(a=4)) == 0
    assert entropy(Counter(a=2, b=2)) == 1
    assert entropy(Counter()) == 0
    assert agreement(Counter(a=4)) == 1
    assert agreement(Counter(a=1, b=1)) == 0
    # two of three pairs differ
    assert agreement(Counter(a=2, b=1)) == 1 / 3
    assert math.isnan(agreement(Counter(a=1)))


def test_consistency_tables_skip_small_groups():
    front = [opening(match, 0, "P5", BOTS) for match in range(30)]
    mixed = front[:15] + [opening(match, 1, "P3", AIR) for match in range(15)]
    lines = consistency_tables({"same": front, "mixed": mixed, "small": front[:3]}, "group")
    assert lines[0] == "| group | openings | first factory | share | entropy | agree |"
    assert "| same | 30 | bot lab | 100% | 0.00 | 100% |" in lines
    assert "| mixed | 30 | bot lab | 50% | 1.00 | 48% |" in lines
    # opening shape, then the first six orders: distinct values, top share, entropy, agreement
    assert "| same | 30 | 1 | 100% | 0.00 | 100% | 1 | 100% | 0.00 | 100% |" in lines
    assert "| mixed | 30 | 2 | 50% | 1.00 | 48% | 2 | 50% | 1.00 | 48% |" in lines
    assert not any("small" in line for line in lines)


def test_distinctive_orders_name_what_only_one_position_builds():
    found = games()
    by_position = {name: [o for o in found if o.position == name] for name in ("P5", "P3", "P8")}
    distinctive = distinctive_orders(by_position, top=2)
    # everyone orders a mex, only the sea player a shipyard and tidal generators
    assert [row[0] for row in distinctive["P8"]] == ["cs", "sy"]
    kind, here, elsewhere, seconds = distinctive["P8"][1]
    assert (here, elsewhere, seconds) == (1.0, 0.0, 40.0)
    assert {row[0] for row in distinctive["P3"]} == {"ap", "ca"}
    assert "mex" not in {row[0] for rows in distinctive.values() for row in rows}


def test_folds_split_matches_evenly():
    parts = folds([str(match) for match in range(25)], count=10)
    assert sorted(len(part) for part in parts) == [2] * 5 + [3] * 5
    assert set().union(*parts) == {str(match) for match in range(25)}
    assert parts == folds([str(match) for match in range(25)], count=10)


def test_classifier_tells_positions_apart():
    classifier = PositionClassifier().fit(games())
    assert classifier.predict(opening(99, 0, None, BOTS)) == "P5"
    assert classifier.predict(opening(99, 0, None, AIR)) == "P3"
    found = classifier.probabilities(opening(99, 0, None, SEA))
    assert math.isclose(sum(found.values()), 1)
    assert found["P8"] > 0.99
    # a unit nobody ordered in training does not break it
    assert classifier.predict(opening(99, 0, None, (*SEA, "armnever"))) == "P8"


def test_classifier_reads_each_kind_of_unit_once():
    few = opening(0, 0, "P5", ("armmex", "armwin", "armlab"))
    many = opening(0, 0, "P5", ("armmex",) * 3 + ("armwin",) * 40 + ("armlab",))
    assert PositionClassifier.words(few) == PositionClassifier.words(many)


def test_held_out_probabilities_use_the_time_window():
    results = held_out_probabilities(games(), seconds=480)
    assert len(results) == 60
    assert all(max(found, key=found.get) == o.position for o, found in results)
    # after 10 seconds one order is in: everyone has ordered a mex and no factory yet
    early = held_out_probabilities(games(), seconds=10)
    assert {len(o.units) for o, _ in early} == {1}
    assert sum(max(found, key=found.get) == o.position for o, found in early) <= 20


def test_by_group_adds_probabilities_up():
    summed = by_group({"P5": 0.25, "pond": 0.25, "P3": 0.5}, {"P5": "P5", "pond": "P5", "P3": "P3"})
    assert summed == {"P5": 0.5, "P3": 0.5}


def test_planted_openings_are_flagged_and_real_ones_are_not():
    results = held_out_probabilities(games(), seconds=480)
    assert not any(found[o.position] < OFF_META_PROBABILITY for o, found in results)
    identity = {name: name for name in ("P5", "P3", "P8")}
    swapped = planted(results, identity)
    assert len(swapped) == 60
    assert all(claimed != o.position for o, _, claimed in swapped)
    assert all(found[claimed] < OFF_META_PROBABILITY for _, found, claimed in swapped)
    # nothing to plant when every teammate is in the same group
    assert planted(results, dict.fromkeys(identity, "one")) == []


def test_position_helps_the_next_unit_model_when_positions_differ():
    # one faction, two positions that differ from the first order on
    found = []
    for match in range(20):
        found.append(opening(match, 0, "P5", ("armlab", "armpw", "armpw")))
        found.append(opening(match, 1, "P3", ("armap", "armpeep", "armca")))
        found.append(opening(match, 2, "P3", ("armap", "armpeep", "armca")))
    plain = next_unit_scores(found, NextUnitModel)
    informed = next_unit_scores(found, PositionNextUnitModel)
    assert plain["P5"][0] < informed["P5"][0] == informed["P5"][1]
    by_role = next_unit_scores(found, lambda: PositionNextUnitModel({"P5": "a", "P3": "a"}))
    assert by_role == plain


def test_report_on_synthetic_games():
    found = games(30)
    shown = StartSetup(FROM_GAME, True, True, FROM_GAME)
    hidden = StartSetup(FROM_MAP_LIST, False, None, FROM_MAP_LIST)
    setups = {str(match): hidden if match < 3 else shown for match in range(30)}
    text = report(MAP, found, setups)
    assert "30 games, 90 openings, 90 of 90 (100.0%) on a spot" in text
    # a position is shown with its role, in the order of the spawn point numbers
    assert "| P5 front | 30 | bot lab | 100% | 0.00 | 100% |" in text
    assert "| P3 air | air | 30 | 100% | P3 air 100% |" in text
    assert text.index("| P3 air | 30 |") < text.index("| P5 front | 30 |")
    assert text.index("| P5 front | 30 |") < text.index("| P8 sea | 30 |")
    assert "Left out (fewer than 20 openings)" in text
    assert "| recommended positions shown | 27 | 81 | 100.0% |" in text
    assert "| recommended positions not shown | 3 | 9 | 100.0% |" in text
    assert "| changed start boxes | 0 | 0 | - |" in text
    assert "## Start setup" not in report(MAP, found)


def test_sides_lines_compare_the_same_place_on_both_sides():
    # two positions per side; 20 games; the second side plays the first side's openings
    found = []
    places = {}
    for match in range(20):
        for team, (position, units, side, index) in enumerate(
            (("P5", BOTS, 0, 0), ("P3", AIR, 0, 1), ("P13", BOTS, 1, 0), ("P11", AIR, 1, 1))
        ):
            found.append(opening(match, team, position, units, side=side))
            places[(str(match), team)] = (side, index)
    lines = sides_lines(found, places, rounds=200)
    assert lines[0] == "First side against second side, 20 teams against 20:"
    assert "| first factory per place | 0.000 | 0.000 | 0.000 | 1.000 |" in lines
    assert "| P5 | P13 | bot lab | 100% of 20 | 100% of 20 |" in lines
    assert "| P3 | P11 | aircraft plant | 100% of 20 | 100% of 20 |" in lines

    # now the second side swaps its two openings: nothing in common per place
    swapped = [
        opening(int(o.match), o.team, o.position, AIR if o.units[0] == "armmex" else BOTS, side=1)
        if o.side == 1
        else o
        for o in found
    ]
    lines = sides_lines(swapped, places, rounds=200)
    row = next(line for line in lines if line.startswith("| first factory per place"))
    cells = [cell.strip() for cell in row.strip("|").split("|")]
    assert cells[1] == "1.000" and float(cells[4]) < 0.01
    assert "| P5 | P13 | bot lab | 100% of 20 | 0% of 20 |" in lines
    # openings without a place are left out; nothing to compare is no table
    assert sides_lines(found, {}) == []
    assert "## The two sides" in report(MAP, found, places=places)


def test_load_sample_keeps_full_human_games(tmp_path):
    document = synthetic.with_own_starts_recommended(json.loads(FIXTURE.read_text("utf-8")))
    (tmp_path / "game.json.zst").write_bytes(zstd.compress(json.dumps(document).encode()))
    flooded = dict(document, modoptions={**document.get("modoptions", {}), "map_waterlevel": "50"})
    (tmp_path / "flooded.json.zst").write_bytes(zstd.compress(json.dumps(flooded).encode()))
    short = dict(document, players=document["players"][:-1])
    (tmp_path / "short.json.zst").write_bytes(zstd.compress(json.dumps(short).encode()))
    sample = load_sample(tmp_path, map_list={})
    assert list(sample.openings) == [MAP]
    assert len(sample.openings[MAP]) == 16
    assert list(sample.setups) == [sample.openings[MAP][0].match]
    # every player is on a position: (side of the layout, place in its list)
    assert sorted(sample.places.values()) == [(side, n) for side in (0, 1) for n in range(8)]
    assert not load_sample(tmp_path, maps=["Rosetta 1.4.4"], map_list={}).openings
