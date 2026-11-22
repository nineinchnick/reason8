import json
import re
from compression import zstd
from pathlib import Path

import pytest

from reason8.replay import BuildOrder, iter_replays, load_replay

FIXTURE = Path(__file__).parent / "fixtures" / "replay.json"


@pytest.fixture(scope="module")
def replay():
    return load_replay(FIXTURE)


def test_meta(replay):
    assert replay.meta["map"] == "Supreme Isthmus v2.1"
    assert replay.meta["game"].startswith("Beyond All Reason")
    assert replay.meta["engine"] == "2026.09.03"
    assert replay.winning_ally_teams == [0]
    assert replay.meta["startFrame"] == 0
    assert replay.end_frame == 13447


def test_fixture_is_anonymised(replay):
    for player in replay.players:
        assert re.fullmatch(r"Player\d+", player["name"])
        assert "userId" not in player
    for spectator in replay.doc["spectators"]:
        assert re.fullmatch(r"Spectator\d+", spectator["name"])
        assert "userId" not in spectator
    assert replay.meta["gameId"] == "0" * 32
    assert replay.meta["serverMatchId"] is None
    for event in replay.events_of("chat"):
        assert re.fullmatch(r"chat message \d+", event["message"])


def test_fixture_is_small():
    assert FIXTURE.stat().st_size < 100_000


def test_teams(replay):
    teams = replay.teams()
    assert len(teams) == 16  # 8v8
    assert {team.ally_team_id for team in teams.values()} == {0, 1}
    assert {team.faction for team in teams.values()} <= {"Armada", "Cortex", "Legion"}
    team_8 = teams[8]
    assert team_8.faction == "Cortex"
    assert team_8.player_ids == (8,)
    assert not team_8.is_ai
    assert team_8.start_pos is not None


def test_events_are_in_frame_order(replay):
    frames = [event["frame"] for event in replay.events]
    assert frames == sorted(frames)
    assert frames[0] < 0  # pregame (chat, map drawing, start positions)
    start = next(replay.events_of("start"))
    assert start["frame"] == 0


def test_build_orders_are_resolved_to_unit_names(replay):
    orders = replay.build_orders()
    assert orders
    assert all(isinstance(order, BuildOrder) for order in orders)
    assert all(order.unit and re.fullmatch(r"[a-z0-9_]+", order.unit) for order in orders)
    assert {order.kind for order in orders} == {"structure", "factory"}
    assert {order.via for order in orders} == {"COMMAND", "AICOMMAND", "AICOMMANDS"}


def test_opening_of_one_team(replay):
    orders = replay.build_orders(team=8, until_frame=3 * 60 * 30)
    assert all(order.team == 8 for order in orders)
    # BAR's pregame build queue is sent by a widget right after the start.
    pregame = [order for order in orders if order.frame <= 10]
    assert [order.unit for order in pregame] == ["cormex", "cormex", "corlab"]
    assert all(order.via == "AICOMMAND" and order.kind == "structure" for order in pregame)
    first_factory = next(order for order in orders if order.kind == "factory")
    assert first_factory.unit == "corak"
    assert first_factory.builders is None  # COMMAND: goes to the current selection


def test_factory_counts(replay):
    orders = [order for order in replay.build_orders(team=8) if order.kind == "factory"]
    shift = next(order for order in orders if order.opts == ("shift",))
    assert shift.count == 5
    dequeue = next(order for order in orders if "right" in order.opts)
    assert dequeue.count == -5  # right+shift removes five


def test_structure_orders_have_positions(replay):
    structure = next(order for order in replay.build_orders() if order.kind == "structure")
    assert structure.x is not None and structure.z is not None
    assert structure.facing in (0, 1, 2, 3)


def test_quota_orders(replay):
    quota = [order for order in replay.build_orders() if order.quota]
    assert quota
    assert all(order.inserted and order.kind == "factory" for order in quota)
    assert any(event["cmd"] == "QUOTA_BUILD_TOGGLE" for event in replay.commands())


def test_queue_and_factory_commands_are_kept(replay):
    names = {event["cmd"] for event in replay.commands()}
    assert {"INSERT", "REMOVE", "STOP", "REPEAT", "FACTORY_GUARD", "STOP_PRODUCTION"} <= names
    # No command is left unnamed.
    assert not any(name.startswith("CMD_") for name in names)


def test_team_stats(replay):
    stats = replay.team_stats()
    assert sorted(stats) == list(range(16))
    final = stats[8][-1]
    assert final["frame"] >= replay.end_frame
    assert final["unitsProduced"] > 0


def test_communication_events(replay):
    for kind in ("chat", "mapdraw", "share"):
        assert next(replay.events_of(kind), None) is not None, kind


def test_load_zstd(tmp_path):
    path = tmp_path / "r.json.zst"
    path.write_bytes(zstd.compress(FIXTURE.read_bytes()))
    assert load_replay(path).meta["map"] == "Supreme Isthmus v2.1"


def test_iter_replays_reads_zstd_files(tmp_path):
    (tmp_path / "a.json.zst").write_bytes(zstd.compress(FIXTURE.read_bytes()))
    (tmp_path / "_index.jsonl").write_text("")
    assert [replay.meta["map"] for replay in iter_replays(tmp_path)] == ["Supreme Isthmus v2.1"]


def test_rejects_other_formats(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"format": "something-else"}))
    with pytest.raises(ValueError):
        load_replay(path)
