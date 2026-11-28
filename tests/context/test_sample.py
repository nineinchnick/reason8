"""Tests for drawing the context sample, on made-up games."""

import json

import polars as pl
import pytest

from reason8 import cli
from reason8.context import sample

MAPS = {"Map A": 30, "Map B": 20}


def games() -> pl.DataFrame:
    rows = []
    for map_index, (map_name, count) in enumerate(MAPS.items()):
        for index in range(count):
            match_id = f"{map_index}{index:03d}"
            rows.append(
                {
                    "match_id": match_id,
                    "replay_file_name": f"2026-11-0{map_index + 1}_10-00-{index:02d}-000_{map_name}"
                    f"_2026.09.03.sdfz",
                    "map": map_name,
                    "split": ("train", "validation", "test")[index % 3],
                    "status": "ok" if index % 10 else "no_positions",
                }
            )
    return pl.DataFrame(rows)


def test_draw_takes_the_counts_of_ok_games_per_map():
    drawn = sample.draw(games(), {"Map A": 10, "Map B": 5}, seed=1)
    assert drawn.columns == list(sample.COLUMNS)
    assert drawn.group_by("map").len().sort("map").rows() == [("Map A", 10), ("Map B", 5)]
    ok = games().filter(pl.col("status") == "ok")["match_id"].to_list()
    assert set(drawn["match_id"]) <= set(ok)
    assert drawn["match_id"].n_unique() == drawn.height


def test_draw_depends_on_the_seed_not_on_the_order_of_the_rows():
    counts = {"Map A": 10, "Map B": 5}
    first = sample.draw(games(), counts, seed=1)
    assert first.equals(sample.draw(games().reverse(), counts, seed=1))
    assert not first.equals(sample.draw(games(), counts, seed=2))


def test_draw_leaves_out_excluded_games():
    excluded = {
        name.removesuffix(".sdfz")
        for name in games().filter(pl.col("map") == "Map B")["replay_file_name"][:10]
    }
    drawn = sample.draw(games(), {"Map B": 8}, seed=1, excluded=excluded)
    assert not {name.removesuffix(".sdfz") for name in drawn["replay_file_name"]} & excluded


def test_draw_refuses_more_games_than_a_map_has():
    with pytest.raises(ValueError, match="Map B: 50 games asked for, 18 to draw from"):
        sample.draw(games(), {"Map B": 50}, seed=1)


def test_the_command_writes_the_sample_and_how_it_was_drawn(tmp_path, capsys):
    source = tmp_path / "openings_v2"
    source.mkdir()
    games().write_parquet(source / "games.parquet")
    (source / "manifest.json").write_text(json.dumps({"name": "openings_v2"}))
    excluded_name = games()["replay_file_name"][1].removesuffix(".sdfz")
    state = tmp_path / "state" / "date=2026-11-01"
    state.mkdir(parents=True)
    (state / f"{excluded_name}.jsonl.gz").write_bytes(b"")
    out = tmp_path / "logs" / "sample.parquet"
    arguments = [
        "context",
        "sample",
        "--source",
        str(source),
        "--count",
        "Map A=10",
        "--count",
        "Map B=5",
        "--seed",
        "3",
        "--exclude-state",
        str(tmp_path / "state"),
        "--out",
        str(out),
    ]

    assert cli.main(arguments) == 0
    drawn = pl.read_parquet(out)
    expected = sample.draw(games(), {"Map A": 10, "Map B": 5}, seed=3, excluded={excluded_name})
    assert drawn.equals(expected)
    description = json.loads((tmp_path / "logs" / "sample.json").read_text())
    assert description["format"] == sample.FORMAT
    assert description["seed"] == 3
    assert description["counts"] == {"Map A": 10, "Map B": 5}
    assert description["source"]["name"] == "openings_v2"
    assert description["excluded_match_ids"] == [games()["match_id"][1]]
    assert description["games"] == 15
    capsys.readouterr()

    assert cli.main(arguments) == 1  # not overwritten
    assert "--force" in capsys.readouterr().err
    assert cli.main([*arguments, "--seed", "4", "--force"]) == 0
    assert json.loads((tmp_path / "logs" / "sample.json").read_text())["seed"] == 4


def test_parse_count_keeps_the_equals_signs_of_a_map_name():
    assert sample.parse_count("Map=1 v2=12") == ("Map=1 v2", 12)
    with pytest.raises(Exception, match="MAP=N"):
        sample.parse_count("Map A")
