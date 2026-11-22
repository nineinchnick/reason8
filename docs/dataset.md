# Public matches dataset and the first training slice

Findings from [`notebooks/01_matches.ipynb`](../notebooks/01_matches.ipynb)
(issue #4), on the dump of 2026-11-21. The selection is reproducible with
`reason8.match_dumps.select_matches()`.

## The dumps

[`data-processing`](https://github.com/beyond-all-reason/data-processing)
publishes four Parquet files at
`https://data-marts.beyondallreason.dev/<name>.parquet`, rebuilt twice a week.
`reason8.match_dumps.download_dumps()` caches them in `data/matches/` (or
`$REASON8_DATA_DIR/matches/`).

| file                    | size   | rows  | what                                   |
| ----------------------- | ------ | ----- | -------------------------------------- |
| `matches`               | 57 MB  | 1.58M | one row per game, 2022-06 .. now       |
| `match_players`         | 291 MB | 16.4M | one row per player per game            |
| `players`               | 1.5 MB | 164k  | user id, name, country                 |
| `player_skill_snapshot` | 4.3 MB | 127k  | current skill per player and game type |

Columns that matter (some differ from the issue's list):

- `matches`: `match_id`, `replay_id`, `replay_file_name`, `start_time`, `map`,
  `team_count`, `game_type`, `winning_team`, `game_duration` (s), `is_ranked`,
  **`engine`**, `game_version`, `is_public`, `has_deleted_player`.
- `match_players`: `match_id`, `team_id`, `user_id`, `party_id`, `left_after`
  (s), `old_skill`/`new_skill` (OpenSkill mu),
  `old_uncertainty`/`new_uncertainty` (sigma), `faction`. No start positions:
  those come from the replay itself (#19).

## Findings

- **Game types.** Large Team (6v6–8v8, almost always 8v8) is the biggest
  queue: 615k games, ~75k per quarter. Duel 302k, Small Team 217k. "Team" was
  split into Small/Large Team in mid-2024.
- **Maps.** In ranked Large Team over the last 6 months, *Supreme Isthmus
  v2.1* (41%) and *All That Glitters v2.2.3* (36%) dominate; no other map has
  more than 3k games.
- **Factions.** Armada 52%, Cortex 43%, Legion 3% (in the data since 2025) in
  the slice.
- **Skill.** `old_skill` is OpenSkill mu (new accounts start at 25 ± 8.33).
  Large Team players: p25 ~18, p75 ~29, p90 ~38, p99 ~55. Lobby averages are
  much narrower (mixed lobbies).
- **Replays.** 99.1% of matches have a `replay_file_name`; the missing ones
  are mostly the newest games (not processed yet). 875k matches with a replay
  are older than a year, but a HEAD probe of one replay per quarter found
  everything since 2023 still downloadable (2022: 404). The "may be expired
  after a year" warning doesn't affect a 6-month slice.
- **`is_public` is true for every row**: private/passworded lobbies
  (tournaments) are not in the dumps at all. Expert games have to come from
  elsewhere (#18).
- **Versions.** The dumps include the **engine version** (`engine`, also the
  suffix of the replay file name) and the exact `game_version`
  (`Beyond All Reason test-<build>-<sha>`). A new engine ships every 1–3
  months; the game version changes every few days.

## The first slice

Defaults of `reason8.match_dumps.select_matches()`:

| filter        | value                                                                                                                                                        |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| maps          | `Supreme Isthmus v2.1`, `All That Glitters v2.2.3`, `Rosetta 1.4.4`: the three most played Large Team maps (exact versions: layouts change between versions) |
| game type     | `Large Team`, ranked, exactly two teams of 8                                                                                                                 |
| time          | last 182 days of the dump (pinned in the notebook to 2026-05-23 .. 2026-11-22)                                                                               |
| duration      | ≥ 600 s                                                                                                                                                      |
| early leavers | no player left before 600 s                                                                                                                                  |
| skill         | lobby average `old_skill` ≥ **that map's** median over the games passing all other filters (Isthmus 22.1, Glitters 21.2, Rosetta 34.3)                       |
| replay        | `replay_file_name` present                                                                                                                                   |

Funnel over the three maps: 112,960 games → 94,531 ranked Large Team → 93,546
8v8 → 93,435 with replay → 89,916 ≥ 10 min → 85,825 no early leaver → **42,913
at or above their map's median skill**.

| map                      | candidates | median cutoff (mu) | in slice |
| ------------------------ | ---------- | ------------------ | -------- |
| Supreme Isthmus v2.1     | 44,263     | 22.1               | 22,132   |
| All That Glitters v2.2.3 | 39,278     | 21.2               | 19,639   |
| Rosetta 1.4.4            | 2,284      | 34.3               | 1,142    |

No other map has more than ~400 games after the same filters.

**Openings:** 42,913 games × 16 = **687k player-openings**: ~22k per start
position on Isthmus, ~20k on Glitters, ~1.1k on Rosetta (twice that per role
if roles mirror across the two teams). Isthmus and Glitters are plenty for an
opening model; Rosetta is small but enough for a frequency baseline and a
check that the approach works beyond one map. Rosetta lobbies are much
stronger than on the other maps, so the median is taken per map; one global
median would keep fewer Glitters games and more Rosetta ones. Replay download
and parsing time is the real constraint.

### Skill cutoff vs. the leaderboard

BAR publishes season leaderboards (top 100 per game type) at
[bar-rts.com/leaderboards](https://bar-rts.com/leaderboards), JSON at
`https://bar-rts.com/api/leaderboard` (seasons) and
`https://bar-rts.com/api/leaderboard/<season>`. The leaderboard rating is
exactly **mu − 3σ** (checked against `player_skill_snapshot`). Top 500 is not
published, so it is estimated by ranking players active in the window by mu −
3σ.

| reference                | rating (mu − 3σ) | mu        | games with lobby avg ≥ mu (3 maps) |
| ------------------------ | ---------------- | --------- | ---------------------------------- |
| per-map median (default) |                  | 21.2–34.3 | 42,913                             |
|                          |                  | 25        | 26,706                             |
|                          |                  | 30        | 13,577                             |
| top 500 (estimated)      | 30.8             | 38.4      | 3,625                              |
| Season 3 Large Team #100 | 40.5             | 49        | 132                                |

**Decision:** keep the median lobby cutoff (per map). A top-500 lobby average
leaves under 4k games and a top-100 one almost none, because even strong
lobbies are mixed. Use the leaderboard levels *per player* instead: the slice
already holds 101k openings by top-500-level players (mu ≥ 38.4, 783 distinct
players) and 29k by top-100-level players, for weighting or a "strong players"
evaluation set.

### Engine and game versions in the slice

| engine         | games   | share    | game versions | dates               |
| -------------- | ------- | -------- | ------------- | ------------------- |
| 2025.06.19     | 1,096   | 2.6%     | 9             | 2026-05-23 .. 05-26 |
| 2025.06.24     | 12,681  | 29.6%    | 57            | 2026-05-26 .. 07-13 |
| 2026.06.11     | 463     | 1.1%     | 4             | 2026-07-13 .. 07-15 |
| 2026.06.12     | 5,307   | 12.4%    | 40            | 2026-07-15 .. 08-05 |
| 2026.07.04     | 22,487  | 52.4%    | 89            | 2026-08-05 .. 11-16 |
| 2026.09.02     | 65      | 0.2%     | 2             | 2026-11-16          |
| **2026.09.03** | **814** | **1.9%** | 4             | 2026-11-16 .. 11-21 |

199 distinct game versions in total. Only 814 slice games match the engine we
have locally (`2026.09.03`). If re-simulation (#12) needs the exact engine and
game version, most of the slice needs other engines; the build-order PoC reads
commands straight from the replay and doesn't. How far back to go is the
version policy's call (#21); `select_matches(since=...)` applies it.

## Reproducing

```python
from datetime import datetime
from reason8 import match_dumps

match_dumps.download_dumps()
chosen = match_dumps.select_matches(
    match_dumps.scan_dump("matches"),
    match_dumps.scan_dump("match_players"),
    since=datetime(2026, 5, 23),
    until=datetime(2026, 11, 22),
)
chosen.select("match_id", "replay_file_name")
```

Without `since`/`until` the window is the last 182 days of whatever dump is
cached, so it moves with each rebuild.
