import gzip
import json
import math
from datetime import date
from pathlib import Path

import polars as pl

from reason8.headless.state import read_records
from reason8.openings.contact import (
    BY_POSITION,
    CONTACT,
    MEASURED,
    MEASURES,
    TABLE_SCHEMA,
    WINDOW,
    contact_measures,
    cutoff_effect,
    first_contact,
    load_measured,
    measure,
    measure_game,
    opening_cutoff,
    position_cutoffs,
    quantile_frame,
    read_fights,
    replay_name,
    report,
)
from reason8.replays.replay import Replay, load_replay
from tests import synthetic

FIXTURE = Path(__file__).parents[1] / "fixtures" / "replay.json"
UNIT_NAMES = {"1": "armcom", "2": "corcom", "3": "armflea", "4": "cormex", "5": "corak"}


def state_lines(events: list[dict], last_frame: int = 21600, attackers: str = "attacker"):
    """A state file: players 0 and 1 on side 0, players 2 and 3 on side 1, and Gaia."""
    teams = [{"team": team, "ally": team // 2, "gaia": False} for team in range(4)]
    teams.append({"team": 4, "ally": 2, "gaia": True})
    header = {"t": "header", "v": 2, "game": "G", "map": "M", "teams": teams}
    end = {"t": "end", "f": last_frame, "reason": "maxframe", "winners": [], "attackers": attackers}
    snapshot = {"t": "s", "f": 150, "wind": 3.5, "teams": [], "units": []}
    return [{**header, "unitdefs": UNIT_NAMES}, snapshot, *events, end]


def hit(frame, team, unit_def, by_team, by_def, damage=10):
    names = {name: int(number) for number, name in UNIT_NAMES.items()}
    return {
        "t": "hit",
        "f": frame,
        "u": 100 + team,
        "d": names[unit_def],
        "team": team,
        "x": 0,
        "z": 0,
        "by": 200 + by_team,
        "by_d": names[by_def],
        "by_team": by_team,
        "damage": damage,
        "paralyzer": False,
    }


def destroyed(frame, team, unit_def, by_team):
    names = {name: int(number) for number, name in UNIT_NAMES.items()}
    record = {"t": "destroyed", "f": frame, "u": 1, "d": names[unit_def], "team": team}
    return {**record, "x": 0, "z": 0, "built": True, "by_team": by_team}


EVENTS = [
    hit(3000, 0, "armflea", 2, "corak"),  # player 0's scout is shot
    destroyed(3010, 0, "armflea", 2),
    hit(3600, 2, "cormex", 0, "armflea"),  # player 0's scout plinks an extractor of player 2
    {"t": "damage", "f": 3630, "team": 2, "by_team": 0, "hits": 3, "damage": 30},
    hit(5400, 0, "armcom", 2, "corcom"),  # the commanders trade shots
    hit(5400, 2, "corcom", 0, "armcom"),
    hit(6000, 0, "armcom", 3, "corak"),
    {"t": "damage", "f": 6030, "team": 2, "by_team": 0, "hits": 9, "damage": 600},
    destroyed(7200, 2, "cormex", 0),
    destroyed(7300, 2, "cormex", 2),  # own side: self-destruct
    destroyed(7400, 2, "cormex", -1),  # nobody's doing
]


def write_state(path: Path, records: list[dict]) -> Path:
    with gzip.open(path, "wt", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, separators=(",", ":")) + "\n")
    return path


def test_read_fights(tmp_path):
    path = write_state(tmp_path / "game.jsonl.gz", state_lines(EVENTS))
    fights = read_fights(path)
    assert fights.map == "M"
    assert fights.complete and fights.last_frame == 21600
    assert fights.attackers == "attacker"
    assert fights.ally_teams == {0: 0, 1: 0, 2: 1, 3: 1}  # without Gaia
    assert [hit.frame for hit in fights.hits] == [3000, 3600, 5400, 5400, 6000]
    assert (fights.hits[0].unit, fights.hits[0].by_unit) == ("armflea", "corak")
    # only units destroyed by the other side are losses
    assert [(loss.frame, loss.team, loss.by_team) for loss in fights.losses] == [
        (3010, 0, 2),
        (7200, 2, 0),
    ]
    assert fights.damage == [(3630, 2, 0, 30), (6030, 2, 0, 600)]
    assert [record["t"] for record in read_records(path)] == (
        ["header"] + [event["t"] for event in EVENTS] + ["end"]
    )
    assert sum(record["t"] == "s" for record in read_records(path, snapshots=True)) == 1


def test_a_cut_off_state_file_is_not_complete(tmp_path):
    path = tmp_path / "game.jsonl"
    lines = [json.dumps(record) for record in state_lines(EVENTS)[:-1]]
    path.write_text("\n".join(lines) + '\n{"t":"hit","f":99')
    fights = read_fights(path)
    assert not fights.complete
    assert len(fights.hits) == 5


def test_contact_measures(tmp_path):
    fights = read_fights(write_state(tmp_path / "game.jsonl.gz", state_lines(EVENTS)))
    measures = contact_measures(fights)
    assert set(measures) == {0, 1, 2, 3}
    assert all(set(frames) == set(MEASURES) for frames in measures.values())
    # player 0: the scout does not count; the commander duel does unless left out
    assert measures[0] == {
        "any_hit": 3000,
        "hit_with_scouts": 3000,
        "hit": 5400,
        "hit_without_duels": 6000,
        "loss": None,
        "damage": None,
    }
    # player 2: hit by a scout counts (the extractor is not a scout)
    assert measures[2]["hit"] == 3600
    assert measures[2]["loss"] == 7200
    assert measures[2]["damage"] == 6030
    assert measures[3]["any_hit"] == 6000 and measures[3]["hit"] is None
    assert measures[1] == dict.fromkeys(MEASURES)
    assert first_contact(fights) == {0: 5400, 1: None, 2: 3600, 3: None}
    assert CONTACT == "hit"


def test_opening_cutoff():
    cutoffs = {"M": {"P1": 200}}
    window = 14400
    assert opening_cutoff("M", "P1", window, {0: 3000}, 0, cutoffs) == (3000, MEASURED)
    # no contact while the game was played, or later than the window: the whole window
    assert opening_cutoff("M", "P1", window, {0: None}, 0, cutoffs) == (window, MEASURED)
    assert opening_cutoff("M", "P1", window, {0: 20000}, 0, cutoffs) == (window, MEASURED)
    # not re-simulated, or the player is not in the state file: the position's cutoff
    assert opening_cutoff("M", "P1", window, None, 0, cutoffs) == (6000, BY_POSITION)
    assert opening_cutoff("M", "P1", window, {1: 3000}, 0, cutoffs) == (6000, BY_POSITION)
    assert opening_cutoff("M", "P1", 3000, None, 0, cutoffs) == (3000, BY_POSITION)
    assert opening_cutoff("M", "P2", window, None, 0, cutoffs) == (window, WINDOW)
    assert opening_cutoff("Other", "P1", window, None, 0, cutoffs) == (window, WINDOW)
    assert opening_cutoff(None, None, window, None, 0, cutoffs) == (window, WINDOW)


def contact_table(rows: list[tuple]) -> pl.DataFrame:
    """(replay, team, position, index, contact frame, order frames) rows on map M."""
    return pl.from_dicts(
        [
            {
                "replay": replay,
                "map": "M",
                "game_version": "G",
                "attackers": "attacker",
                "last_frame": 21600,
                "team": team,
                "ally_team": team % 2,
                "position": position,
                "role": "front",
                "position_index": index,
                **dict.fromkeys(MEASURES, frame),
                "order_frames": orders,
            }
            for replay, team, position, index, frame, orders in rows
        ],
        schema=TABLE_SCHEMA,
    )


def test_quantile_frame():
    assert quantile_frame([300, None, 100, 200], 0.5) == 300
    assert quantile_frame([300, None, 100, 200], 0.25) == 200
    assert math.isinf(quantile_frame([300, None, 100, 200], 0.75))
    assert math.isinf(quantile_frame([], 0.5))


def test_position_cutoffs_pool_the_two_sides():
    table = contact_table(
        [
            ("a", 0, "P1", 0, 3000, [10, 2900, 3100]),
            ("a", 1, "P3", 0, 6100, [10, 7000]),
            ("b", 0, "P1", 0, 9000, [10]),
            ("a", 2, "P2", 1, None, [10, 14000]),
            ("a", 3, "P4", 1, None, []),
            ("b", 2, "P2", 1, 15000, []),
        ]
    )
    cutoffs = position_cutoffs(table, quantile=0.5)
    # P1 and P3 share the median of 3000, 6100 and 9000 frames, rounded down to 5 s
    assert cutoffs == {"M": {"P1": 200, "P3": 200, "P2": 480, "P4": 480}}
    assert position_cutoffs(table, quantile=0.0)["M"]["P1"] == 100
    assert position_cutoffs(table, quantile=0.5, window_seconds=120)["M"]["P1"] == 120

    in_window, before, kept, kept_after, dropped_before = cutoff_effect(table, cutoffs, 14400)
    assert in_window == 8
    assert before == 6  # not the order at 3100 of the first player, nor the one at 7000
    assert kept == 7  # P1 and P3 end at frame 6000: the order at 7000 goes
    assert kept_after == 1  # the order at 3100, after that player's contact at 3000
    assert dropped_before == 0  # the order at 7000 came after its player's contact at 6100
    text = report(table)
    assert "| P1, P3" in text and "POSITION_CUTOFF_SECONDS = {" in text
    assert '"P1": 200, "P3": 200' in text


def test_measure_game_and_load_measured(tmp_path):
    replay = Replay(synthetic.with_own_starts_recommended(load_replay(FIXTURE).doc))
    teams = replay.teams()
    events = [hit(3000, 0, "armcom", 8, "corak")]
    lines = state_lines(events)
    lines[0]["teams"] = [
        {"team": team.team_id, "ally": team.ally_team_id, "gaia": False} for team in teams.values()
    ]
    fights = read_fights(write_state(tmp_path / "game.jsonl.gz", lines))
    rows = measure_game(fights, replay, "game", map_list={})
    assert len(rows) == 16
    by_team = {row["team"]: row for row in rows}
    assert by_team[0]["hit"] == 3000 and by_team[8]["hit"] is None
    assert by_team[0]["position"].startswith("P")
    assert by_team[0]["map"] == replay.meta["map"]
    assert len(by_team[0]["order_frames"]) == 47

    table = pl.from_dicts(rows, schema=TABLE_SCHEMA)
    path = tmp_path / "first_contact.parquet"
    table.write_parquet(path)
    measured = load_measured(path)
    assert measured["game"][0] == 3000 and measured["game"][8] is None
    assert load_measured(tmp_path / "missing.parquet") == {}
    assert replay_name("dir/2026-01-01_Map_1.2.jsonl.gz") == "2026-01-01_Map_1.2"
    assert replay_name("2026-01-01_Map_1.2.json.zst", ".json.zst") == "2026-01-01_Map_1.2"


def test_measure_reads_the_replays_from_the_tables(tmp_path):
    replay = Replay(synthetic.with_own_starts_recommended(load_replay(FIXTURE).doc))
    lines = state_lines([hit(3000, 0, "armcom", 8, "corak")])
    lines[0]["teams"] = [
        {"team": team.team_id, "ally": team.ally_team_id, "gaia": False}
        for team in replay.teams().values()
    ]
    out, state = tmp_path / "tables", tmp_path / "state"
    names = [f"2026-11-0{day}_10-00-00-000_x" for day in (1, 2, 3)]
    for name in names:
        (state / f"date={name[:10]}").mkdir(parents=True)
        write_state(state / f"date={name[:10]}" / f"{name}.jsonl.gz", lines)
    synthetic.write_tables(out, dict.fromkeys(names[:2], replay))
    # names[2] is not parsed: skipped

    table = measure(state, map_list={}, tables_dir=out)
    fights = read_fights(state / "date=2026-11-01" / f"{names[0]}.jsonl.gz")
    expected = [
        row | {"replay": name}
        for name in names[:2]
        for row in measure_game(fights, replay, "x", {})
    ]
    assert table.to_dicts() == pl.from_dicts(expected, schema=TABLE_SCHEMA).to_dicts()
    later = measure(state, map_list={}, tables_dir=out, since=date(2026, 11, 2))
    assert later["replay"].unique().to_list() == [names[1]]


def test_report_counts_the_engines_attacker_as_known():
    table = contact_table(
        [
            ("a.sdfz", 0, "P1", 0, 3000, [100]),
            ("b.sdfz", 0, "P1", 0, 3000, [100]),
            ("c.sdfz", 0, "P1", 0, 3000, [100]),
        ]
    ).with_columns(
        pl.when(pl.col("replay") == "a.sdfz")
        .then(pl.lit("last_attacker"))
        .when(pl.col("replay") == "b.sdfz")
        .then(pl.lit("attacker"))
        .otherwise(pl.lit("nearest"))
        .alias("attackers")
    )
    sample_row = next(line for line in report(table).splitlines() if line.startswith("| M "))
    cells = [cell.strip() for cell in sample_row.strip("|").split("|")]
    assert cells[3:5] == ["2", "1"]  # attacker known, attacker guessed
