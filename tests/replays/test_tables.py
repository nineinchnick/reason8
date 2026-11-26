import json
from compression import zstd
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from reason8.analysis.apm import end_frames, player_actions
from reason8.replays import tables
from reason8.replays.replay import Replay, load_replay
from tests import synthetic

FIXTURE = Path(__file__).parents[1] / "fixtures" / "replay.json"
DAY = "2026-11-01"
NAME = f"{DAY}_00-00-00-000_Test Valley 1.0_2026.09.03"
REPLAYS = {
    "fixture": lambda: load_replay(FIXTURE),
    "synthetic": synthetic.command_replay,
    "never started": lambda: synthetic.command_replay(started=False),
}


def from_tables(replay: Replay, team=None, until_frame=None):
    commands = tables.replay_tables(replay, "game")[tables.COMMANDS].lazy()
    if team is not None:
        commands = commands.filter(pl.col("team") == team)
    frame = tables.build_order_frame(commands, until_frame).collect()
    return tables.build_orders_from(frame).get("game", [])


@pytest.mark.parametrize("make", REPLAYS.values(), ids=REPLAYS.keys())
def test_build_orders_equal_those_of_the_replay(make):
    replay = make()
    teams = [None, *sorted({order.team for order in replay.build_orders()} - {None})]
    for team in teams:
        for until_frame in (None, 0, 70, 90, 8 * 60 * 30):
            assert from_tables(replay, team, until_frame) == replay.build_orders(team, until_frame)


def test_synthetic_orders_cover_the_cases():
    orders = synthetic.command_replay().build_orders()
    assert {order.count for order in orders} >= {1, 5, 20, 100, -1, -5, -20}
    assert any(order.quota for order in orders)
    assert any(order.inserted and order.kind == "structure" for order in orders)
    assert any(order.team is None for order in orders)
    assert any(order.unit is None for order in orders)
    assert any(order.facing is None and order.kind == "structure" for order in orders)


@pytest.mark.parametrize("make", REPLAYS.values(), ids=REPLAYS.keys())
def test_teams_equal_those_of_the_replay(make):
    replay = make()
    players = tables.replay_tables(replay, "game")[tables.PLAYERS]
    assert tables.teams_from(players)["game"] == replay.teams()


def events_from_tables(rows: dict[str, pl.DataFrame]) -> list[dict]:
    """The command, select, team and playerleft events of a replay, rebuilt from its tables."""
    events = []
    for index, row in enumerate(rows[tables.COMMANDS].iter_rows(named=True)):
        event = {"order": (index, 1, 0), "type": "cmd", "frame": row["frame"], "via": row["via"]}
        event |= {"player": row["player"], "cmd": row["command"]}
        if row["ai"] is not None:
            event["ai"] = row["ai"]
        if row["units"] is not None:
            event["units"] = row["units"]
        events.append(event)
    for row in rows[tables.SELECTIONS].iter_rows(named=True):
        events.append({"order": (row["commands_before"], 0, row["seq"]), "type": "select", **row})
    for row in rows[tables.EVENTS].iter_rows(named=True):
        order = (row["commands_before"], 0, row["seq"])
        events.append({**row, "order": order, "type": str(row["type"])})
    return sorted(events, key=lambda event: event["order"])


@pytest.mark.parametrize("make", REPLAYS.values(), ids=REPLAYS.keys())
def test_actions_can_be_counted_from_the_tables(make):
    replay = make()
    rows = tables.replay_tables(replay, "game")
    rebuilt = Replay({**replay.doc, "events": events_from_tables(rows)})
    if replay.end_frame is not None:
        assert player_actions(rebuilt) == player_actions(replay)
        assert end_frames(rebuilt) == end_frames(replay)


def filled(value):
    """A value of a document without names and without the keys whose value is None."""
    if isinstance(value, dict):
        return {
            key: filled(item) for key, item in value.items() if item is not None and key != "name"
        }
    if isinstance(value, list):
        return [filled(item) for item in value]
    return value


@pytest.mark.parametrize("make", REPLAYS.values(), ids=REPLAYS.keys())
def test_replay_headers_hold_the_document_but_its_events(make):
    replay = make()
    rows = tables.replay_tables(replay, "game")
    header = tables.replay_headers(rows[tables.GAMES], rows[tables.PLAYERS])["game"]
    meta = {key: value for key, value in replay.meta.items() if key in header.meta}
    assert filled(header.meta) == filled(meta)
    for key in ("allyTeams", "unitdefs"):
        assert filled(header.doc[key]) == filled(replay.doc.get(key))
    for key in ("modoptions", "mapoptions", "restrictions"):
        assert header.doc[key] == (replay.doc.get(key) or {})
    for key in ("players", "ais"):
        for record, original in zip(header.doc[key], replay.doc[key], strict=True):
            record, original = filled(record), filled(original)
            uncertainty = original.pop("skillUncertainty", None)
            assert record.pop("skillUncertainty", None) == pytest.approx(uncertainty)
            assert record == original
    assert header.teams() == replay.teams()
    assert header.doc["source"]["parser"] == (replay.doc.get("source") or {}).get("parser")
    assert "events" not in header.doc


def test_open_source_adds_the_parsed_replays_the_tables_lack(tmp_path):
    parsed, out = tmp_path / "parsed", tmp_path / "tables"
    replay, fixture = synthetic.command_replay(), load_replay(FIXTURE)
    other = f"{DAY}_12-00-00-000_x"
    write_parsed(parsed, NAME, replay)
    write_parsed(parsed, other, fixture)
    tables.update(tables.parsed_days(parsed), out, jobs=0, log=lambda message: None)
    messages = []

    def build_orders(source):
        frame = tables.build_order_frame(source.scan(tables.COMMANDS)).collect()
        return tables.build_orders_from(frame)

    source = tables.open_source(parsed, out, log=messages.append)
    assert (source.stored, source.converted, messages) == ({NAME, other}, {}, [])
    assert build_orders(source) == {NAME: replay.build_orders(), other: fixture.build_orders()}

    # a replay parsed again, a new one, an unreadable one, and one of another day
    write_parsed(parsed, other, replay)
    new = f"{DAY}_13-00-00-000_x"
    write_parsed(parsed, new, fixture)
    (parsed / f"date={DAY}" / f"{DAY}_14-00-00-000_x.json.zst").write_bytes(b"not zstd")
    write_parsed(parsed, "2026-11-02_10-00-00-000_x", fixture)
    source = tables.open_source(parsed, out, until=date(2026, 11, 2), log=messages.append)
    assert source.stored == {NAME}
    assert set(source.converted) == {other, new}
    assert list(source.unreadable) == [f"{DAY}_14-00-00-000_x"]
    assert messages and "reason8 tables" in messages[0]
    assert build_orders(source) == {
        NAME: replay.build_orders(),
        other: replay.build_orders(),
        new: fixture.build_orders(),
    }
    games = source.scan(tables.GAMES).collect()
    assert games["replay"].to_list() == [NAME, other, new]
    days = source.by_day()
    assert [day.scan(tables.GAMES).collect()["replay"].to_list() for day in days] == [
        [NAME, other, new]
    ]
    assert list(days[0].unreadable) == [f"{DAY}_14-00-00-000_x"]
    later = tables.open_source(parsed, out, log=messages.append).by_day()
    assert [day.scan(tables.GAMES).collect().height for day in later] == [3, 1]
    assert source.scan(tables.GAMES, [new, NAME]).collect()["replay"].to_list() == [NAME, new]
    assert source.scan(tables.GAMES, []).collect().is_empty()
    headers = tables.replay_headers(games, source.scan(tables.PLAYERS).collect())
    assert headers[new].teams() == fixture.teams()

    # only some replays and tables; without parsed replays, the tables alone
    source = tables.open_source(parsed, out, replays=[new, NAME], tables=[tables.GAMES])
    assert source.scan(tables.GAMES).collect()["replay"].to_list() == [NAME, new]
    assert set(source.converted[new]) == {tables.GAMES}
    assert source.scan(tables.COMMANDS).collect().is_empty()
    alone = tables.open_source(None, out)
    assert alone.scan(tables.GAMES).collect()["replay"].to_list() == [NAME, other]
    assert tables.open_source(None, tmp_path / "none").scan(tables.GAMES).collect().is_empty()


def test_games_and_players_keep_no_names():
    rows = tables.replay_tables(synthetic.command_replay(), "game")
    for frame in rows.values():
        assert "name" not in frame.columns
        for column in frame.columns:
            if frame.schema[column] == pl.String:
                assert not any("Player" in str(value) for value in frame[column])
    players = rows[tables.PLAYERS]
    assert players["user_id"].to_list() == [1000, 1001, None]
    assert players["ai_short_name"].to_list() == [None, None, "BARb"]
    game = rows[tables.GAMES].row(0, named=True)
    assert game["match_id"] == 123
    assert tables.options_dict(game["modoptions"]) == synthetic.command_replay().doc["modoptions"]


def test_command_columns():
    commands = tables.replay_tables(synthetic.command_replay(), "game")[tables.COMMANDS]
    selections = tables.replay_tables(synthetic.command_replay(), "game")[tables.SELECTIONS]
    assert selections["commands_before"].to_list() == [0, 12]
    quota = commands.filter(pl.col("inserted") & (pl.col("insert_options") == 64 + 128)).row(
        0, named=True
    )
    assert (quota["command"], quota["options"], quota["units"]) == ("BUILD", 8 + 128, [300])
    nested = commands.filter(pl.col("inserted") & (pl.col("command") == "INSERT")).row(
        0, named=True
    )
    assert nested["params"] == [1, -6, 64]  # position, command id and options of the inner one
    first = commands.row(0, named=True)
    assert (first["x"], first["z"], first["facing"]) == pytest.approx((5200.12, 6704.5, 1))
    clicked = commands.filter(pl.col("via") == "COMMAND")
    assert clicked["units"].null_count() == clicked.height


def write_parsed(directory: Path, name: str, replay: Replay) -> Path:
    path = directory / f"date={name[:10]}" / f"{name}.json.zst"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(zstd.compress(json.dumps(replay.doc).encode()))
    return path


def test_update_scan_and_read_build_orders(tmp_path):
    parsed, out = tmp_path / "parsed", tmp_path / "tables"
    replay = synthetic.command_replay()
    fixture = load_replay(FIXTURE)
    write_parsed(parsed, NAME, replay)
    write_parsed(parsed, "2026-11-02_10-00-00-000_x", fixture)
    days = tables.parsed_days(parsed)
    results = tables.update(days, out, jobs=1, log=lambda message: None)
    assert [result.converted for result in results] == [1, 1]
    for table in tables.TABLES:
        assert (out / f"date={DAY}" / f"{DAY}.{table}.parquet").exists()

    orders = tables.build_orders(out)
    assert orders == {
        NAME: replay.build_orders(),
        "2026-11-02_10-00-00-000_x": fixture.build_orders(),
    }
    assert tables.build_orders(out, until=date(2026, 11, 2)) == {NAME: replay.build_orders()}
    assert tables.build_orders(out, team=1, until_frame=100) == {NAME: replay.build_orders(1, 100)}
    games = tables.scan(tables.GAMES, out, since=date(2026, 11, 2)).collect()
    assert games["date"].to_list() == [date(2026, 11, 2)]
    assert tables.scan(tables.COMMANDS, out, since=date(2027, 1, 1)).collect().is_empty()

    # nothing changed: nothing is converted again
    again = tables.update(days, out, jobs=1, log=lambda message: None)
    assert all(result.up_to_date for result in again)

    # a new replay of a day: only it is converted, the others are kept
    other = f"{DAY}_12-00-00-000_Test Valley 1.0_2026.09.03"
    write_parsed(parsed, other, fixture)
    result = tables.update_day(parsed / f"date={DAY}", out / f"date={DAY}")
    assert (result.converted, result.replays) == (1, 2)
    assert set(tables.build_orders(out, until=date(2026, 11, 2))) == {NAME, other}
    assert tables.build_orders(out, replays=[NAME])[NAME] == replay.build_orders()
    assert not list(out.rglob("*.tmp"))
    assert sorted(path.name for path in out.iterdir()) == [f"date={DAY}", "date=2026-11-02"]


def test_a_day_written_by_another_version_is_rebuilt(tmp_path, monkeypatch):
    parsed, out = tmp_path / "parsed", tmp_path / "tables"
    write_parsed(parsed, NAME, synthetic.command_replay())
    tables.update_day(parsed / f"date={DAY}", out / f"date={DAY}")
    monkeypatch.setattr(tables, "VERSION", "reason8.tables/0")
    assert tables.update_day(parsed / f"date={DAY}", out / f"date={DAY}").converted == 1


def test_an_unreadable_replay_is_reported_and_retried(tmp_path):
    parsed, out = tmp_path / "parsed", tmp_path / "tables"
    write_parsed(parsed, NAME, synthetic.command_replay())
    broken = parsed / f"date={DAY}" / f"{DAY}_01-00-00-000_x.json.zst"
    broken.write_bytes(b"not zstd")
    result = tables.update_day(parsed / f"date={DAY}", out / f"date={DAY}")
    assert (result.converted, len(result.errors)) == (1, 1)
    again = tables.update_day(parsed / f"date={DAY}", out / f"date={DAY}")
    assert not again.up_to_date and again.converted == 0


def test_sync_copies_the_day_files_and_not_the_staged_ones():
    from reason8.data import sync

    area = sync.AREAS[tables.AREA]
    assert sync.is_data_file(f"date={DAY}/{DAY}.commands.parquet", area)
    assert sync.is_data_file(f"date={DAY}/{DAY}.games.parquet", area, since=date(2026, 11, 1))
    assert not sync.is_data_file(f"date={DAY}/{DAY}.games.parquet.tmp", area)
    assert not sync.is_data_file(f"_staging/{DAY}/{NAME}.commands.parquet", area)


def test_parse_updates_the_tables_of_the_days_it_parsed(tmp_path, monkeypatch, capsys):
    from reason8.cli import make_parser
    from reason8.replays import parse

    replays, parsed = tmp_path / "replays" / f"date={DAY}", tmp_path / "parsed"
    replays.mkdir(parents=True)
    (replays / f"{NAME}.sdfz").write_bytes(b"")

    def process_one(parser, replay, out_dir, zstd_level):
        write_parsed(out_dir, replay.stem, synthetic.command_replay())
        return {"file": replay.name, "status": "ok", "seconds": 0.0}

    monkeypatch.setattr(parse, "process_one", process_one)
    monkeypatch.setattr(parse, "ProcessPoolExecutor", lambda max_workers: tables._InProcess())
    monkeypatch.setattr(parse, "summarize", lambda entries: "")
    monkeypatch.setattr(tables, "default_jobs", lambda: 0)
    parser_binary = tmp_path / "parser"
    parser_binary.write_text("")
    arguments = ["parse", str(tmp_path / "replays"), "--out", str(parsed), "--jobs", "1"]
    args = make_parser().parse_args([*arguments, "--parser", str(parser_binary)])
    assert args.run(args) == 0
    orders = tables.build_orders(tmp_path / tables.AREA)
    assert orders == {NAME: synthetic.command_replay().build_orders()}
