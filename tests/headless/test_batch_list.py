"""Tests for writing a batch's replay list from a sample."""

import polars as pl
import pytest

from reason8 import cli
from reason8.headless import batch, batch_list

NAMES = [
    f"2026-11-0{day}_10-00-0{index}-000_Map A_2026.09.03.sdfz"
    for day in (1, 2)
    for index in range(5)
]


def setup_data(tmp_path):
    """A sample of ten games: one with a state file, one without its replay."""
    sample = pl.DataFrame(
        {
            "match_id": [str(index) for index in range(len(NAMES))],
            "replay_file_name": NAMES,
            "map": ["Map A"] * len(NAMES),
            "split": ["train"] * len(NAMES),
        }
    )
    sample_path = tmp_path / "logs" / "sample.parquet"
    sample_path.parent.mkdir()
    sample.write_parquet(sample_path)
    replays = tmp_path / "replays"
    for name in NAMES[:-1]:
        path = replays / f"date={name[:10]}" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
    states = tmp_path / "state"
    played = states / f"date={NAMES[2][:10]}" / NAMES[2].replace(".sdfz", ".jsonl.gz")
    played.parent.mkdir(parents=True)
    played.write_bytes(b"")
    return sample_path, replays, states


def test_replays_to_play_leaves_out_played_games_and_missing_replays(tmp_path):
    sample_path, replays, states = setup_data(tmp_path)
    paths, counts = batch_list.replays_to_play(pl.read_parquet(sample_path), replays, states)
    assert [path.name for path in paths] == [NAMES[0], NAMES[1], *NAMES[3:9]]
    assert counts == {"games": 10, "with_state": 1, "missing_replay": 1}


@pytest.mark.parametrize(
    ("count", "weights", "sizes"),
    [
        (10, [1], [10]),
        (10, [1, 1, 1], [4, 3, 3]),
        (13, [6, 4, 3], [6, 4, 3]),
        (2, [1, 1, 1], [1, 1, 0]),
    ],
)
def test_split_keeps_every_item_once_in_order(count, weights, sizes):
    parts = batch_list.split(list(range(count)), weights)
    assert [len(part) for part in parts] == sizes
    assert [item for part in parts for item in part] == list(range(count))


def test_split_refuses_weights_that_are_not_positive():
    with pytest.raises(ValueError, match="positive"):
        batch_list.split([1, 2], [1, 0])


def test_the_command_writes_parts_the_batch_reads(tmp_path, capsys):
    sample_path, replays, states = setup_data(tmp_path)
    out = tmp_path / "workers" / "context.txt"
    arguments = ["headless", "list", "--sample", str(sample_path), "--replays", str(replays)]
    arguments += ["--state-dir", str(states), "--out", str(out), "--weights", "2,1"]
    assert cli.main(arguments) == 0
    first, second = out.with_name("context.1.txt"), out.with_name("context.2.txt")
    assert first.read_text().startswith(f"# replays of the sample {sample_path} (sha256 ")
    listed = [*batch.read_list(first), *batch.read_list(second)]
    assert [path.name for path in listed] == [NAMES[0], NAMES[1], *NAMES[3:9]]
    assert len(batch.read_list(first)) == 5
    assert '"to_play": 8' in capsys.readouterr().out
