from datetime import datetime, timedelta

import polars as pl
import pytest

from reason8.match_dumps import lobby_stats, replay_url, select_matches

T0 = datetime(2026, 6, 1)


def _match(match_id, **kw):
    row = {
        "match_id": match_id,
        "replay_id": f"r{match_id}",
        "replay_file_name": f"{match_id}.sdfz",
        "start_time": T0 + timedelta(days=match_id),
        "map": "Supreme Isthmus v2.1",
        "game_type": "Large Team",
        "game_duration": 1800,
        "is_ranked": True,
        "engine": "2026.09.03",
        "game_version": "Beyond All Reason test-1",
    }
    row.update(kw)
    return row


def _players(match_id, skill=30.0, team_size=8, left_after=1800, overrides=None):
    rows = [
        {
            "match_id": match_id,
            "team_id": i % 2,
            "user_id": match_id * 100 + i,
            "old_skill": skill,
            "left_after": left_after,
        }
        for i in range(2 * team_size)
    ]
    for i, kw in (overrides or {}).items():
        rows[i].update(kw)
    return rows


@pytest.fixture
def dumps():
    matches = pl.DataFrame(
        [
            _match(1),  # kept
            _match(2),  # kept, higher skill
            _match(3, map="Forge v2.3"),  # not a default map
            _match(4, game_type="Duel"),
            _match(5, is_ranked=False),
            _match(6, replay_file_name=None),
            _match(7, game_duration=300),
            _match(8),  # early leaver
            _match(9),  # 7v7
            _match(10),  # low skill
            _match(-400),  # too old
        ]
    )
    players = (
        _players(1)
        + _players(2, skill=40.0)
        + sum((_players(i) for i in (3, 4, 5, 6, 7)), [])
        + _players(8, overrides={3: {"left_after": 120}})
        + _players(9, team_size=7)
        + _players(10, skill=10.0)
        + _players(-400)
    )
    return matches, pl.DataFrame(players)


def test_lobby_stats(dumps):
    _, mp = dumps
    s = lobby_stats(mp).collect().sort("match_id")
    row = s.filter(pl.col("match_id") == 8).row(0, named=True)
    assert row["n_players"] == 16
    assert row["n_teams"] == 2
    assert row["max_team_size"] == 8
    assert row["min_left_after"] == 120


def test_select_matches_fixed_threshold(dumps):
    matches, mp = dumps
    out = select_matches(matches, mp, min_avg_skill=20.0)
    assert out["match_id"].to_list() == [1, 2]
    assert out.columns[:3] == ["match_id", "replay_id", "replay_file_name"]


def test_select_matches_median(dumps):
    matches, mp = dumps
    # candidates 1 (30), 2 (40), 10 (10): median 30 keeps 1 and 2
    assert select_matches(matches, mp)["match_id"].to_list() == [1, 2]
    assert select_matches(matches, mp, min_avg_skill=35.0)["match_id"].to_list() == [2]


def test_select_matches_median_is_per_map():
    # Isthmus lobbies at 30/40 (median 35), Glitters lobbies at 10/20 (median 15):
    # one global median (25) would drop both Glitters games
    isthmus, glitters = "Supreme Isthmus v2.1", "All That Glitters v2.2.3"
    matches = pl.DataFrame([_match(1), _match(2), _match(3, map=glitters), _match(4, map=glitters)])
    players = pl.DataFrame(
        _players(1, skill=30.0)
        + _players(2, skill=40.0)
        + _players(3, skill=10.0)
        + _players(4, skill=20.0)
    )
    out = select_matches(matches, players, maps=[isthmus, glitters])
    assert out["match_id"].to_list() == [2, 4]


def test_select_matches_filters_can_be_disabled(dumps):
    matches, mp = dumps
    out = select_matches(
        matches,
        mp,
        maps=None,
        game_type=None,
        ranked=None,
        team_size=None,
        window=None,
        min_avg_skill=None,
        early_leave_s=None,
        min_duration_s=None,
        require_replay=False,
    )
    assert out.height == matches.height


def test_select_matches_explicit_window(dumps):
    matches, mp = dumps
    out = select_matches(matches, mp, since=T0, until=T0 + timedelta(days=2), min_avg_skill=None)
    assert out["match_id"].to_list() == [1]


def test_select_matches_bad_threshold(dumps):
    matches, mp = dumps
    with pytest.raises(ValueError):
        select_matches(matches, mp, min_avg_skill="mean")


def test_replay_url():
    assert replay_url("a b.sdfz").endswith("/BAR/demos/a%20b.sdfz")


def test_select_matches_min_build():
    # A build is a release number, not a date: the older build was still played later.
    matches = pl.DataFrame(
        [
            _match(1, game_version="Beyond All Reason test-31075-1913fe9"),
            _match(2, game_version="Beyond All Reason test-31058-0308fc6"),
            _match(3, game_version="Beyond All Reason test-31115-0123abc"),
            _match(4, game_version="Beyond All Reason pr-9493-31506-5476673"),
            _match(5, game_version=None),
        ]
    )
    players = pl.DataFrame(sum((_players(i) for i in range(1, 6)), []))
    out = select_matches(matches, players, min_avg_skill=None, min_build=31075)
    assert out["match_id"].to_list() == [1, 3]
    assert select_matches(matches, players, min_avg_skill=None).height == 5
