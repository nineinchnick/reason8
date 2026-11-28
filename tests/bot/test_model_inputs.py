import math

from reason8.bot import model_inputs
from reason8.game import maps
from reason8.models import trees

TYPES = ["mex", "win", "lab", "com", "other"]


def small_model() -> trees.TreeFile:
    """A model file without trees: only its inputs and builders matter here."""
    features = [
        {"name": name, "group": "history", "type": "categorical", "categories": categories}
        for name, categories in (
            ("faction", ["Armada", "Cortex"]),
            ("map", ["Some Map v1"]),
            ("position", ["P1", "P2"]),
            ("role", ["front", "tech"]),
            ("previous_1", ["<start>", "armmex", "armwin"]),
            ("builder_kind", ["commander", "factory"]),
            ("builder_role", ["com", "lab"]),
            ("builder_previous", ["<start>", "armmex", "armwin"]),
        )
    ]
    numbers = [
        "step_idx",
        "decision_index",
        *[f"ordered_{name}" for name in (*TYPES, *model_inputs.JOBS)],
        "builder_moves",
        "builder_build_power",
        "time_s",
        *model_inputs.ECONOMY,
        *[f"own_{state}_{name}" for name in TYPES for state in ("done", "building")],
        "team_build_power",
        "idle_build_power",
        *[f"{kind}_build_power_{each}" for kind in ("team", "idle") for each in model_inputs.KINDS],
        "skill",
    ]
    features += [{"name": name, "group": "x", "type": "numeric"} for name in numbers]
    return trees.from_document(
        {
            "format": trees.FORMAT,
            "name": "small",
            "answers": ["armmex", "<unknown>"],
            "features": features,
            "classes": [{"answers": [0], "weights": [1.0]}],
            "base_score": [0.0],
            "trees": [],
            "builders": {
                "armcom": {
                    "kind": "commander",
                    "moves": True,
                    "build_power": 300.0,
                    "answers": [0],
                },
                "armlab": {"kind": "factory", "moves": False, "build_power": 100.0, "answers": []},
            },
            "choice": {"threshold": 0.1, "unknown": "<unknown>"},
        }
    )


def test_parse_inputs():
    assert model_inputs.parse_inputs("map=Some Map v1; role=?; metal=12.5") == {
        "map": "Some Map v1",
        "role": None,
        "metal": 12.5,
    }


def test_history_follows_the_orders_the_library_records():
    lines = [
        "frame 10: armcom 1 commander: model chose armmex 0.90; 1 of 2 possible",
        "frame 10: armcom 1 commander: inputs step_idx=?",
        # a run: the same answer at most 6 frames later is one step
        "frame 16: armcom 1 commander: model chose armmex 0.90; 1 of 2 possible",
        # not carried out in its frame: no order
        "frame 40: armcom 1 commander: model chose assist 0.50; 1 of 2 possible",
        "frame 40: armcom 1 commander: cannot carry out assist: BARb has no assist task; "
        "left to BARb",
        "frame 50: armcom 1 commander: BARb ordered armwin",
        # ended unfinished a frame later: it was given, and counts
        "frame 60: armcom 1 commander: model chose armlab 0.50; 1 of 2 possible",
        "frame 61: armcom 1 commander: cannot carry out armlab: its task ended unfinished; "
        "left to BARb",
        "frame 70: armcom 1 commander: model chose armmex 0.90; 1 of 2 possible",
        "frame 70: armcom 1 commander: inputs step_idx=3",
    ]
    first, last = model_inputs.logged_decisions(lines)
    assert first["history"].inputs(1, TYPES)["step_idx"] == 0
    history = last["history"].inputs(1, TYPES)
    assert history["decision_index"] == 4  # armmex, armmex, armwin, armlab
    assert history["step_idx"] == 3
    assert history["previous_1"] == "armlab" and history["builder_previous"] == "armlab"
    assert history["ordered_mex"] == 2 and history["ordered_lab"] == 1
    assert history["ordered_assist"] == 0
    assert model_inputs._orders(lines) == [(10, 1), (16, 1), (50, 1), (60, 1), (70, 1)]


def resources(frame: int, metal: float) -> dict:
    return {"t": "r", "f": frame, "teams": [[0, metal, 1000, 2.5, 1.0, 900, 1000, 20, 5]]}


def test_compare_finds_what_differs():
    records = [
        {"t": "header", "unitdefs": {"1": "armcom", "2": "armlab", "3": "armmex"}},
        {"t": "created", "f": 0, "u": 100, "d": 1, "team": 0, "x": 10, "z": 10},
        {"t": "finished", "f": 0, "u": 100, "d": 1, "team": 0},
        resources(0, 1000),
        {"t": "idle", "f": 5, "u": 100, "d": 1, "team": 0},
        {"t": "created", "f": 20, "u": 101, "d": 3, "team": 0, "x": 0, "z": 0},
        resources(30, 980),
        {"t": "created", "f": 31, "u": 102, "d": 3, "team": 0, "x": 0, "z": 0},
        resources(60, 950),
    ]
    economy = "metal=980; metal_storage=1000; metal_income=2.5; metal_expense=1; energy=900; "
    economy += "energy_storage=1000; energy_income=20; energy_expense=5"
    logged = (
        "frame 31: armcom 100 commander: inputs faction=Armada; map=Some Map v1; position=P1; "
        "role=front; previous_1=<start>; builder_kind=commander; builder_role=com; "
        "builder_previous=<start>; builder_moves=1; builder_build_power=300; time_s=1.03333333; "
        f"{economy}; own_done_com=1; own_building_mex=1; team_build_power=300; "
        "team_build_power_commander=300; idle_build_power=300; idle_build_power_commander=300; "
        "skill=43.9"
    )
    lines = ["frame 31: armcom 100 commander: model chose armmex 0.90; 1 of 2 possible", logged]
    layout = maps.Layout(2, 8, ((maps.SpawnPoint("P1", 0, 0, "front"),),))
    map_list = {"Some Map v1": maps.MapMetadata(maps.StartPositions((layout,)), None, {})}
    model = small_model()
    result = model_inputs.compare(
        lines, records, 0, model, map_name="Some Map v1", map_list=map_list
    )
    assert result["start"] == {
        "map": "Some Map v1",
        "faction": "Armada",
        "position": "P1",
        "role": "front",
    }
    assert result["decisions_logged"] == 1 and result["rows_equal"] == 1
    assert result["inputs_differing"] == {} and result["skill"] == [43.9]

    # one more extractor under construction than the export had before frame 31
    wrong = [lines[0], logged.replace("own_building_mex=1", "own_building_mex=2")]
    result = model_inputs.compare(
        wrong, records, 0, model, map_name="Some Map v1", map_list=map_list
    )
    assert result["rows_equal"] == 0 and result["inputs_differing"] == {"own_building_mex": 1}
    assert result["largest_difference"] == {"own_building_mex": 1.0}
    assert math.isclose(result["examples"]["own_building_mex"][0]["expected"], 1.0)
