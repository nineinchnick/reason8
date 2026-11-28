"""Tests for the cloud batch's queue messages and where their files are."""

from pathlib import Path

import pytest

from reason8.cloud.messages import (
    BatchSettings,
    GameMessage,
    MessageError,
    plan_batch,
    result_files,
    result_path,
)

NAME = "2026-11-01_10-00-00-000_Supreme Isthmus v2.1_2026.09.03"


def test_a_message_reads_back_as_it_was_written():
    message = GameMessage(
        f"date=2026-11-01/{NAME}.sdfz",
        BatchSettings(out_area="state-v7", max_frame=36000, timeout=600, settings=("A=1",)),
    )
    assert GameMessage.from_json(message.to_json()) == message


def test_where_a_games_files_are():
    message = GameMessage(f"date=2026-11-01/{NAME}.sdfz", BatchSettings(out_area="state-v7"))
    assert message.replay_path == f"replays/date=2026-11-01/{NAME}.sdfz"
    assert message.result_path == f"state-v7/date=2026-11-01/{NAME}.game.parquet"
    assert message.failure_path == f"cloud/failures/state-v7/date=2026-11-01/{NAME}.json"


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"replay": "x.sdfz"}',
        # not in its partition, or out of the replays area
        GameMessage(f"date=2026-11-01/{NAME}.sdfz").to_json().replace("2026-11-01/", "x/"),
        GameMessage(f"date=2026-11-01/{NAME}.sdfz").to_json().replace('"state"', '"replays"'),
    ],
)
def test_other_messages_are_refused(text):
    with pytest.raises(MessageError):
        GameMessage.from_json(text)


def test_result_files_end_with_the_game_table(tmp_path):
    state_file = tmp_path / f"{NAME}.jsonl.gz"
    for name in (state_file.name, f"{NAME}.game.parquet", f"{NAME}.units.parquet"):
        (tmp_path / name).write_bytes(b"x")
    assert [path.name for path in result_files(state_file)] == [
        f"{NAME}.jsonl.gz",
        f"{NAME}.units.parquet",
        f"{NAME}.game.parquet",
    ]


def test_a_batch_leaves_out_done_missing_and_repeated_games():
    names = [f"2026-11-0{day}_10-00-00-000_Map_2026.09.03" for day in range(1, 5)]
    listed = [
        Path(f"/data/replays/date=2026-11-0{day}/{name}.sdfz") for day, name in enumerate(names, 1)
    ]
    batch = BatchSettings(out_area="state-v7", max_frame=36000)
    plan = plan_batch(
        [*listed, listed[0]],
        batch,
        results=[result_path("state-v7", listed[1].name).removeprefix("state-v7/")],
        replays_in_bucket=[
            f"date=2026-11-0{day}/{name}.sdfz" for day, name in enumerate(names, 1) if day != 3
        ],
    )
    assert [message.replay for message in plan.messages] == [
        f"date=2026-11-01/{names[0]}.sdfz",
        f"date=2026-11-04/{names[3]}.sdfz",
    ]
    assert all(message.batch == batch for message in plan.messages)
    assert (plan.done, plan.missing_replay, plan.repeated) == (1, 1, 1)
