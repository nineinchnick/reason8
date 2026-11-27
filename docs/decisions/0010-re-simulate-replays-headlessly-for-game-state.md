# 0010. Re-simulate replays headlessly for game state

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

Replays record player commands, not the game state. Learning decisions with
their context ([ADR 0005](0005-learn-decisions-with-their-context.md)),
finding where an opening ends
([ADR 0012](0012-end-openings-at-first-contact.md)) and measuring the bot in
the game ([ADR 0003](0003-define-success-as-in-game-measures.md)) all need to
know what the game looked like: units, positions, resources, wind, who hit
whom. The only source of that is the engine itself: play the replay again and
write the state down while it runs.

[`state-extraction.md`](../research/state-extraction.md) measured this on
engine 2026.09.03 and on older engines:

- The re-run is exact: no desyncs, the recorded winner and length, and
  byte-identical output across runs.
- It needs the exact engine and game version of each replay. A wrong engine
  refuses to load; a wrong game version loads and silently desyncs.
- Cost: a 1v1 replay takes about 40 s of one core, a whole 8v8 replay 7 to 11
  minutes and its first 10 minutes about 65 s; an engine needs 5 to 6 GB of
  RAM, so RAM limits how many run at once.

The next use joins the state with every build order of every player: what
stood on the map and what the team had at that frame, over thousands of games.
Buildings do not move, and the lines for units created, finished, given and
destroyed carry unit, type, team, position and frame, so what stands at any
frame follows from them; rebuilt that way it matches the snapshots of 247 real
games but for units still dying and a few made between two frames
(`state-extraction.md`, section 4). What changes all the time is each team's
resources and the wind. A Lua widget can only write text.

The models after the first one choose what to reclaim, resurrect and assist,
and where ([ADR 0019](0019-first-model-trees-asked-by-every-builder.md)).
Reclaim and resurrection are among the decisions that set experienced players
apart, and a game played again without what they need would have to be played
once more. A spectator widget gets a call-in when a feature (a wreck, heap,
rock or tree) appears or goes and can read its metal and energy, but no
call-in tells what a builder works on: it has to ask each builder
(`state-extraction.md`, section 4).

The bot plays only on what a player could see
([ADR 0008](0008-play-under-human-like-limits.md)), and scouting and contact
need when each team saw which enemy unit. Scouting contacts are often shorter
than a 5-second snapshot. The engine calls a full-view spectator's widget each
time a unit enters or leaves an ally team's sight or radar, once per ally
team; BAR's widget handler passes on only the unit and its team, but the
widget can tell the ally team from the unit's state for each ally team, which
the engine changes right before each call. And what each unit type can build
and do is what the game makes of its unit files when it loads them, which the
files alone do not show.

## Decision

Recover game state by re-running each replay in `spring-headless` with a
spectator widget that writes JSON lines
(`reason8/headless/widgets/reason8_state_export.lua`), and convert them to
Parquet tables right after the run.

The widget writes (format 7):

- every second, each team's resources and the wind;
- every 5 seconds, a snapshot of the units that can move or are still being
  built, with position, health and build progress. Finished buildings are left
  out: where they stand and who owns them follows from the unit lines. Only
  their health is lost, which matters in fights after the opening and is not
  needed to know what a team had built; the `hit` and `damage` lines still say
  when and how hard buildings were attacked;
- a line per unit created, finished, destroyed, given and gone idle, the first
  hit of each unit by each enemy team, and damage per second between teams;
- a line per reclaimable feature when it appears (the map's own at the start)
  and when it goes, with its metal and energy, and the feature a resurrected
  unit came from;
- what every builder that is not a factory works on (build, repair, reclaim,
  resurrect, capture, restore), asked every 5 frames and written when it
  changes;
- the metal and energy each team reclaimed from each feature;
- a line each time an enemy unit enters or leaves an ally team's sight or
  radar, with where it was (a unit in sight is on radar too, as the engine
  counts it);
- in the header, every unit type as the game loaded it: build power, build
  options and whether it can move, assist, repair, reclaim and resurrect.

Everything comes from call-ins except builders' work, the only sampled part.

Resource and snapshot lines are written at the end of their frame, so a line
of frame F shows the world after the unit lines up to F.

`reason8 headless batch` and the evaluation games convert each state file into
ten Parquet tables next to it (`game`, `resources`, `events`, `units`, `hits`,
`damage`, `features`, `reclaim`, `work`, `visibility`;
`reason8/headless/tables.py`): one file per game and table, in the date
partition of the replay ([ADR 0016](0016-download-and-store-the-data.md)),
zstd-compressed, with 16-bit and 32-bit integers, 32-bit floats and
dictionary-encoded unit types. `reason8 headless tables` converts state files
written before; their resources come at the snapshot interval (5 s), games
before format 6 have empty feature, reclaim and work tables, and games before
format 7 an empty visibility table and no loaded unit types. Readers use
`tables.scan()` (lazy Polars frames by date range),
`standing.standing_units()` (what stands at a frame) or
`state.read_records()`, which reads every format, from JSON lines or tables,
as the same records.

The JSON lines are kept next to the tables: they are what the engine wrote,
and when the table layout changes they are converted again in a second, while
writing them again means playing the game again (a core-minute and 6 GB of RAM
per 8v8 opening). They are 40% bigger than the tables.

- **1v1:** re-run whole games.
- **8v8:** stop at the part being learned (`--max-frame`); the openings need
  the first 10 to 12 minutes.

Every run fetches the engine, game version and map named in the replay's
header, uses one engine per replay with one worker thread, its own write dir
and a free port, and is rejected on any desync warning, non-zero exit code or
timeout.

## Consequences

- We have to keep several engines and many game versions on disk (about 0.4 GB
  for the top three engines of the first slice, a few GB of game versions).
- Throughput is bounded by RAM, not cores. The first 12 minutes of the 43k
  games of the slice would take about two weeks on one machine, so games are
  re-simulated as a growing sample, and whole games in bulk wait for a cloud
  cluster ([ADR 0016](0016-download-and-store-the-data.md)).
- Ten small files per game: tens of thousands of files for a sample of
  thousands of games. If that gets slow to list or sync, the tables of a day
  can be merged into one file per table later, without touching the widget.
- The state is the spectator's full view. Training on the openings uses only
  the state of the player's own team and its allies, which a player sees
  anyway
  ([ADR 0018](0018-learn-from-orders-joined-with-the-state-before-them.md)).
  From format 7 the `visibility` table says which enemy units each ally team
  had in sight or on radar at any frame, so enemy units can be used as a
  player saw them ([ADR 0008](0008-play-under-human-like-limits.md)). The
  games played in formats 5 and 6 do not have it: they have to be played again
  for it, and nothing else in their state can stand in for it.
- `reason8 headless tables --check` checks the sight and radar lines. On five
  8v8 openings every enter has its leave, death or the end, sight is always
  within radar, and of the units an enemy hit first or destroyed, 81% and 92%
  were in its sight and 15% and 6% on its radar only. They cost the widget
  0.07 s per game, under 0.1% of the simulation, and add 15% to the tables: 37
  to 77 KB of visibility rows and 5 KB of loaded unit types per 8v8 opening
  (`state-extraction.md`).
- The unit types as loaded differ from the unit files as `reason8` reads them:
  per game a third of the types with build power come from files that build
  their units with code (commander levels, drones), the units a lobby leaves
  out (Legion, the bosses) are not loaded at all, and 5 to 20 build lists
  change. They are the game's own values, with that lobby's options applied,
  and the decision table can switch to them for games of format 7.
- The format has room for other additions as lines and tables of their own:
  unit command queues (writing every builder's and factory's queue when it
  changes would add a third to the tables and double the widget's time,
  `state-extraction.md`), and static map data (metal spots).
- Which builder reclaimed how much of a feature, and who assisted a build, is
  known to within the 5-frame sampling of builders' work. What each team
  reclaimed matches the game's own count within a quarter percent; between
  allies on the same feature the split is approximate. It costs half a second
  of the widget's time and a quarter more table bytes per game
  (`state-extraction.md`). The games played in format 5 have none of it, and
  only the features a map starts with can be added to them without playing
  them again.
- Revisit if a replay stops re-simulating exactly, or if per-replay cost makes
  the needed part of 8v8 games too expensive even in the cloud.
