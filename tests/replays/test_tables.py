import copy
import json
from compression import zstd
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from reason8.analysis.apm import end_frames, event_stream, player_actions
from reason8.replays import from_parsed, parse, tables
from reason8.replays.replay import Replay, load_replay
from tests import synthetic

FIXTURE = Path(__file__).parents[1] / "fixtures" / "replay.json"
DAY = "2026-11-01"
NAME = f"{DAY}_00-00-00-000_Test Valley 1.0_2026.09.03"


def every_kind() -> Replay:
    """The synthetic replay with an event of every type and end-of-game statistics."""
    document = copy.deepcopy(synthetic.command_replay().doc)
    document["events"][1:1] = [
        {"frame": None, "type": "startpos", "player": 0, "team": 0, "ready": 1, "x": 1.5, "z": 2},
        {"frame": 5, "type": "mapdraw", "player": 0, "action": "point", "x": 1, "z": 2},
        {"frame": 6, "type": "mapdraw", "player": 3, "action": "point", "x": 1, "z": 2}
        | {"label": "", "from_lua": True},
        {"frame": 7, "type": "mapdraw", "player": 0, "action": "line", "x": 1, "z": 2}
        | {"x2": 3, "z2": 4},
        {"frame": 8, "type": "mapdraw", "player": 0, "action": 7, "x": 1, "z": 2},
        {"frame": 9, "type": "share", "player": 0, "to_team": 1, "units": True}
        | {"metal": 10.5, "energy": 0},
        {"frame": 10, "type": "setshare", "player": 0, "team": 0, "metal": 0.99, "energy": 1},
        {"frame": 11, "type": "aishare", "player": 2, "ai": 0, "from_team": 1, "to_team": 0}
        | {"metal": 1, "energy": 2.25, "units": [301, 302]},
        {"frame": 12, "type": "team", "player": 0, "action": 9, "param": 3},
    ]
    document["events"].append({"frame": 20000, "type": "quit"})
    sample = dict.fromkeys(tables.TEAM_STATISTICS_FIELDS, 3) | {"metalUsed": 1.25}
    document["statistics"] = {
        "winningAllyTeamIds": [0],
        "playerStats": [
            dict.fromkeys(tables.PLAYER_STATISTICS_FIELDS, 4) | {"playerId": 9},
            dict.fromkeys(tables.PLAYER_STATISTICS_FIELDS, 5) | {"playerId": 0},
        ],
        "teamStats": {"1": [], "0": [sample, sample | {"frame": 4}]},
    }
    return Replay(document)


REPLAYS = {
    "fixture": lambda: load_replay(FIXTURE),
    "synthetic": synthetic.command_replay,
    "never started": lambda: synthetic.command_replay(started=False),
    "every kind": every_kind,
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


def filled(value):
    """A value of a document without names and without the keys whose value is None."""
    if isinstance(value, dict):
        return {
            key: filled(item) for key, item in value.items() if item is not None and key != "name"
        }
    if isinstance(value, list):
        return [filled(item) for item in value]
    return value


def rounded(value):
    """Floats rounded as command parameters are (float32 in the table, 2 decimals)."""
    if isinstance(value, dict):
        return {key: rounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [rounded(item) for item in value]
    if isinstance(value, float):
        rounded_value = round(value, 2)
        return int(rounded_value) if rounded_value.is_integer() else rounded_value
    return value


@pytest.mark.parametrize("make", REPLAYS.values(), ids=REPLAYS.keys())
def test_the_tables_give_the_document_back_without_names(make):
    replay = make()
    document = copy.deepcopy(replay.doc)
    document["source"] = {
        key: value for key, value in (document.get("source") or {}).items() if key != "trimmed"
    } | {"file": "game.sdfz"}
    back = tables.replay_documents(tables.replay_tables(replay, "game"))["game"]
    assert rounded(filled(back)) == rounded(filled(document))
    assert "name" not in json.dumps(back["players"] + back["spectators"])
    if replay.doc.get("statistics") is not None:  # teams listed without samples are kept
        assert (
            back["statistics"]["teamStats"].keys() == replay.doc["statistics"]["teamStats"].keys()
        )


def test_every_kind_comes_back_exactly():
    replay = every_kind()
    back = tables.replay_documents(tables.replay_tables(replay, "game"))["game"]
    events = [event for event in replay.events if event["type"] != "cmd"]
    assert [event for event in back["events"] if event["type"] != "cmd"] == events
    assert back["statistics"] == replay.doc["statistics"]
    assert back["ais"] == replay.doc["ais"]
    assert back["spectators"] == [{"playerId": 3, "userId": 2000}]
    mapdraws = [event for event in back["events"] if event["type"] == "mapdraw"]
    assert [type(event["action"]) for event in mapdraws] == [str, str, str, int]


def inserts(document: dict) -> list[dict]:
    return [event for event in document["events"] if "inner" in event]


@pytest.mark.parametrize(
    "change",
    [
        lambda document: document["meta"].update(newField=1),
        lambda document: document["players"][0].update(country="XX"),
        lambda document: document["events"][0].update(extra=1),
        lambda document: document["events"].append({"frame": 1, "type": "newtype"}),
        lambda document: document.update(newPart={}),
        lambda document: inserts(document)[0]["inner"].update(extra=1),
    ],
)
def test_a_field_without_a_column_is_refused(change):
    document = copy.deepcopy(synthetic.command_replay().doc)
    change(document)
    with pytest.raises(tables.UnknownField):
        tables.replay_tables(document, "game")


def test_a_value_its_column_cannot_hold_is_refused():
    document = copy.deepcopy(synthetic.command_replay().doc)
    document["events"][0]["player"] = "zero"
    with pytest.raises(TypeError):
        tables.replay_tables(document, "game")


@pytest.mark.parametrize("make", REPLAYS.values(), ids=REPLAYS.keys())
def test_actions_can_be_counted_from_the_tables(make, tmp_path):
    replay = make()
    out = synthetic.write_tables(tmp_path / "tables", {NAME: replay})
    stream = event_stream(tables.open_source(out), [NAME]).collect()
    events = [dict(row) for row in stream.drop("replay").iter_rows(named=True)]
    rebuilt = Replay({**replay.doc, "events": events})
    if replay.end_frame is not None:
        assert player_actions(rebuilt) == player_actions(replay)
        assert end_frames(rebuilt) == end_frames(replay)


@pytest.mark.parametrize("make", REPLAYS.values(), ids=REPLAYS.keys())
def test_replay_headers_hold_the_document_but_its_events(make):
    replay = make()
    rows = tables.replay_tables(replay, "game")
    header = tables.replay_headers(rows[tables.GAMES], rows[tables.PLAYERS])["game"]
    meta = {key: value for key, value in replay.meta.items() if key in header.meta}
    assert filled(header.meta) == filled(meta)
    for key in ("allyTeams", "unitdefs", "players", "ais", "spectators"):
        assert filled(header.doc[key]) == filled(replay.doc.get(key))
    for key in ("modoptions", "mapoptions", "restrictions"):
        assert header.doc[key] == (replay.doc.get(key) or {})
    assert header.teams() == replay.teams()
    assert header.doc["source"]["parser"] == (replay.doc.get("source") or {}).get("parser")
    assert "events" not in header.doc and "statistics" not in header.doc


def test_tables_keep_no_names():
    rows = tables.replay_tables(every_kind(), "game")
    for frame in rows.values():
        assert "name" not in frame.columns
        for column in frame.columns:
            if frame.schema[column] == pl.String:
                assert not any("Player" in str(value) for value in frame[column])
                assert not any("Spectator" in str(value) for value in frame[column])
    players = rows[tables.PLAYERS]
    assert players["role"].to_list() == ["player", "player", "ai", "spectator"]
    assert players["user_id"].to_list() == [1000, 1001, None, 2000]
    assert players["ai_name"].to_list() == [None, None, "BARb(1)", None]
    game = rows[tables.GAMES].row(0, named=True)
    assert game["match_id"] == 123
    assert game["statistics_teams"] == [1, 0]
    assert tables.options_dict(game["modoptions"]) == synthetic.command_replay().doc["modoptions"]


def test_event_rows():
    rows = tables.replay_tables(every_kind(), "game")
    assert set(rows) == set(tables.TABLES)
    for table, frame in rows.items():
        assert frame.schema == pl.Schema(tables.SCHEMAS[table]), table
    commands, selections = rows[tables.COMMANDS], rows[tables.SELECTIONS]
    seqs = pl.concat([rows[table].select("seq") for table in tables.EVENT_TABLES])["seq"]
    assert sorted(seqs.to_list()) == list(range(len(every_kind().events)))
    kinds = [event["type"] for event in every_kind().events]
    assert selections["seq"].to_list() == [
        seq for seq, kind in enumerate(kinds) if kind == "select"
    ]
    assert commands["seq"].to_list() == [seq for seq, kind in enumerate(kinds) if kind == "cmd"]
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
    events = rows[tables.EVENTS]
    assert events.filter(pl.col("type") == "gameover")["winners"].to_list() == [[0]]
    assert events.filter(pl.col("type") == "pause")["paused"].to_list() == [True, False]
    assert events.filter(pl.col("type") == "playerleft")["reason"].to_list() == [1]
    assert rows[tables.CHAT]["message"].to_list() == ["hello"]
    shares = rows[tables.SHARES]
    assert shares["type"].to_list() == ["share", "setshare", "aishare"]
    assert shares["units"].to_list() == [None, None, [301, 302]]
    assert rows[tables.TEAM_STATISTICS]["frame"].to_list() == [3, 4]
    assert rows[tables.PLAYER_STATISTICS]["player_id"].to_list() == [9, 0]


def stage_document(name: str, document: dict, staging: Path) -> dict:
    if document is None:
        return {"file": name, "status": "error", "error": "boom"}
    tables.stage(tables.replay_tables(document, name), staging, name)
    return {"file": name, "status": "ok"}


def plan(out: Path, day: str, replays: dict) -> tables.DayPlan:
    stored = tables.stored_replays(out / f"date={day}", day) or {}
    return tables.DayPlan(day, list(replays.items()), stored)


def test_write_scan_and_read_build_orders(tmp_path):
    out = tmp_path / "tables"
    replay, fixture = synthetic.command_replay(), load_replay(FIXTURE)
    other_day = "2026-11-02_10-00-00-000_x"
    plans = [plan(out, DAY, {NAME: replay.doc}), plan(out, "2026-11-02", {other_day: fixture.doc})]
    entries = []
    results = tables.update_days(
        plans, out, stage_document, jobs=1, on_entry=entries.append, log=lambda message: None
    )
    assert [result.converted for result in results] == [1, 1]
    assert sorted(entry["file"] for entry in entries) == [NAME, other_day]
    for table in tables.TABLES:
        path = out / f"date={DAY}" / f"{DAY}.{table}.parquet"
        assert tables.file_version(path) == tables.VERSION
    assert "converted" not in tables.summarize(results)

    orders = tables.build_orders(out)
    assert orders == {NAME: replay.build_orders(), other_day: fixture.build_orders()}
    assert tables.build_orders(out, until=date(2026, 11, 2)) == {NAME: replay.build_orders()}
    assert tables.build_orders(out, team=1, until_frame=100) == {NAME: replay.build_orders(1, 100)}
    games = tables.scan(tables.GAMES, out, since=date(2026, 11, 2)).collect()
    assert games["date"].to_list() == [date(2026, 11, 2)]
    assert tables.scan(tables.COMMANDS, out, since=date(2027, 1, 1)).collect().is_empty()

    # a day without replays to stage is left as it is
    again = tables.update_days([plan(out, DAY, {})], out, stage_document, jobs=0)
    assert again[0].up_to_date

    # a new replay of a day is added, the others are kept; one that fails is left out,
    # and a replay staged again whose staging fails keeps its rows
    other = f"{DAY}_12-00-00-000_x"
    day_plan = plan(out, DAY, {other: fixture.doc, f"{DAY}_13-00-00-000_x": None, NAME: None})
    result = tables.update_days([day_plan], out, stage_document, jobs=0, log=lambda m: None)[0]
    assert (result.converted, result.replays, len(result.errors)) == (1, 2, 2)
    assert set(tables.build_orders(out, until=date(2026, 11, 2))) == {NAME, other}
    assert tables.build_orders(out, replays=[NAME])[NAME] == replay.build_orders()
    assert not list(out.rglob("*.tmp"))
    assert sorted(path.name for path in out.iterdir()) == [f"date={DAY}", "date=2026-11-02"]


def test_open_source_reads_the_days_of_the_current_layout(tmp_path, monkeypatch):
    out = tmp_path / "tables"
    replay, fixture = synthetic.command_replay(), load_replay(FIXTURE)
    other, later = f"{DAY}_12-00-00-000_x", "2026-11-02_10-00-00-000_x"
    synthetic.write_tables(out, {NAME: replay, other: fixture, later: fixture})
    messages = []

    def build_orders(source):
        frame = tables.build_order_frame(source.scan(tables.COMMANDS)).collect()
        return tables.build_orders_from(frame)

    source = tables.open_source(out, until=date(2026, 11, 2), log=messages.append)
    assert (source.stored, messages) == ({NAME, other}, [])
    assert build_orders(source) == {NAME: replay.build_orders(), other: fixture.build_orders()}
    days = tables.open_source(out).by_day()
    assert [day.scan(tables.GAMES).collect()["replay"].to_list() for day in days] == [
        [NAME, other],
        [later],
    ]
    assert source.scan(tables.GAMES, [later, NAME]).collect()["replay"].to_list() == [NAME]
    assert source.scan(tables.GAMES, []).collect().is_empty()
    games = source.scan(tables.GAMES).collect()
    headers = tables.replay_headers(games, source.scan(tables.PLAYERS).collect())
    assert headers[other].teams() == fixture.teams()

    # only some replays and tables
    source = tables.open_source(out, replays=[later, NAME], tables=[tables.GAMES])
    assert source.scan(tables.GAMES).collect()["replay"].to_list() == [NAME, later]
    assert source.scan(tables.COMMANDS).collect().is_empty()
    assert tables.open_source(tmp_path / "none").scan(tables.GAMES).collect().is_empty()

    # a day of another layout, or with a table missing, is left out
    (out / "date=2026-11-02" / "2026-11-02.chat.parquet").unlink()
    assert tables.open_source(out, log=messages.append).stored == {NAME, other}
    monkeypatch.setattr(tables, "VERSION", "reason8.tables/99")
    assert tables.open_source(out, log=messages.append).stored == frozenset()
    assert len(messages) == 3 and "date=2026-11-02" in messages[0]


def test_sync_copies_the_day_files_and_merges_the_index():
    from reason8.data import sync

    area = sync.AREAS[tables.AREA]
    assert sync.is_data_file(f"date={DAY}/{DAY}.commands.parquet", area)
    assert sync.is_data_file(f"date={DAY}/{DAY}.games.parquet", area, since=date(2026, 11, 1))
    assert not sync.is_data_file(f"date={DAY}/{DAY}.games.parquet.tmp", area)
    assert not sync.is_data_file(f"_staging/{DAY}/{NAME}.commands.parquet", area)
    assert set(area.merged_files) == {tables.INDEX_NAME}
    assert "parsed" not in sync.AREAS


def run_parse(tmp_path, *arguments):
    from reason8.cli import make_parser

    parser_binary = tmp_path / "parser"
    parser_binary.write_text("")
    args = make_parser().parse_args(
        ["parse", str(tmp_path / "replays"), "--out", str(tmp_path / "tables"), "--jobs", "1"]
        + ["--parser", str(parser_binary), *arguments]
    )
    assert args.run(args) == 0


def test_parse_writes_the_replays_into_the_tables(tmp_path, monkeypatch):
    replays = tmp_path / "replays" / f"date={DAY}"
    replays.mkdir(parents=True)
    (replays / f"{NAME}.sdfz").write_bytes(b"1234")
    (replays / f"{DAY}_01-00-00-000_x.sdfz").write_bytes(b"")
    parsed = []

    def parse_replay(parser, replay):
        parsed.append(replay.name)
        if replay.stat().st_size == 0:
            raise ValueError("not a demo")
        document = copy.deepcopy(synthetic.command_replay().doc)
        document["source"] = {"file": replay.name, "bytes": replay.stat().st_size}
        return document, 10

    monkeypatch.setattr(parse, "parse_replay", parse_replay)
    monkeypatch.setattr(parse, "run_parser", lambda *arguments, **options: b"{}")
    monkeypatch.setattr(tables, "ProcessPoolExecutor", lambda max_workers: tables._InProcess())
    run_parse(tmp_path)
    out = tmp_path / "tables"
    assert tables.build_orders(out) == {NAME: synthetic.command_replay().build_orders()}
    index = parse.read_index(out)
    assert index[f"{NAME}.sdfz"]["status"] == "ok"
    assert index[f"{DAY}_01-00-00-000_x.sdfz"]["error"] == "ValueError: not a demo"
    assert not (tmp_path / "parsed").exists()

    # done replays are not parsed again, failed ones are; a changed file is parsed again
    parsed.clear()
    run_parse(tmp_path)
    assert parsed == [f"{DAY}_01-00-00-000_x.sdfz"]
    (replays / f"{NAME}.sdfz").write_bytes(b"12345")
    parsed.clear()
    run_parse(tmp_path)
    assert sorted(parsed) == [f"{NAME}.sdfz", f"{DAY}_01-00-00-000_x.sdfz"]
    parsed.clear()
    run_parse(tmp_path, "--force")
    assert len(parsed) == 2
    games = tables.scan(tables.GAMES, out).collect()
    assert games.select("replay", "sdfz_bytes").rows() == [(NAME, 5)]


def test_a_document_with_an_unknown_field_fails_its_replay(tmp_path, monkeypatch):
    replay = tmp_path / f"{NAME}.sdfz"
    replay.write_bytes(b"1")
    document = copy.deepcopy(synthetic.command_replay().doc)
    document["meta"]["newField"] = 1
    monkeypatch.setattr(parse, "parse_replay", lambda parser, path: (document, 1))
    monkeypatch.setattr(parse, "run_parser", lambda *arguments, **options: b"{}")
    entry = parse.parse_into(tmp_path / "parser", replay, tmp_path / "staging")
    assert entry["status"] == "error" and "newField" in entry["error"]
    assert not (tmp_path / "staging").exists()


def write_parsed(directory: Path, name: str, replay: Replay) -> Path:
    path = directory / f"date={name[:10]}" / f"{name}.json.zst"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(zstd.compress(json.dumps(replay.doc).encode()))
    return path


def test_the_parsed_json_of_earlier_versions_is_converted_once(tmp_path):
    parsed, out = tmp_path / "parsed", tmp_path / "tables"
    replay, fixture = synthetic.command_replay(), load_replay(FIXTURE)
    other, later = f"{DAY}_12-00-00-000_x", "2026-11-02_10-00-00-000_x"
    for name, document in ((NAME, replay), (other, fixture), (later, fixture)):
        write_parsed(parsed, name, document)
    (parsed / f"date={DAY}" / f"{DAY}_14-00-00-000_x.json.zst").write_bytes(b"not zstd")
    parse.write_index(parsed, {"a.sdfz": {"file": "a.sdfz", "status": "error", "error": "x"}})
    parse.write_index(out, {"b.sdfz": {"file": "b.sdfz", "status": "ok"}})

    results = from_parsed.convert(parsed, out, jobs=0, log=lambda message: None)
    assert [(result.converted, len(result.errors)) for result in results] == [(2, 1), (1, 0)]
    assert set(parse.read_index(out)) == {"a.sdfz", "b.sdfz"}
    expected = synthetic.write_tables(
        tmp_path / "direct", {NAME: replay, other: fixture, later: fixture}
    )
    for table in tables.TABLES:
        converted = tables.scan(table, out).collect()
        assert converted.equals(tables.scan(table, expected).collect()), table

    # converted documents are skipped; the one that failed is tried again
    again = from_parsed.convert(parsed, out, jobs=0, log=lambda message: None)
    assert [(result.converted, len(result.errors)) for result in again] == [(0, 1), (0, 0)]
    assert again[1].up_to_date


def test_the_tables_command_needs_the_parsed_directory(tmp_path):
    from reason8.cli import make_parser

    with pytest.raises(SystemExit):
        make_parser().parse_args(["tables"])
    args = make_parser().parse_args(["tables", "--from-parsed", str(tmp_path), "--jobs", "0"])
    assert args.from_parsed == tmp_path and args.run(args) == 0
