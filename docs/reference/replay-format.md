# Parsed replay format

How we turn BAR replays (`.sdfz`) into JSON, and the parts of that JSON we
rely on. Code: `tools/fetch-parser.sh`, `reason8/replays/parse.py` (writer),
`reason8/replays/replay.py` (reader).

Why orders are read from the commands, and the game state from re-simulated
replays: [ADR 0005](../decisions/0005-learn-decisions-with-their-context.md).

## Pipeline

```sh
# once: download the pinned sdfz-demo-parser 5.15.1 into data/tools/
tools/fetch-parser.sh
# data/replays/**/*.sdfz -> data/parsed/date=<day>/<name>.json.zst
uv run reason8 parse
# only the replays of some days
uv run reason8 parse --since 2026-11-01 --until 2026-11-08
# other inputs and output directory
uv run reason8 parse some/dir file.sdfz --out other/dir \
    --jobs 8 --force
```

1. **[sdfz-demo-parser](https://github.com/beyond-all-reason/demo-parser)**
   (BAR's own parser, used by bar-lobby) runs as a standalone executable, so
   no Node.js install is needed. `tools/fetch-parser.sh` downloads the pinned
   release and checks its SHA-256. We ask only for the packet types listed in
   `INCLUDE_PACKETS`, so frame, sync and ping packets are never emitted.
2. **`reason8/replays/sdfz.py`** reads the command packets straight from the
   demo to recover each command's numeric id. The parser leaves the id out
   whenever it has no name for it, and that's the case for every BAR custom
   command. It also reads the shared command id of `AICOMMANDS` packets as
   unsigned, so BUILD orders sent by widgets come out without a unit name (435
   of about 5,900 build orders in one 8v8 game). The two streams are zipped
   packet by packet, and any difference in count or parameters raises an
   error. Both bugs are worth reporting upstream.
3. **`reason8/replays/parse.py`** keeps what we need (metadata, players,
   statistics and a flat list of events) and writes one zstd-compressed JSON
   document per replay, in the date partition of the replay
   ([`dataset.md`](dataset.md#data-layout)).

Failures don't stop the run. Each replay gets a line in
`data/parsed/_index.jsonl` with `status` (`ok` or `error`), the error message,
the game and engine version (read with `--header-only` when the full parse
fails), sizes and the time taken. Replays that are already parsed are skipped
unless `--force` is given. The run ends with a summary that includes failures
per game version and per engine.

## Document

`format`
: `"reason8.replay/1"`. Bump it when the structure changes.

`source`
: `file` (replay file name), `bytes`, `parser` (parser name and version)

`meta`
: From the parser: `gameId`, `engine`, `game` (BAR version), `map`,
  `startTime`, `durationMs`, `fullDurationMs`, `winningAllyTeamIds`,
  `startPosType`. Added by us: `demoVersion`, `gameTime` and `wallclockTime`
  (seconds, from the demo header), `startFrame` (0, or null if the game never
  started), `endFrame` (frame of the first `gameover` event, null if there is
  none), `serverMatchId` (the lobby's match id, for joining with match
  metadata).

`allyTeams`
: `allyTeamId`, `startBox` (if any), `playerCount`

`players`
: `playerId`, `teamId`, `allyTeamId`, `name`, `userId`, `faction`, `rank`,
  `skill` (OpenSkill as a string, e.g. `"[45.67]"`), `skillUncertainty`,
  `startPos` `{x,y,z}`

`ais`
: Bots: `aiId`, `teamId`, `allyTeamId`, `name`, `shortName`, `version`,
  `faction`, `startPos`

`spectators`
: `playerId`, `name`, `userId` (needed to attribute chat)

`modoptions`, `mapoptions`, `restrictions`
: Lobby settings, as strings

`unitdefs`
: The game's unit definition names. Index *i* is the unit built by command id
  *-i*.

`statistics`
: `winningAllyTeamIds`, `playerStats` (per player: `numCommands`,
  `unitCommands`, mouse and keyboard counters), `teamStats` (see below)

`events`
: Everything that happened, in demo order (see below)

Names and user ids stay in the local `data/parsed/` files, because we need
them to join with match metadata. Don't publish these files. The committed
fixture (`tests/fixtures/replay.json`, made by `reason8/replays/fixture.py`)
is trimmed and anonymised: players become `Player1`…, spectators
`Spectator1`…; user ids, the game and match id, the start time and the file
name are replaced; chat text and map labels are replaced with placeholders.

Things we drop: the raw script and setup text (they contain names and IPs),
`hostSettings` (IPs; only `server_match_id` is kept), SPADS settings, the
parser's `chatlog` (the same as the `chat` events), Lua messages (FPS, mouse
positions, selected units and similar), system and log messages, and sync and
frame packets.

One Lua message is read separately: the list of user widgets each player had
installed, which BAR sends one second into the game. `reason8 widgets` reads
it straight from the `.sdfz` files into `data/widgets/`
([`automation-widgets.md`](../research/automation-widgets.md)).

## Time

Every event has `frame`, the simulation frame relative to game start (30
frames per second). It is computed from the demo's per-packet game time and
the `STARTPLAYING` packet with countdown 0. **Pregame events have negative
frames.** These are start-position picks, lobby chat and map drawing during
the countdown. Frames within a game are exact: packet times fall on 1/30 s
boundaries.

- Game start: the `start` event, frame 0.
- Game end: `meta.endFrame`. Every player sends its own `GAMEOVER` packet, and
  we take the first. `meta.gameTime` is the game length in seconds from the
  header.
- `meta.durationMs` is game time and `fullDurationMs` includes the lobby and
  countdown.

## Events

All events have `frame` and `type`. Most have `player`, the sender's player
number (`playerId` in `players` and `spectators`).

`cmd` (COMMAND, AICOMMAND, AICOMMANDS)
: See [Commands](#commands)

`select` (SELECT)
: `units`: the unit ids the player selected. A `COMMAND` applies to the
  current selection.

`start` (STARTPLAYING (countdown 0))
: (none)

`startpos` (STARTPOS)
: `team`, `ready`, `x`, `z`. Sent every time a player moves their start point;
  the last one per team wins. `players[].startPos` already holds the final
  position.

`gameover` (GAMEOVER)
: `winners` (ally team ids). One per player.

`chat` (CHAT)
: `to`, `message`. Per Recoil's `ChatMessage`: 252 = allies, 253 = spectators,
  254 = everyone, any other value is a player id (private message).

`mapdraw` (MAPDRAW)
: `action` (`point`, `line`, `erase`), `x`, `z`, and `x2`, `z2` for lines,
  `label` for points, `from_lua`

`share` (SHARE)
: `to_team`, `units` (true if the selected units were given), `metal`,
  `energy`

`setshare` (SETSHARE)
: `team`, `metal`, `energy`: the share-overflow fractions

`aishare` (AISHARE)
: `ai`, `from_team`, `to_team`, `metal`, `energy`, `units`

`team` (TEAM)
: `action` (`giveaway`, `resign`, `join_team`, `team_died`, …), `param`

`playerleft` (PLAYERLEFT)
: `reason` (0 lost connection, 1 left, 2 kicked)

`pause` (PAUSE)
: `paused`

`quit` (QUIT)
: (none)

`chat`, `mapdraw`, `share`, `setshare` and `aishare` are kept for team
communication.

### Commands

```json
{
  "frame": 1140,
  "type": "cmd",
  "player": 8,
  "via": "AICOMMANDS",
  "ai": 255,
  "team": 8,
  "units": [28370],
  "cmd": "BUILD",
  "cmd_id": -162,
  "unit": "armmex",
  "opts": ["shift"],
  "params": [5200, 38.1, 6704, 1]
}
```

`via`
: `COMMAND`: the player clicked; it applies to the player's current selection
  (`select` events), so there is no `units` field. `AICOMMAND`: one command
  for one unit (`units` has one id). `AICOMMANDS`: a batch; `units` is the
  target unit for each command when the packet is pairwise, otherwise every
  command goes to all listed units.

`ai`
: `aiId` for the AICOMMAND packets. **255 means a LuaUI widget of a human
  player**, not a bot. BAR widgets send many orders this way: the pregame
  build queue, area mex, build splitting, formation moves, and queue clean-up.

`team`
: The commanding team: the player's team, or the bot's team for a real AI
  (`ais[].teamId`). Taking over a teammate's units (`team` events with
  `join_team`) is not tracked; we use the player's starting team.

`cmd`, `cmd_id`
: Name and raw id. Negative ids are BUILD. Engine names come from `Command.h`.
  BAR custom commands come from BAR's `modules/customcommands.lua`: `PRIORITY`
  34571, `UNIT_SET_TARGET` 34923, `FACTORY_GUARD` 13921, `STOP_PRODUCTION`
  13923, `QUOTA_BUILD_TOGGLE` 23000, `AREA_MEX` 30100, `SHARE_UNIT` 30102, and
  others. An unknown id becomes `CMD_<id>`.

`unit`
: For BUILD, the unit's name (`unitdefs[-cmd_id]`). The table comes from the
  `UNITDEFS` Lua message BAR writes into every replay, bot games included.

`opts`
: Modifier keys: `shift`, `ctrl`, `alt`, `meta` (space), `right` (right mouse
  button), `internal`

`params`
: Raw parameters. Floats are rounded to 2 decimals.

`pos`, `inner`
: For INSERT only: the queue position and the inserted command (`cmd`,
  `cmd_id`, `unit`, `opts`, `params`), instead of `params`

**BUILD orders.**

- *Structure* (placed by a constructor or commander):
  `params = [x, y, z, facing]` (facing 0–3 = S, E, N, W). Without `shift` it
  **replaces** the builder's queue; with `shift` it is appended.
- *Factory* (unit production): `params = []`. Each order adds 1 unit, ×5 with
  `shift`, ×20 with `ctrl`. With `right` it **removes** that many from the
  queue. `alt` puts it at the front. `Replay.build_orders()` turns this into a
  signed `count`.
- *Pregame queue*: what the player queued before the start is sent in the
  first half second (frames 5–13) as `AICOMMAND` (`ai` 255) BUILD orders for
  the commander, all with `shift`. This is the planned opening; 12–15 of 16
  players used it in each of our 8v8 games.
- A single shift-drag sends one BUILD per spot in the same frame (we saw 64
  wind turbines at once). Many of them are never built.

**Queue edits.**

- `INSERT` (`cmd_id` 1): with `alt`, `pos` is a queue index (mostly 0, the
  front); without it, `pos` is a command *tag*.
- `REMOVE` (2): with `alt`, `params` are command ids to remove; without it,
  `params` are command *tags*. Tags are assigned at run time and are **not**
  in the replay, so removal by tag can't be resolved without re-simulating the
  replay. Widgets send thousands of these per game.
- `STOP` (0) clears the queue, and `WAIT` (5) pauses it.
- For factories, `ctrl` on INSERT and REMOVE targets the build queue rather
  than the rally orders.

**Factory settings.**

- `REPEAT` (115): `params [1]` on, `[0]` off. With repeat on, a factory keeps
  cycling its queue, so one order can produce many units.
- `QUOTA_BUILD_TOGGLE` (23000): `[1]` switches a factory to quota mode. The
  quotas themselves are local to BAR's `unit_factory_quota` widget and are
  **not** in the replay; only their effect is. The widget sends `INSERT` with
  `opts ["alt","ctrl"]` and an inner BUILD with `["internal","alt"]`.
  `BuildOrder.quota` marks these.
- `FACTORY_GUARD` (13921) sets whether new units guard the factory.
  `STOP_PRODUCTION` (13923) clears the queue.

## Commands aren't outcomes

A replay records what players **asked for**, not what happened. A BUILD order:

- can be replaced (a structure order without shift), dequeued (a factory order
  with `right`), removed by tag (`REMOVE`) or cleared (`STOP`,
  `STOP_PRODUCTION`);
- can be given to a builder that dies, can't reach the spot, or never gets to
  it (drag-placed rows of turbines);
- can turn into many units (`REPEAT`, ×5/×20 orders), or appear without the
  player clicking anything (quota widget, pregame queue).

So for openings, the data tells us the **order sequence** and how it was
given. Use frame, `via`, `queued`, `count`, `inserted` and `quota` to tell
"ordered" from "probably built", for example by dropping orders that were
dequeued or replaced soon after. Knowing what was actually **finished** needs
re-running the replay headlessly. The only outcome data in the replay is in
`statistics`:

- `teamStats[team]` is a list of snapshots with `frame`,
  `metalUsed`/`Produced`/`Excess`/`Received`/`Sent`, the same for energy,
  `damageDealt`/`Received`, and
  `unitsProduced`/`Died`/`Received`/`Sent`/`Captured`/`OutCaptured`/`Killed`.
  In the 2026.09 replays we looked at there is **only one snapshot per team,
  at the end of the game** (its frame is rounded up to the 15 s stats period,
  so it can be slightly past `endFrame`). There is no time series.
- `playerStats` holds command and input counters per player.

## Tables

Decoding a parsed document takes about a third of a second, however little of
it a pass needs. So the parsed replays also become Parquet tables, one row per
command, selection, event, player and game, and passes over many games read
only the columns they need. Code: `reason8/replays/tables.py`. Why:
[ADR 0005](../decisions/0005-learn-decisions-with-their-context.md); layout:
[ADR 0016](../decisions/0016-download-and-store-the-data.md). The JSON
documents stay the archival copy, and the tables can be rebuilt from them at
any time without parsing the replays again.

```sh
# data/parsed/date=<day>/ -> data/tables/date=<day>/<day>.<table>.parquet
uv run reason8 tables
uv run reason8 tables --since 2026-10-14 --until 2026-10-28 --jobs 4
uv run reason8 tables --force      # rebuild days that are up to date
```

Each day has one file per table, in the same partitions as the parsed replays.
A day is up to date when its `games` table lists exactly the parsed files of
that day with their sizes, and was written by the current version of the code
(`reason8.tables/1` in the file metadata). Other days are brought up to date
by converting only the replays that are new or changed: each one is converted
into small staged files (`tables/_staging/<day>/`), then the day is streamed
into new files that copy the rows of the unchanged replays, written under a
temporary name and renamed into place, `games` last. `reason8 parse` does the
same for the days it parsed replays of (`--no-tables` to skip it), and
`reason8 sync` copies the `tables` area.

Reading:

```python
from datetime import date

import polars as pl

from reason8.replays import tables

# a lazy frame with a `date` column; since inclusive, until exclusive
commands = tables.scan(tables.COMMANDS, since=date(2026, 10, 14), until=date(2026, 10, 28))
opening = tables.build_order_frame(commands, until_frame=8 * 60 * 30).collect()
# replay -> [BuildOrder], equal to Replay.build_orders(team, until_frame)
orders = tables.build_orders(since=date(2026, 10, 14), until_frame=8 * 60 * 30)
# replay -> team id -> Team, equal to Replay.teams()
teams = tables.teams_from(tables.scan(tables.PLAYERS).collect())
```

A pass over the parsed replays opens them with `open_source()` instead of
scanning the tables directly. It reads the tables of the days asked for, and
converts the parsed replays that the tables lack, or hold for an older parsed
file, from their JSON, one at a time and in memory only: it says how many, and
`reason8 tables` stores them so that the next pass does not convert them
again. A parsed replay that cannot be read is listed in `unreadable`, so each
pass reports it as it did when it read the JSON. Without parsed replays, the
tables alone are read. `replay_headers()` makes a `Replay` of everything but
the events from rows of `games` and `players`, so that `Replay.teams()`, the
positions and the game's lobby options work as on the document:

```python
source = tables.open_source(data_dir() / "parsed", since=date(2026, 10, 14))
headers = tables.replay_headers(
    source.scan(tables.GAMES).collect(), source.scan(tables.PLAYERS).collect()
)
```

Every table has `replay`, the replay's file name without `.sdfz`, and the rows
of a replay are together, in replay order. Strings are dictionary-encoded by
the Parquet writer; files are compressed with zstd (level 9), with statistics,
in row groups of 16,384 rows.

`commands`
: One row per command (`cmd` event), in stream order within a replay. `frame`
  Int32, `player`, `team`, `ai` Int16, `via` (an enum of `COMMAND`,
  `AICOMMAND`, `AICOMMANDS`), `units` (List of Int32, null for `COMMAND`,
  which applies to the player's current selection), `command` and
  `command_id`, `unit` (the unit a BUILD orders), `options` (UInt8, the bits
  of `OPTION_BITS`: 4 meta, 8 internal, 16 right, 32 shift, 64 ctrl, 128 alt),
  `params` (List of Float32, null for NaN), and `x`, `z` (Float32) and
  `facing` (Int8) for a BUILD of a structure. For an INSERT whose inserted
  command could be read, `inserted` is true, the columns above describe the
  inserted command, and `insert_options` and `insert_position` are the
  INSERT's own; an INSERT of an INSERT keeps the inner one's raw parameters.

`selections`
: One row per `select` event: `seq` (index in the document's events),
  `commands_before` (how many commands of the replay came before it), `frame`,
  `player`, `units`. A `COMMAND` row applies to the player's last selection
  with `commands_before` at most its position among the replay's commands.

`events`
: The events that end or interrupt a player's game: `start`, `gameover`,
  `team`, `playerleft`, `pause` and `quit`, with `seq`, `commands_before`,
  `frame`, `type`, `player`, `action` (for `team`: `resign`, `team_died`, …)
  and `param` (for `team` its param, for `playerleft` the reason, for `pause`
  1 or 0).

`players`
: One row per player, then one per AI, in document order (`slot`): `team_id`,
  `ally_team_id`, `player_id` or `ai_id`, `is_ai`, `user_id` (for the join
  with the match dumps), `faction`, `rank`, `skill` (as written, e.g.
  `"[45.67]"`), `skill_uncertainty`, `start_x`, `start_y`, `start_z`, and for
  AIs `ai_short_name` and `ai_version`.

`games`
: One row per replay: `parsed_bytes` (the size of its `.json.zst`, for the
  up-to-date check), `sdfz_bytes`, `parser`, `match_id` (Int64, from
  `serverMatchId`), `game_id`, `engine`, `game`, `map`, `start_time`,
  `duration_ms`, `full_duration_ms`, `winning_ally_teams`, `start_pos_type`,
  `demo_version`, `game_time`, `wallclock_time`, `start_frame`, `end_frame`,
  `ally_teams` (id, player count and start box), `modoptions`, `mapoptions`
  and `restrictions` (lists of `name`/`value`; `tables.options_dict()` turns
  one back into the dict of the JSON) and `unitdefs`.

From these, `Replay.build_orders()` (with `count`, `queued`, `inserted` and
`quota`), `Replay.teams()`, the action counting of `reason8.analysis.apm`
(commands and selections in stream order, ends from `events`) and what the
opening dataset, first contact and the position check take from a replay are
read without the JSON. The tests check them against the JSON on the fixture
and on synthetic replays, and every pass over the parsed replays reads the
tables ([measured below](#passes-over-the-tables)).

Not in the tables:

- **Names** of players, AIs and spectators: they are personal data, and no
  pass needs them.
- **Chat, map drawing, start-position picks and resource shares** (`chat`,
  `mapdraw`, `startpos`, `share`, `setshare`, `aishare`): about 1% of the
  events, used by no pass yet; the final start positions are in `players`. Add
  a table when a pass needs them.
- **`statistics`** (end-of-game team and player counters) and spectators.

## Measurements

### First sample of the slice

The first 100 replays of the first slice in download order
([ADR 0016](../decisions/0016-download-and-store-the-data.md)): 8v8 games on
the three slice maps (34 All That Glitters, 33 Supreme Isthmus, 33 Rosetta)
played between 2026-05-23 and 2026-11-20, on **68 game versions and 6
engines**. They were parsed one at a time (`--jobs 1`) on a WSL2 machine with
32 threads and sdfz-demo-parser 5.15.1.

| Per replay  | Game length | `.sdfz`  | Parser JSON | Ours (JSON) | Ours (gz) | Events  | Time    |
| ----------- | ----------- | -------- | ----------- | ----------- | --------- | ------- | ------- |
| mean        | 26.1 min    | 4.09 MB  | 51.2 MB     | 20.1 MB     | 1.96 MB   | 126,270 | 2.20 s  |
| median      | 23.0 min    | 3.66 MB  | 42.1 MB     | 16.1 MB     | 1.58 MB   | 102,626 | 1.76 s  |
| 90th pctile | 40.6 min    | 6.15 MB  | 80.9 MB     | 32.7 MB     | 3.38 MB   | 206,767 | 3.52 s  |
| max         | 77.8 min    | 17.25 MB | 264.8 MB    | 109.8 MB    | 10.07 MB  | 674,083 | 11.68 s |

| Map (mean)               | Replays | Game length | `.sdfz` | Ours (gz) | Events  | Time   |
| ------------------------ | ------- | ----------- | ------- | --------- | ------- | ------ |
| All That Glitters v2.2.3 | 34      | 25.0 min    | 3.41 MB | 1.37 MB   | 87,760  | 1.57 s |
| Supreme Isthmus v2.1     | 33      | 28.0 min    | 4.07 MB | 1.90 MB   | 129,728 | 2.24 s |
| Rosetta 1.4.4            | 33      | 25.4 min    | 4.80 MB | 2.63 MB   | 162,487 | 2.79 s |

- **Failures: 0 of 100**, on every game version and engine. Per engine:

  | Engine     | Replays | Failed |
  | ---------- | ------- | ------ |
  | 2025.06.19 | 3       | 0      |
  | 2025.06.24 | 30      | 0      |
  | 2026.06.11 | 1       | 0      |
  | 2026.06.12 | 13      | 0      |
  | 2026.07.04 | 52      | 0      |
  | 2026.09.03 | 1       | 0      |

  The 68 game versions (test-30166 to test-32018) have 1 to 4 replays each,
  none failed. The game and engine version in every parsed replay match the
  match dump's.

- Parse time is proportional to the number of events (correlation 0.996), at
  about 17 µs per event. The parser's JSON is 11.7× the `.sdfz` on average,
  ours 4.5× uncompressed and **0.45× gzipped**.

- With `--jobs 8` the same 100 replays take 43 s of wall time (0.43 s per
  replay) when the output is gzipped. These tables were measured with gzip;
  see [Compression](#compression) for the zstd output we write now.

### Compression

Parsed replays are written once and read many times, so they are compressed
with zstd, at level 12 by default (`--zstd-level`). On 20 parsed 8v8 replays:

| Output        | Size vs gzip | Compress per file | Decompress per file |
| ------------- | ------------ | ----------------- | ------------------- |
| gzip level 6  | 100%         | 0.07 s            | 15 ms               |
| zstd level 9  | 87%          | 0.07 s            | 6 ms                |
| zstd level 12 | 85%          | 0.14 s            | 6 ms                |
| zstd level 15 | 82%          | 0.47 s            | 8 ms                |
| zstd level 19 | 69%          | 4.2 s             | 7 ms                |

Long-distance matching with a 128 MB window made no difference at any level,
and several compression threads per file didn't speed up level 19.

Level 19 looked worth it at first, but profiling one replay showed it is three
quarters of the time per replay: 7.9 s of 10.7 s for a median 8v8 game (3.7 MB
`.sdfz`) and 22 s of 29 s for a large one (7.6 MB). The rest is the parser
(0.9 to 1.8 s), reading its JSON (0.6 to 1.5 s), reading the command packets
(0.5 to 1.1 s) and building our document (0.7 to 2.2 s). Level 19 saves about
18% of space over level 12, about 12 GB for the whole slice, and costs about
65 CPU-hours per full parse.

With level 12 and the default `--jobs` (three quarters of the CPU threads, 24
here), 240 replays took 88 s: 164 replays a minute, against 35 a minute at
level 19 with 8 jobs. That is about 4.5 h for the whole slice (42,913
replays), and about 70 GB of parsed JSON (1.64 MB per replay) next to 175 GB
of replays.

### Tables

Two weeks of the slice, the partitions 2026-10-14 to 2026-10-27: 2,830 replays
(1,512 Supreme Isthmus, 1,263 All That Glitters, 55 Rosetta), built with
`reason8 tables --since 2026-10-14 --until 2026-10-28 --jobs 4` on the
32-thread WSL2 machine while it was running headless simulations (load average
40 to 70), so the times are pessimistic.

| Table      | Rows        | Size     | Bytes per row |
| ---------- | ----------- | -------- | ------------- |
| commands   | 359,424,419 | 3,464 MB | 9.6           |
| selections | 8,625,853   | 122 MB   | 14.1          |
| events     | 173,289     | 1.7 MB   | 9.8           |
| players    | 45,280      | 0.9 MB   | 20            |
| games      | 2,830       | 0.7 MB   | 250           |
| all        |             | 3,589 MB |               |

- **Size:** the tables are 82% of the parsed JSON they come from (4,396 MB),
  1.27 MB per replay. Half of the commands table is `params`: map coordinates
  as float32 take about 2.5 bytes each after compression, and storing them as
  integer hundredths or as separate columns saves under 10%. zstd level 9 is
  3% smaller than level 3 and costs nothing measurable when writing.
- **Build time:** 18 min 41 s of wall time, 0.40 s per replay with 4
  processes, and 2.1 s of CPU per replay including Polars' own threads. One
  replay alone on an idle core takes about 0.7 s: 0.3 s to decode the JSON and
  0.4 s to make the rows. A worker peaks at 1.7 GB on the largest replay of
  the sample (9.3 MB of `.json.zst`), most take a few hundred MB. Running it
  again with every day up to date takes 2.4 s.
- **Build orders of the first 8 minutes** of every game of the sample
  (6,227,332 orders): from the tables, 2.4 s to collect
  `build_order_frame(..., until_frame=14400)` as a Polars frame, 53 s when
  each order is also made into a `BuildOrder` object. From the JSON, 1,285 s
  of CPU (0.45 s per replay), 327 s of wall time with 4 processes. The orders
  were **equal for all 2,830 replays**. The frame filter skips row groups:
  counting the BUILD commands takes 1.1 s for whole games and 0.26 s for the
  first 8 minutes.

For the whole slice (about 43k parsed replays), the build is

```sh
uv run reason8 tables --jobs 8
```

At the rate of the sample with 4 processes that is about 4.8 hours; on an
otherwise idle machine with the default 8 processes about 1 to 1.5 hours. The
tables will take about 55 GB next to the 70 GB of JSON.

### Passes over the tables

Every pass over the parsed replays was run on the same two weeks, from the
JSON documents (before) and from the tables (after), on the same loaded
machine (load average 12 to 22 from other work). The outputs are equal: the
dataset's Parquet files row for row and its manifest but for `built_at` and
the code version, the APM and first-contact tables row for row, and the
reports byte for byte. Processes are those of the pass; a pass from the tables
ran with `POLARS_MAX_THREADS=4`. `opening-shift` ran with 20 label shuffles
instead of 1,000, which take more than an hour either way.

| Pass                                 | Before (JSON)      | After (tables)     |
| ------------------------------------ | ------------------ | ------------------ |
| `dataset`                            | 288 s, 4 processes | 14 s, 1 process    |
| `analysis apm`                       | 383 s, 4 processes | 325 s, 3 processes |
| `maps check`                         | 986 s, 1 process   | 4.2 s, 1 process   |
| `analysis map-meta`                  | 1,536 s, 1 process | 311 s, 1 process   |
| `analysis opening-shift --rounds 20` | 5,337 s, 1 process | 4,807 s, 1 process |
| `contact` (12 re-simulated games)    | 8.8 s, 1 process   | 2.4 s, 1 process   |

- `map-meta` and `opening-shift` spend nearly all of their time in the
  measurement itself (classifiers and label shuffles): loading the sample
  takes 6.7 s and 4.1 s from the tables.
- `analysis apm` gains least: putting the commands, selections and events back
  in stream order takes about 0.13 s per replay in Python, and counting the
  actions, which is per event, another 0.15 s. From the JSON a replay took
  about 0.7 s.

### Earlier replays

Seven replays: three 8v8 games on Supreme Isthmus, three 1v1s (Avalanche,
Canis River) and our 1-minute BARb-vs-BARb test game, parsed the same way.

| Replay              | Game       | Length   | `.sdfz` | Parser JSON | Ours (JSON / gz) | Events | Time   |
| ------------------- | ---------- | -------- | ------- | ----------- | ---------------- | ------ | ------ |
| 8v8 Supreme Isthmus | test-32018 | 7.5 min  | 0.89 MB | 7.5 MB      | 1.89 / 0.19 MB   | 12,579 | 0.32 s |
| 8v8 Supreme Isthmus | test-32018 | 14.7 min | 2.39 MB | 26.3 MB     | 8.74 / 0.91 MB   | 56,172 | 1.04 s |
| 8v8 Supreme Isthmus | test-32018 | 25.7 min | 3.05 MB | 36.3 MB     | 11.68 / 1.06 MB  | 76,368 | 1.48 s |
| 1v1 Avalanche       | test-31986 | 14.0 min | 0.27 MB | 1.6 MB      | 0.44 / 0.05 MB   | 2,899  | 0.11 s |
| 1v1 Canis River     | test-31992 | 14.3 min | 0.56 MB | 5.3 MB      | 1.67 / 0.19 MB   | 10,738 | 0.23 s |
| 1v1 Canis River     | test-32018 | 12.9 min | 0.55 MB | 4.5 MB      | 1.21 / 0.13 MB   | 7,561  | 0.20 s |
| BARb vs BARb        | test-32018 | 1 min    | 0.01 MB | 0.1 MB      | 0.02 / 0.004 MB  | 104    | 0.03 s |

- 1v1 games have far fewer events than 8v8 games of the same length: about
  0.1–0.2 MB of gzipped JSON each.
- The parser binary uses 150–400 MB of RAM per process.
- A truncated and a non-gzip file are recorded as errors
  (`unexpected end of file`, `incorrect header check`).
