# Recovering game state by re-running replays

A replay records **commands**, not the world. To know what the game looked
like at minute 7 (units, positions, resources) we have to run the replay
through the engine again and write the state down while it plays. This
document measures how well that works.

## Summary

**Go.** Re-running replays in a headless engine works, is exact, and is cheap
enough for 1v1 games. Big team games cost about 12 times more per replay and
need a budget.

Faster than real time?
: Yes. 1v1 replay: 48x on average. 8v8 replay: 3.8x on average (23x at the
  start, 1.8x at minute 25)

State snapshots from a spectator widget?
: Yes. Resources and wind every second; units, positions, health and build
  progress every 5 s; an event for every unit created / finished / destroyed /
  given / gone idle and for every first hit between two enemy units; every
  reclaimable feature as it appears and goes, the metal and energy each team
  reclaimed from it, what each builder works on, sampled every 5 frames, each
  time an enemy unit enters or leaves an ally team's sight or radar, and the
  unit types as the game loaded them (section 4). Converted to Parquet tables
  after the run

What each team saw?
: Yes, exactly, from the engine's call-ins: on five 8v8 openings every enter
  has its leave, death or the end, and 81% of the units an enemy hit first
  were in its sight, 15% on its radar only

Reclaim right?
: Yes, against the game's own count where the game version keeps one: within
  0.05% and 0.24% of the metal reclaimed; between allies sharing a feature up
  to 2% of a team's reclaim is split differently

What stands at any frame?
: Rebuilt from the unit events alone; it matches the snapshots of real games
  but for units still dying and the odd unit made between two frames (section
  4\)

Is the re-run the same game?
: Yes. 0 desync warnings, same winner and length as recorded, byte-identical
  output across runs

Disk per game (snapshot every 5 s, gzip)
: 1v1 (13 min): 86 KB. 8v8 (26 min): 6.0 MB (format 1). First 10 minutes of an
  8v8 in format 5: 39 KB of gzipped JSON lines and 28 KB of Parquet tables per
  game minute; format 6 adds 42% and 26% to them, format 7 another 28% and 15%

Replays per hour per core
: 1v1: 80 to 100. 8v8: 5 to 8

RAM per engine
: 4.7 GB (1v1) to 5.7 GB (8v8). RAM, not CPU, limits how many engines fit on a
  machine

CPU per engine
: 1 core (with `WorkerThreadCount = 1`, which is also the fastest setting per
  core)

Wrong engine version
: Refuses to start. If forced, it plays but desyncs and gives a wrong result

Wrong game version
: Never an error. It plays, desyncs and silently writes wrong state

Getting the right versions
: All automatic from the replay header: engine from GitHub, game and map with
  `pr-downloader`

## How it works

```
replay.sdfz
  └─► spring-headless (same engine, game version and map as recorded)
        └─ widget: reason8_state_export.lua
           (spectator: sees everything, gives no orders)
              └─► reason8_state.jsonl (one line per snapshot or event)
```

The idea comes from Apex (`apexearth/bar-ai`: `tools/replay_extract.py` and
`barai_replay_export.lua`). Apex's widget logs events (builds, deaths, damage,
resource waste) to the engine log. Ours adds full snapshots, writes to its own
file, and does not write player names. We ran Apex's widget too, unchanged, on
the same 1v1 replay: it works on the current game, costs the same time, and
wrote 949 event lines (134 KB, 24 KB gzipped).

### Tools

All in `reason8/headless/`, run as `reason8 headless <command>`. Paths are
arguments; nothing is committed from `data/`.

`setup`
: Downloads engine, game version and map into one data dir. `--replay X.sdfz`
  fetches what X needs

`run`
: Runs a start script or plays a replay in its own write dir; prints time,
  speed, memory, desyncs

`batch`
: Plays many replays, several engines at once: fetches what each needs, keeps
  the state as `date=<day>/<replay name>.jsonl.gz` with its Parquet tables
  next to it, skips the ones already done

`state`
: Reads a state file; prints sizes and counts, and the first finished builds
  per team

`tables`
: Converts state files to Parquet tables (`tables.py`); with `--check`
  compares the units rebuilt from the events with every snapshot
  (`standing.py`) and checks features, reclaim and work (`features.py`) and
  sight and radar (`visibility.py`)

`widgets/reason8_state_export.lua`
: The widget that writes the state file

`startscripts/barb_vs_barb.txt`
: BARb vs BARb start script template

`reason8 header` (in `reason8/replays/sdfz.py`) reads a replay's header:
engine version, game version, map, length.

```sh
# fetch what a replay needs (engine, game version, map)
uv run reason8 headless setup --data-dir data/bar \
    --replay data/replays/date=D/X.sdfz
# play it and keep the state
uv run reason8 headless run --data-dir data/bar --threads 1 --snapshots \
    --out X.jsonl data/replays/date=D/X.sdfz
uv run reason8 headless state X.jsonl --builds
# tables for the state files of a date range (those written before, too)
uv run reason8 headless tables --state-dir data/state --since 2026-11-01
# the first 12 game minutes of many replays, 4 engines at once
uv run reason8 headless batch --data-dir data/bar --out-dir data/state \
    --jobs 4 --max-frame 21600 data/replays/date=D/A.sdfz data/replays/date=D/B.sdfz

# an AI vs AI game at full speed, 10 game minutes
uv run reason8 headless run --data-dir data/bar --threads 1 \
    --var "MAP=Supreme Isthmus v2.1" \
    --var "GAME=Beyond All Reason test-32018-ad135b9" \
    --var SEED=1 --var FRAMES=18000 \
    reason8/headless/startscripts/barb_vs_barb.txt
```

`reason8 headless run` exits non-zero when the engine fails, times out, or
reports a desync.

## Test setup

- Machine: Intel i9-13900F (8 fast + 16 slow cores, 32 threads), 31 GB RAM,
  Linux under WSL2. Other engines on the same machine slow a run down by up to
  60% (section 5), so the "alone" numbers were taken with no other engine
  running, unless noted.
- Engine: prebuilt Recoil releases from GitHub (`spring-headless`), mainly
  2026.09.03.
- Replays: 6 public human replays (three 1v1, three 8v8) from November,
  September and June 2026, on engines 2026.09.03, 2026.09.02, 2026.07.04 and
  2025.06.24.
- How measured: wall time with a monotonic clock around the engine process;
  CPU time and peak memory from `wait4` (what the kernel charged the process);
  frames and load time from the timestamps in the engine log. "Speed" is game
  time divided by simulation wall time, without loading. All of it is printed
  by `reason8 headless run`.

## 1. Running faster than real time

By default a headless game runs at real time: 1,800 frames (1 game minute)
took 60 s.

These settings change that:

AI vs AI game (a start script)
: `MinSpeed=100; MaxSpeed=100;` in `[MODOPTIONS]`. The server then starts at
  speed 100

Replay
: The replay's own script wins, so a widget sends `setmaxspeed 100` and
  `setminspeed 100`

Both
: `WorkerThreadCount = 1` in `springsettings.cfg`

Speed 100 is only a cap; the engine runs as fast as the CPU allows.

The thread setting matters more than expected. By default the engine starts 16
worker threads here. They mostly wait for each other. BARb vs BARb, Supreme
Isthmus, 10 game minutes, speed 100:

| WorkerThreadCount | Simulation time | Speed | Cores used | Peak RAM |
| ----------------- | --------------- | ----- | ---------- | -------- |
| default (16)      | 58.3 s          | 10x   | 3.0        | 5.7 GB   |
| 8                 | 25.7 s          | 23x   | 2.1        | 5.6 GB   |
| 4                 | 16.4 s          | 37x   | 1.8        | 5.5 GB   |
| 2                 | 14.6 s          | 41x   | 1.5        | 5.5 GB   |
| 1                 | 13.6 s          | 44x   | 1.1        | 5.4 GB   |

One thread is 4 times faster than the default and uses a third of the CPU. In
a big game more threads help a little, at double the CPU: the 8v8 replay below
took 402 s with 1 thread (1.0 core) and 325 s with 4 threads (2.0 cores).
**Use 1 thread per engine and run more engines.**

Loading is not affected by the speed setting: 16 to 21 s per run with 1 thread
(10 s with 16 threads).

## 2. Playing back human replays

All with 1 thread, speed 100, snapshots every 5 s. Players are not named here
on purpose.

| Replay               | Engine     | Game length | Load | Simulation | Speed | Wall  | Peak RAM | Most units | Desyncs |
| -------------------- | ---------- | ----------- | ---- | ---------- | ----- | ----- | -------- | ---------- | ------- |
| 1v1, Canis River     | 2026.09.03 | 12.9 min    | 17 s | 16 s       | 48x   | 37 s  | 4.7 GB   | 336        | 0       |
| 1v1, Canis River     | 2026.09.03 | 14.3 min    | 17 s | 20 s       | 43x   | 40 s  | 4.7 GB   | 309        | 0       |
| 1v1, Avalanche       | 2026.09.02 | 14.0 min    | 14 s | 13 s       | 67x   | 30 s  | 4.5 GB   | 140        | 0       |
| 8v8, Supreme Isthmus | 2026.09.03 | 25.7 min    | 21 s | 402 s      | 3.8x  | 427 s | 5.7 GB   | 4,735      | 0       |
| 8v8, Supreme Isthmus | 2026.07.04 | 21.1 min    | 37 s | 270 s      | 4.7x  | 311 s | 6.1 GB   | 3,035      | 0       |
| 8v8, Supreme Isthmus | 2025.06.24 | 20.7 min    | 45 s | 312 s      | 4.0x  | 361 s | 5.7 GB   | 3,263      | 0       |

The last two rows ran next to other engines, so they are somewhat slower than
they would be alone (see section 5).

Speed drops as the game fills with units. Game minutes per wall minute, in
5-minute steps:

| Game minutes | 1v1 (336 units at most) | 8v8 (4,735 units at most) |
| ------------ | ----------------------- | ------------------------- |
| 0 to 5       | 78x                     | 23x                       |
| 5 to 10      | 49x                     | 9.5x                      |
| 10 to 15     | 31x                     | 4.7x                      |
| 15 to 20     |                         | 2.8x                      |
| 20 to 25     |                         | 1.8x                      |

So the first 10 minutes of an 8v8 cost 44 s of simulation, and the last 5
minutes cost 165 s. A 40-minute 8v8 will run close to real time at the end. If
only openings matter, stop early with `--max-frame`.

BAR's own 250 UI widgets also load in headless mode. Switching them all off
made the 1v1 16% faster (16.3 s to 13.7 s) and made no clear difference for
the 8v8. Not worth the trouble.

### Is the re-run really the same game?

Three checks, all passed:

1. **The engine's own check.** While a replay plays, the engine compares its
   state checksum with the checksums the original players sent, every 60
   frames, and logs `[DESYNC WARNING]` on a mismatch. Every correct run had 0
   warnings; every wrong-version run below had hundreds.
   `reason8 headless run` counts them and fails the run.
2. **Same result as recorded.** For all six replays the winning side matches
   the public replay API (`api.bar-rts.com/replays/<id>`), and the game-over
   frame is within 1 second of the API's duration.
3. **Deterministic.** The state file of the same replay is byte-identical
   across runs, with 1 or 4 threads, and with BAR's widgets on or off.

## 3. Version matching

Replay from engine 2026.09.02 on engine 2026.09.03
: Exit code 21 in under 1 s:
  `demo-file ... corrupt or created by a different Spring version, expected "2026.09.02"`

Same, forced with `DisableDemoVersionCheck = 1`
: Plays. First desync at frame 4,020 (2.2 min), 414 warnings. "Ends" at 9.1
  min with the **wrong winner** (real: 14.0 min)

Same replay on engine 2026.09.02
: Correct: 0 desyncs, right winner, right length

Game version 2 days newer than the replay's
: No error, exit code 0. First desync at frame 3,660 (2.0 min), 2,582
  warnings, different unit counts

Game version 2 months older than the replay's
: No error, exit code 0. Desync from frame 0; almost nothing gets built (3
  units at most, real: 309)

Game version not installed
: Exit code 21:
  `Dependent archive "beyond all reason test-31992-e7a6cff" ... not found`

Map not installed
: Exit code 21: `Dependent archive "canis river v1.4" ... not found`

Notes on the game version tests: the engine takes the game name from the
replay itself, so the wrong version cannot be loaded by accident. To test it
we rewrote the name inside a copy of the replay. Editing only the header's
script has no effect; the name the engine uses is in the first packet of the
command stream.

**Verdict: confirmed. A replay only plays back correctly on the exact engine
version and exact game version it was recorded on.** Even a patch release of
the engine (2026.09.02 to 2026.09.03) and a game version 2 days apart desync
within about 2 minutes. A wrong engine is caught by the engine. A wrong game
version is not: the only sign is the desync warnings, so the pipeline must
treat any desync as a failed replay.

One more trap: in older game versions (seen with one from June 2026; one from
September 2026 was fine) a new user widget is not switched on by itself in a
replay, even with `enabled = true`. Without the widget nothing sets the speed,
and the replay runs at real time, writing nothing. `reason8 headless run`
therefore writes `LuaUI/Config/BYAR.lua` with the widget switched on.

## 4. State snapshots

The widget (`reason8/headless/widgets/reason8_state_export.lua`) is unsynced,
watches as a full-view spectator, and writes JSON lines to
`LuaUI/Config/reason8_state.jsonl` in the run's write dir. That folder is one
of the two that BAR allows a user widget to write to.

Format 7 (the `v` of the header) writes these lines:

`header`
: *When:* once
: *Content:* game, map, engine, map size, the map's wind range and tidal
  strength, teams (number, ally team, AI or not, side), unit type id to name,
  the types that cannot move (`static`), the types whose work is sampled
  (`builders`), how often resource, snapshot and work lines come, whether
  sight and radar are written, and every unit type as the game loaded it
  (`loaded`: build power, the types it can build, and whether it can move,
  assist, repair, reclaim and resurrect)

`r`
: *When:* every second (30 frames)
: *Content:* the wind strength at that moment; per team: metal and energy
  (stored, storage, income, expense)

`s`
: *When:* every 5 game seconds
: *Content:* per unit that can move or is still being built: id, type, team,
  x, z, health %, build %. Finished buildings and units that are dying are
  left out

`created`
: *When:* unit placed
: *Content:* frame, unit, type, team, position, builder; for a resurrected
  unit the feature it came from

`finished`
: *When:* unit completed
: *Content:* frame, unit, type, team, position

`destroyed`
: *When:* unit died
: *Content:* frame, unit, type, team, position, whether it was finished,
  attacker's team, the attacking unit, the engine's weapon number (negative:
  no weapon, such as a crash) and whether the attacker reclaimed it

`given`
: *When:* unit changed team
: *Content:* frame, unit, type, new team, old team

`idle`
: *When:* a factory or builder ran out of orders
: *Content:* frame, unit, type, team, position

`hit`
: *When:* a unit is damaged by a given enemy team for the first time
: *Content:* frame, unit, type, team, position, the attacking unit, its type
  and team, the damage

`damage`
: *When:* every second in which one team damaged units of an enemy team
: *Content:* frame, damaged team, attacking team, number of hits, damage

`fdef`
: *When:* before the first feature of a type
: *Content:* feature type id, name, metal, energy, reclaim time

`fcreated`
: *When:* a feature with metal or energy appears; the map's own when the
  widget starts
: *Content:* frame, feature, type, position, metal, energy, for a wreck the
  unit type it can be resurrected as

`fdestroyed`
: *When:* such a feature goes
: *Content:* frame, feature, metal and energy left, reclaim left (0: reclaimed
  away)

`reclaim`
: *When:* a team stops reclaiming a feature, the feature goes, or the game
  ends
: *Content:* frame, feature, team, first frame, metal and energy taken

`work`
: *When:* every 5 frames, for each builder whose work changed
: *Content:* frame, builder, team, task (build, repair, reclaim, resurrect,
  capture, restore, none), the unit or feature worked on

`los`, `radar`
: *When:* an enemy unit enters or leaves an ally team's sight or radar
: *Content:* frame, unit, the ally team, in or out, position

`end`
: *When:* game over or last frame
: *Content:* frame, reason, winning ally teams, how the attackers were told
  (below), when in the frame resources and snapshots were taken, each team's
  reclaim as the game counts it (only newer game versions count it: seen in
  `test-31836` and `test-32018`, not in `test-30903` or older), and how many
  sight and radar call-ins the widget could not put down to one ally team

Resource and snapshot lines are written in `GameFramePost`, after everything
the frame did, so a line of frame F shows the world after the unit lines up to
frame F (`"sampled":"frame_end"`). An engine without that call-in gets them at
the start of the frame (`"frame_start"`); every engine we use has it.

Format 6 had the same lines without sight and radar and the new fields of the
header and `end`. Format 5 had them without the features, reclaim and work and
the new fields of `created`, `destroyed`, the header and `end`. Up to format 4
the snapshot held the wind and the resources too, listed every unit, and was
written in `GameFrame`, at the start of its frame (formats 2 to 4 add the
`hit` and `damage` lines and the wind, the exact attacker, and `idle`).
`read_records()` in `state.py` reads every format the same way: the snapshots
of format 5 come back whole, with the wind and resources of the same frame and
the finished buildings rebuilt from the unit lines (health unknown).

The `finished` lines are the **finished builds** that the opening model needs:
what was actually built and when, not just what was ordered.
`reason8 headless state --builds` prints them per team.

Unit type ids change between game versions, which is why every file carries
its own id-to-name table.

The `hit` and `damage` lines are what [`first-contact.md`](first-contact.md)
is measured from. BAR's widget handler passes a widget only the first five
arguments of `UnitDamaged` (unit, type, team, damage, paralyzer), not the
attacker, so the widget asks the engine instead: `Spring.GetUnitLastAttacker`
returns the unit that last damaged a unit, in every game version and without
access to the handler (`"attackers":"last_attacker"` in the `end` line).
Damage with no attacker (wreckage, fire, terrain) is left out.

Checked on two Supreme Isthmus 8v8 replays, first 6 game minutes:

- `test-30868`, where a widget can still wrap the handler and read the real
  attacker: `GetUnitLastAttacker` named the same unit in 1,457 of 1,497 damage
  events (97.3%). In the other 40 it named an earlier attacker of the same
  unit, or none; the function doesn't say when the attack happened, so a hit
  without an attacker of its own can be put down to the previous one. A unit's
  first hit, which is what first contact uses, is not affected.
- `test-31986`, where the handler is closed to user widgets: the call-in gave
  no attacker in any of 400 damage events, and `GetUnitLastAttacker` gave one,
  always an enemy unit, in 394.

Older state files (format 2) used two other ways: wrapping the handler
(`"attackers":"attacker"`, exact) and, in game versions from `test-31820`
where that is no longer allowed, the nearest enemy unit within 1,300 map units
(`"attackers":"nearest"`, a guess). How well the guess agrees with the real
attacker is measured in [`first-contact.md`](first-contact.md).

### Size per game

| Snapshot every | 1v1, 12.9 min, raw | gzip   | 8v8, 25.7 min, raw | gzip   |
| -------------- | ------------------ | ------ | ------------------ | ------ |
| 1 s            | 3.8 MB             | 293 KB |                    |        |
| 5 s            | 853 KB             | 86 KB  | 23.2 MB            | 6.0 MB |
| 10 s           | 486 KB             | 57 KB  | 12.3 MB            | 3.1 MB |
| 30 s           | 239 KB             | 35 KB  | 5.1 MB             | 1.2 MB |
| 60 s           | 177 KB             | 29 KB  | 3.3 MB             | 0.7 MB |
| events only    | 114 KB             | 18 KB  | 1.5 MB             | 0.2 MB |

The 1 s and 5 s rows are measured runs; 10 s to 60 s are the 5 s file with
snapshots dropped. For comparison the replays themselves are 0.55 MB (1v1) and
3.1 MB (8v8).

Snapshots cost little time: the 1v1 took about 15 s without them, 16.3 s at 5
s and 19.1 s at 1 s.

At 5 s, 100,000 duels need about 9 GB gzipped, and 43,000 8v8 games about 260
GB. For 8v8 a 30 s interval (50 GB) or a binary format is the better choice.
The 8v8 file has 669,214 unit rows; packed at 16 bytes per row that is 10.7 MB
before compression.

The sizes in the table were measured before the `hit` and `damage` lines and
the wind were added. The first 12 minutes of an 8v8 game, with snapshots every
5 s, are 3.6 to 4.2 MB raw and 0.8 to 0.9 MB gzipped.

### Format 5 and the tables

The state is joined with every build order of every player: what stood on the
map and what the team had at that frame. Two things changed for that in format
5\. Resources and wind, which change all the time and are small, come every
second. Finished buildings, which do not move, are left out of the snapshots:
in format 4 they were 62% to 67% of the snapshot rows of 8v8 games (six games
measured), and what stands follows from the unit lines (below). Their health
is the only thing lost; the `hit` and `damage` lines still say when and how
hard they were attacked.

A Lua widget can only write text, so the JSON lines are converted to Parquet
tables after the run (`reason8 headless tables`, run by `batch` and the
evaluation games). A state file `<name>.jsonl.gz` gets one file per table next
to it, `<name>.<table>.parquet`, in the date partition of the replay:

`game`
: one row: format, versions, map, wind range, intervals, teams, unit types
  (with `static`, and from format 7 as loaded: build power, build options,
  what they can do), last frame, how the game ended

`resources`
: per team and resource line: metal and energy (stored, storage, income,
  expense), wind. Sorted by team and frame

`events`
: units created (with builder), finished, destroyed (finished or not, by which
  team), given (from which team), gone idle; with position. In the order the
  engine reported them

`units`
: snapshot units with position, health and build progress. Sorted by unit and
  frame

`hits`
: first hit of a unit by each enemy team, with the attacker

`damage`
: hits and damage per damaged and attacking team, per second

`features` (format 6)
: one row per reclaimable feature: type, position, metal and energy when it
  appeared, resurrect type, when it went, what it had left and how it went
  (reclaimed, resurrected, destroyed)

`reclaim` (format 6)
: metal and energy per feature, team and stretch of reclaiming it

`work` (format 6)
: builders' work changes. Sorted by builder and frame

`visibility` (format 7)
: an enemy unit entering or leaving an ally team's sight or radar, with
  position. Sorted by unit and frame

Unit types are names, dictionary-encoded, so tables of different game versions
can be read together; teams are 16-bit, frames, ids and positions 32-bit
integers, money and damage 32-bit floats; zstd level 19. Sorting the units by
unit and frame instead of frame and unit makes that table a quarter smaller (a
unit's rows repeat each other's values), and level 19 instead of 9 makes all
tables 13% smaller; writing a game's tables takes 0.07 s. `tables.scan()`
reads one table of many games as a lazy Polars frame, by date range;
`read_records()` reads a game's tables as if they were its JSON lines (with
the units of a snapshot sorted by id). Games written before format 6 have no
`features`, `reclaim` and `work` files and fewer `events` columns, those
before format 7 no `visibility` file and fewer `game` columns and unit type
fields; `tables.scan()` and `tables.read_game()` read them with the full
schema, as empty tables and null columns.

Size of the first 10 minutes of the same 8v8 replay (Rosetta, 16 players,
engine 2026.09.03), per game minute:

| Format                                  | JSON raw | JSON gzip | Tables |
| --------------------------------------- | -------- | --------- | ------ |
| 4: resources and all units every 5 s    | 263 KB   | 43 KB     | 24 KB  |
| 5: resources every 1 s, units every 5 s | 186 KB   | 39 KB     | 28 KB  |

Of the format 5 tables, per game minute: units 12.6 KB, resources 7.4 KB,
events 4.2 KB, hits 1.3 KB, damage 1.0 KB and the game row 1.2 KB (most of it
the 500 unit type names). The resource lines are 434 KB of the 1.86 MB of JSON
lines, the snapshots 865 KB (2.07 MB in format 4).

The JSON lines stay next to the tables: they are what the engine wrote, they
are converted again in a fraction of a second when the layout changes, and
writing them again means playing the game again. They are 40% bigger than the
tables. The 152 state files written before format 5 (formats 2 and 4, 108 MB
gzipped, 22 measured: 62 KB per game minute) give 46 KB of tables per game
minute, with every unit in the snapshots and resources every 5 s, in 0.3 to
0.5 s per file.

The widget's cost did not change. Measured on the same replay and the same
first 10 minutes, with a copy of each widget that adds up the time spent in
its own call-ins (`Spring.GetTimer`): 0.413 s in format 4 and 0.415 s in
format 5, of 150 to 200 s of simulation. The wall times of the runs themselves
(155 to 205 s of simulation for either format) were set by the 8 other engines
running on the machine at the time, not by the widget. Each format's file was
byte-identical across two runs, under different load.

### What stands, from the events

`standing.standing_units()` rebuilds the units of every team at any frame from
the `events` table: the last `created` line of each unit id (ids are used
again), less those `destroyed` after it, finished if a `finished` line
follows, owned by the team of the last `given` line. The position is where the
unit was created: where a building stands, and for a unit that can move the
factory or builder that made it.

`reason8 headless tables --check` compares that with every snapshot of a game:
the same units, of the same type and team, finished or not, and for units that
cannot move at the same place.

Results, on every state file there was (186 replays: 72 of format 2, 114 of
format 4; 24,174 snapshots, 15.7 million unit rows) and on every fifth
evaluation game (61 AI games of format 3; 6,283 snapshots, 3.0 million unit
rows), comparing a snapshot with the units after the previous frame, and the
last snapshot of a game over or shutdown with the units after its own frame:

Units still dying
: 5,624 rows (0.03%), in every game. A unit that was destroyed stays in the
  engine's unit list while its death animation plays (up to 50 frames seen),
  so the snapshot still has it. Format 5 leaves dying units out of snapshots

Units made by the game at the start of the frame
: 19 rows in 11 replays, all `legdrone`: drones that Legion units launch from
  the game's scripts. Those run before the widget's `GameFrame`, so a format 4
  snapshot already has the drones that the rebuilt units only get after the
  frame

A unit reported destroyed before it was created
: 3 rows, one unit (a `corak` in one replay): its `destroyed` line came before
  its `created` line in the same frame, so it is rebuilt as standing until the
  end. Not seen anywhere else

There were no differences of type, team, being finished or position.

On the format 5 run of the replay above (121 snapshots, 27,551 unit rows) the
snapshot at the end of the frame and the units rebuilt after the same frame
differ in one row: a lab whose `created` line has the snapshot's frame but
came after the snapshot, between two frames. Frame numbers alone cannot tell
it apart. Everything else matches, including units given, units destroyed
before they were finished, and the commanders created by the game at the
start.

### Features, reclaim and builders' work (format 6)

The next models choose what to reclaim, resurrect and assist. Reclaim and
resurrection are among the decisions that set experienced players apart, so
format 6 records what a spectator widget can read of them. What each item
comes from, read in the engine's Lua API (Recoil 2026.09.03 source) and BAR's
widget handler, and checked on every engine we use (2025.06.19 to 2026.09.03):

Features the map starts with
: *Exact.* `Spring.GetAllFeatures()` when the widget starts: type, position,
  metal and energy (`GetFeatureResources`). Only features with metal or energy
  that can be reclaimed are written

Features that appear (wrecks, heaps, gadget-made ones)
: *Exact.* `FeatureCreated` call-in, with the same fields and, for a wreck,
  the unit type it can be resurrected as (`GetFeatureResurrect`)

Features that go, and how
: *Exact.* `FeatureDestroyed` runs in the feature handler's update, after the
  units of the frame and before the feature is freed, so its metal, energy and
  reclaim progress can still be read: reclaim progress 0 means it was
  reclaimed away. A resurrected one is named by the unit made from it (below);
  every other one was blown up, crushed or burnt

Which unit a wreck came from
: *Not given.* The call-in has only the feature and its ally team. Matched in
  the check by type and position against the deaths of the 300 frames before:
  682 of 683 wrecks in five games

Metal and energy reclaimed, per feature and team
: *Exact per feature, sampled between teams.* The engine has no reclaim
  call-in for widgets (`AllowFeatureBuildStep` is synced only) and no reclaim
  figure in the team statistics. The widget reads, at every work sample, what
  each feature being reclaimed has left, and gives what it lost to the teams
  whose builders work on it, split by their reclaim speed. What a feature had
  left when reclaimed away goes to the builders still pointing at it in that
  frame (`GetUnitWorkerTask` in `FeatureDestroyed`), which is exact. A loss
  without reclaim progress or without a builder on the feature is not reclaim:
  BAR's tree feller takes the energy of trees that explosions fell

What every builder works on
: *Sampled* (every 5 frames). `Spring.GetUnitWorkerTask` tells what a builder
  is doing, not what it was ordered to: building (with the unit; assisting
  when someone else started it), repairing, reclaiming a unit or feature,
  resurrecting, capturing, restoring ground. No call-in tells when it changes.
  Factories are left out: what they make is in the unit lines

Builder of a unit
: *Exact,* as before (`UnitCreated`), now with the feature for a resurrected
  unit: while the unit is made, its resurrector still points at the feature

Units reclaimed
: *Exact.* `UnitDestroyed` gives the attacker, which for a reclaimed unit is
  the builder still pointing at it. The metal it gives back is not written; it
  follows from the unit's cost and build progress

Orders to builders (command queues)
: *Not recorded.* The orders are in the replay itself; the `UnitCommand`
  call-in could write them too

#### Checks on real games

`reason8 headless tables --check` checks the units against the snapshots and,
from format 6, the features, reclaim and work (`features.py`). Five 8v8 games
of the context sample, first 10 minutes, three maps, engines 2025.06.24 to
2026.09.03:

| Game                          | Features | At start | Reclaimed | Resurrected | Work lines | Built by builders, seen building |
| ----------------------------- | -------- | -------- | --------- | ----------- | ---------- | -------------------------------- |
| Supreme Isthmus, 2026.07.04   | 2,914    | 2,638    | 1,708     | 15          | 10,335     | 757 of 758                       |
| All That Glitters, 2026.07.04 | 330      | 158      | 240       | 1           | 7,571      | 1,114 of 1,115                   |
| Supreme Isthmus, 2025.06.24   | 2,918    | 2,638    | 1,814     | 0           | 10,795     | 918 of 918                       |
| Rosetta, 2026.06.12           | 459      | 132      | 334       | 7           | 8,943      | 664 of 664                       |
| Supreme Isthmus, 2026.09.03   | 2,801    | 2,638    | 1,783     | 1           | 9,344      | 818 of 818                       |

- **Reclaim against the game's count.** Newer game versions count each team's
  reclaim themselves, in a synced gadget that sees every reclaim step, and
  leave it in team rules params; the widget writes them in its `end` line. Two
  of the five games have them. Supreme Isthmus on 2026.07.04: 15,083.7 metal
  and 296,214 energy reclaimed against the game's 15,076.3 and 296,193; no
  team differs by more than 3 metal and 148 energy. On 2026.09.03: 14,177
  metal against 14,143 (0.24%) and 307,987 energy against 307,469; per team up
  to 32 metal (2.2% of a team's reclaim) and 752 energy (1.3%) move between
  allies. Those games had 82 and 43 features reclaimed by more than one team,
  all but one by allies; the split between them by reclaim speed at the
  samples is where the difference comes from, the totals hold. The game
  credits a step at the next step on the feature, a frame later, which
  explains the few metal left over at the last frame.
- **Reclaim against the features.** Every feature reclaimed away (5,879) was
  credited exactly its metal and energy; no other feature was credited more
  than it lost.
- **Wrecks and deaths.** 682 of 683 wrecks match a death of their unit type
  within 64 map units in the 300 frames before. 665 features were destroyed
  otherwise; 306 of them left a feature in their place in the same frame (a
  wreck blown up into a heap, a tree into a falling tree).
- **Resurrection.** All 24 resurrected units name their feature, the feature
  went as resurrected, and the unit is the feature's resurrect type.
- **Builders' work.** Of the 4,273 units that builders (not factories) built,
  4,271 have a work line of their builder building them; 4,033 units were
  assisted by another builder. All 133 units reclaimed have a work line of
  their reclaimer on them.
- **Units.** The units against the snapshots differ as in format 5 (the same
  two `corwin` made between frames in one game, units still dying).
- **Same output.** The state written next to the line-of-sight probe (below)
  was byte-identical to the run without it.

#### How often to sample builders' work

On the first game, with the work sampled every 1, 5, 15 and 30 frames:

| Every     | Widget time | Work lines | Raw work lines | Built, seen building | Reclaimed metal | Largest team difference to the game |
| --------- | ----------- | ---------- | -------------- | -------------------- | --------------- | ----------------------------------- |
| 1 frame   | 2.65 s      | 11,888     | 770 KB         | 758 of 758           | 15,083.7        | 3.0 metal, 145 energy               |
| 5 frames  | 0.83 s      | 10,335     | 664 KB         | 757 of 758           | 15,083.7        | 3.0 metal, 148 energy               |
| 15 frames | 0.68 s      | 9,250      | 597 KB         | 757 of 758           | 15,083.7        | 6.9 metal, 141 energy               |
| 30 frames | 0.55 s      | 8,244      | 538 KB         | 752 of 758           | 15,076.2        | 9.9 metal, 133 energy               |

Five frames lose almost nothing against every frame and cost a third of the
time; 30 frames start to miss short jobs and reclaim.

#### Cost against format 5

The same five games and first 10 minutes, each played with the format 5 and
the format 6 widget, one engine at a time while 8 engines of another batch ran
on the machine (which sets the wall and simulation times):

| Per game (average of 5) | Format 5 | Format 6 | Change |
| ----------------------- | -------- | -------- | ------ |
| Simulation              | 120.9 s  | 118.6 s  | noise  |
| Widget's own time       | 0.26 s   | 0.75 s   | +0.5 s |
| JSON lines, raw         | 1.68 MB  | 2.69 MB  | +60%   |
| JSON lines, gzip        | 355 KB   | 504 KB   | +42%   |
| Tables                  | 275 KB   | 346 KB   | +26%   |

The widget's own time (summed with `Spring.GetTimer` in its call-ins) grows by
half a second, under 0.5% of the simulation. Of the 71 KB of tables added,
`work` is 28 to 38 KB, `features` 11 to 36 KB and `reclaim` 5 to 16 KB; the
features are mostly the trees and rocks a map starts with (2,638 on Supreme
Isthmus, 30 KB), the same in every game of the map (below), so a table per map
instead of per game would save about a tenth.

#### What the games of format 5 can get without playing them again

- **The features a map starts with:** yes. They were identical in type,
  position, metal and energy in three Supreme Isthmus games from June to
  November 2026, so one format 6 game per map (and game version, to be safe)
  gives them to every game.
- **Wrecks:** only approximately. The `destroyed` lines give the unit type,
  place and frame, and the unit definition its wreck and metal, but not
  whether a wreck was left (units destroyed unfinished, self-destructed or
  blown apart leave a heap or nothing), when it appeared, or when it went.
- **Reclaim, resurrection, builders' work, the attacker of a destroyed unit:**
  no. They need the simulation. The replay's commands say what builders were
  ordered to reclaim, repair or resurrect, not what they did or got.

### Sight, radar and loaded unit types (format 7)

The bot plays on what a player could see, so the state has to say which enemy
units each ally team saw, and when. Format 7 records it as events, and also
writes the unit types as the game loaded them, which the builders and the mask
of the decision table need
([ADR 0010](../decisions/0010-re-simulate-replays-headlessly-for-game-state.md)).

#### How the widget learns what each team sees

From the engine's source (Recoil 2025.06.19 and 2026.09.03, the same in both):

- Every frame, the unit handler recomputes each unit's state for each ally
  team in turn (`UpdateUnitLosStates`). When the sight or radar bit changes it
  calls `UnitEnteredLos`, `UnitLeftLos`, `UnitEnteredRadar` or `UnitLeftRadar`
  with the unit and that ally team. It sets the new bit before an "entered"
  call and clears it before a "left" call.
- The event handler passes a call to every Lua handle that can read that ally
  team. A spectator with full view can read them all, so the widget's handle
  gets the call for every ally team, with the ally team as its third argument.
- BAR's widget handler (`luaui/barwidgets.lua`) passes a widget only the unit
  and its team.

So the widget reads the unit's raw state for every ally team
(`Spring.GetUnitLosState(unit, allyTeam, true)`) and writes the ally team
whose bit differs from what it wrote last. Ally teams the engine has not come
to yet in that frame have not changed, and those before it were written at
their own call, so one ally team differs at each call. A unit in sight is on
radar too, as the engine counts it (the radar bit is set with the sight bit).
A unit's own ally team is left out. The engine sends nothing when a unit dies;
the widget skips dying units, whose `destroyed` line ends their being seen.

When a unit changes team, the engine works its state out again for every enemy
ally team, and announces it again to those that already saw it, before the
`given` call-in. The widget writes nothing then and does not count it as a
call without a change (it knows each unit's team from `created` and `given`).
A unit given to the ally team that saw it is that team's own from then on.

#### Checks on real games

The same five 8v8 games, first 10 minutes, played again with the format 7
widget. Each has 16 players in two ally teams.
`reason8 headless tables --check` (`visibility.py`):

| Game                          | Sight in / out | Radar in / out | Ended by leave / death / end | Hit first: in sight / radar only / neither | Destroyed: in sight / radar only / neither |
| ----------------------------- | -------------- | -------------- | ---------------------------- | ------------------------------------------ | ------------------------------------------ |
| Supreme Isthmus, 2026.07.04   | 2,075 / 1,735  | 1,769 / 1,327  | 3,062 / 641 / 141            | 358 / 117 / 32                             | 232 / 31 / 11                              |
| All That Glitters, 2026.07.04 | 2,130 / 1,847  | 1,861 / 1,492  | 3,339 / 496 / 156            | 379 / 62 / 36                              | 216 / 11 / 5                               |
| Supreme Isthmus, 2025.06.24   | 2,157 / 1,839  | 1,920 / 1,521  | 3,360 / 618 / 99             | 320 / 76 / 7                               | 229 / 15 / 1                               |
| Rosetta, 2026.06.12           | 4,165 / 3,592  | 3,181 / 2,491  | 6,083 / 1,020 / 243          | 677 / 58 / 13                              | 409 / 15 / 4                               |
| Supreme Isthmus, 2026.09.03   | 1,819 / 1,610  | 1,234 / 875    | 2,485 / 374 / 194            | 249 / 56 / 8                               | 143 / 15 / 3                               |

- **Pairs.** Every enter is followed by a leave, the unit's death, or the end
  of the run; no leave comes without an enter, and no unit is seen twice
  without leaving in between. No unit was given to an ally team that saw it.
- **Sight within radar.** Every one of the 10,346 entries into sight came
  while the unit was on radar.
- **The widget's own count.** No call matched several ally teams. Four games
  had no call that matched none; the first had two, both for one unit given
  twice in one frame, the second time to the team that already owned it, which
  the engine announced again. Nothing was missed.
- **Independent of the call-ins:** of the 2,448 units that an enemy team hit
  for the first time, 81% were in that team's sight and 15% on its radar only;
  of the 1,340 units an enemy destroyed (not counting units reclaimed by their
  own side), 92% and 6%. The rest, 3.9% and 1.8%, were hit out of sight:
  artillery and splash, and shots at other targets.
- **Same output.** The other lines are byte-identical to the format 6 widget's
  on all five games.
- **More than two ally teams.** With two, only one ally team can be the one
  that changed. A game of four BARb AIs, each its own ally team, on All That
  Glitters (engine 2026.09.03, 12 minutes): 9,000 lines spread over all four
  ally teams, no call matched none or several, every enter paired, and in 8
  frames a unit entered the sight of two ally teams at once, written as one
  line each.

#### Cost against format 6

The same five games, each played with the format 6 and the format 7 widget,
one engine at a time while 8 engines of another batch ran on the machine:

| Per game (average of 5) | Format 6 | Format 7 | Change  |
| ----------------------- | -------- | -------- | ------- |
| Simulation              | 150.7 s  | 148.1 s  | noise   |
| Widget's own time       | 0.93 s   | 1.00 s   | +0.07 s |
| JSON lines, raw         | 2.69 MB  | 3.30 MB  | +23%    |
| JSON lines, gzip        | 504 KB   | 643 KB   | +28%    |
| Tables                  | 351 KB   | 403 KB   | +15%    |

Of the 52 KB of tables added, the `visibility` table is 37 to 77 KB per game
(5,500 to 13,400 rows) and the unit types as loaded add 5 KB to the `game`
table. The sight and radar lines are 49 to 112 KB gzipped. The unit types make
the header 56 KB instead of 14 KB raw, 10 KB gzipped.

The position of each row is about half of the `visibility` table: without it
the table is 17 to 39 KB, close to the estimate of the probe below. It is kept
because a unit that can move is otherwise only placed by the snapshots, every
5 s, and where a scout was seen is what scouting is about. Sorting the table
by unit and frame, as `units` and `work` are, makes it 18% smaller than in the
order of the game.

Before format 7, a probe widget measured three ways of recording sight on two
of the games: events as above (13 to 14 KB of table for sight, 12 to 13 KB for
radar, without positions), a mask of the ally teams that see each unit of each
5 s snapshot (5.5 KB, but a scout that passes between two snapshots is lost),
and the same mask for every unit, buildings too (7.5 to 8 KB). Events were
chosen because scouting contacts are often shorter than a snapshot interval.

#### Unit types as the game loaded them

Compared with the unit files of the same game version as `reason8` reads them
(`reason8.game.unitdefs`, as the decision table does):

| Game version | Types with build power, loaded | Only loaded | Only in the files | Build lists that differ |
| ------------ | ------------------------------ | ----------- | ----------------- | ----------------------- |
| `test-31836` | 191                            | 67          | 94                | 18                      |
| `test-30903` | 205                            | 67          | 94                | 7                       |
| `test-30318` | 205                            | 67          | 86                | 20                      |
| `test-30664` | 275                            | 87          | 43                | 5                       |
| `test-32018` | 191                            | 67          | 94                | 6                       |

- **Only loaded:** types from files that build their units with code, which
  the reader skips: commander levels, assist drones, respawners.
- **Only in the files:** types the game did not load at all in that lobby:
  Legion's units in the three games whose lobby left Legion off, and types
  behind other options (experimental factories, the commander and raptor
  bosses, the raptors).
- **Build lists:** the higher commander levels lose two units, naval builders
  gain turrets in two game versions and a Cortex shipyard loses a submarine in
  two others; with Legion off, the Legion types that are still loaded keep one
  option.
- **Build power** matched for every type in both. The job flags differed for
  two to three types (loot pods and a Legion extractor that builds); factories
  can move and repair as the engine counts it, which the decision table's rule
  that factories do no jobs already overrides.

The decision table still reads the unit files: the games of the context sample
are of formats 5 and 6.

#### Builder and factory queues: what they would cost

Not in the export. The replay has every order a player gave, but not what is
left of a queue when its unit finished, failed or skipped an order. A probe
copy of the format 7 widget wrote a builder's or factory's whole queue at the
end of each frame in which it got an order or finished one (`UnitCommand`,
`UnitCmdDone`, `UnitIdle`, `UnitFinished`), when it changed; two of the games:

- 7,600 to 9,100 lines from 238 units, 2.1 to 2.4 MB raw and 165 to 171 KB
  gzipped: two thirds more JSON and a quarter more gzipped. Factories with
  long repeat queues make most of it (up to 387 orders in one queue).
- As a table of one row per order of each queue written, 101,000 rows and 128
  KB: a third more tables.
- The widget's own time doubles, from 1.0 s to 1.95 s per game; still about 1%
  of the simulation.
- Written as changes (orders added and removed against the previous queue of
  the unit), the same queues are about 28,000 rows, a quarter of the above.

## 5. Per engine: RAM, CPU, throughput

| Workload                       | Peak RAM | Cores used | Game minutes per wall minute | Wall per replay |
| ------------------------------ | -------- | ---------- | ---------------------------- | --------------- |
| BARb vs BARb, 10 min, 1 thread | 5.4 GB   | 1.1        | 44x                          | 34 s            |
| 1v1 replay, 13 min, 1 thread   | 4.7 GB   | 1.0        | 48x                          | 37 s            |
| 8v8 replay, 26 min, 1 thread   | 5.7 GB   | 1.0        | 3.8x                         | 427 s           |
| 8v8 replay, 26 min, 4 threads  | 5.8 GB   | 2.0        | 4.7x                         | 347 s           |

The RAM figure agrees with Apex's 5 to 6 GB. All of it is the engine's private
memory (4.6 GB is already there when the game starts: map, models and textures
are loaded even without a screen), so engines do not share it. **This machine
fits 5 engines by RAM, not 32 by cores.**

Engines also slow each other down. Four at once, 1 thread each:

| Test                              | Alone | Four at once | Slowdown |
| --------------------------------- | ----- | ------------ | -------- |
| 1v1 replay, simulation            | 16 s  | 21.5 s       | 1.3x     |
| 1v1 replay, whole run             | 37 s  | 44 s         | 1.2x     |
| 8v8 replay, first 15 game minutes | 108 s | 171 s        | 1.6x     |
| 8v8 replay, loading               | 21 s  | 32 s         | 1.5x     |

Replays per hour per core:

| Replay type | One engine alone | Four engines at once  |
| ----------- | ---------------- | --------------------- |
| 1v1, 13 min | 99               | 81                    |
| 8v8, 26 min | 8.4              | about 5.3 (estimated) |

The 8v8 figure for four engines is an estimate: the 1.6x slowdown was measured
on the first 15 game minutes and applied to the whole game.

Per 1,000 replays that is 10 to 12 core-hours for 1v1 and 120 to 190
core-hours for 8v8, with 6 GB of RAM per core. Cloud prices are not covered
here.

Two things to know when running engines in parallel:

- A replay is served on UDP port 8452 by default. A second playback on the
  same machine dies with `bind: Address already in use`.
  `reason8 headless run` sets `HostPortDefault = 0` (any free port).
- Give each run its own write dir and share the content read-only through
  `SPRING_DATADIR`. `reason8 headless run` does this.

## 6. Getting the right engine, game and map at scale

Everything needed is in the replay header (`reason8 header`): engine version,
game version, map name.

### Engine

Prebuilt Linux engines are on GitHub (`beyond-all-reason/RecoilEngine`
releases), with `spring-headless`, `pr-downloader` and BARb inside.

2025.03.1 and later (March 2025)
: *Asset name:* `recoil_<version>_amd64-linux.7z`
: *Size:* 28 to 34 MB, 120 MB unpacked

2025.01.x and 105.1.1-\* (2022 on)
: *Asset name:* `spring_bar_.<branch>.<version>_linux-64-minimal-portable.7z`
: *Size:* 27 to 56 MB

`reason8 headless setup` handles the first kind, which covers every replay
since 2025-04-16. Engines are few: in the last 12 months 9 engines had 100 or
more matches (697,035 matches in total). All 9 would take 300 MB to download
and 1.1 GB on disk.

### Game version

BAR game versions are published through "rapid": a small index of names
(`versions.gz`, 0.65 MB) and a pool of files stored by content hash, so
versions share files. `pr-downloader --download-game "<exact name>"` fetches
one.

- The index lists 12,605 `test-` versions. **Every one of the 4,876 game
  versions in `matches.parquet` (back to 2022) is in it by exact name.**
- Fetching by exact name worked for all 7 versions we tried, from this week
  back to October 2023.
- Disk: the first version is 1.99 GB. Each further one only adds the files
  that differ:

| Extra version, age relative to the first | Added to the pool | Download time |
| ---------------------------------------- | ----------------- | ------------- |
| 2 days                                   | 1.0 MB            | 5 s           |
| 3 days                                   | 1.4 MB            | 10 s          |
| 2 months                                 | 6.1 MB            | 48 s          |
| 4 months                                 | 39.4 MB           | 172 s         |
| 5 months                                 | 4.0 MB            | 50 s          |
| 3 years (October 2023)                   | 234 MB            | 204 s         |

(In download order: 2 days, 3 days, 4 months, 2 months, 5 months, 3 years. A
version adds less when a nearby one is already there. All seven together: 2.27
GB.) Each version also has a 0.55 MB file list. Download time is with our
limit of 20 requests per second; every missing file is one request.

- There are many versions: 379 in the last 12 months, median 1,146 matches
  each.

### Map

`pr-downloader --download-map "<name>"` fetches a map from BAR's CDN by its
exact name: 36 MB (Avalanche), 62 MB (Canis River), 144 MB (Supreme Isthmus).
251 maps were played in the last 12 months; 12 of them cover half of all
matches and 136 cover 90%.

`pr-downloader` downloads a map again even when it is already there, so
`reason8 headless setup` keeps a list of what it has fetched
(`headless_setup.json` in the data dir) and skips those.

### Example: the first training slice

The first slice ([`dataset.md`](../reference/dataset.md)) is 42,913 ranked 8v8
games on three maps from the last 6 months. It spans 7 engines and 199 game
versions. Three engines cover 94% of it: 2026.07.04 (52%), 2025.06.24 (30%)
and 2026.06.12 (12%).

Top 3 engines
: 98 MB download, 358 MB on disk, under 20 s each. All three downloaded and
  unpacked fine

All 7 engines
: about 230 MB download, 0.8 GB on disk. All have the
  `recoil_<version>_amd64-linux.7z` name

199 game versions
: 2.0 GB for the first, then 1 to 40 MB each: about 2.5 to 4 GB in total
  (estimate from the versions measured), plus 0.1 GB of file lists. One to
  three hours of polite downloading, once

3 maps
: 144 MB for Supreme Isthmus; the other two were not downloaded here

Replays
: 1 to 3 MB each: about 100 GB (estimate)

Simulation, whole games
: 42,913 x 430 to 670 s = 5,100 to 8,000 core-hours, 6 GB RAM per engine

Whole games on this machine (5 engines)
: about 27 replays per hour: roughly 9 weeks

Simulation, first 10 minutes only
: 42,913 x 65 to 100 s = 800 to 1,200 core-hours (the 100 s assumes the 1.5x
  slowdown of running engines side by side)

First 10 minutes on this machine (5 engines)
: about 180 replays per hour: roughly 10 days

State of whole games, 5 s / 30 s snapshots
: 260 GB / 50 GB gzipped

Old game versions by exact name: still fetchable, see above. Replay files were
not tested here beyond the ones we played; `dataset.md` reports that files
since 2023 still download and 2022 ones do not.

Replays from engines 2026.07.04 and 2025.06.24 were played back on their own
engines as a test (the last two rows of the table in section 2): 0 desyncs,
right winner, right length. Engine 2026.06.12 was installed and a game version
for it fetched, but no replay was played on it. One thing to watch on engine
2025.06.24: it logs a line about a texture atlas several hundred times per
second, 23 MB of log for one 8v8 game, so clean up run dirs.

## 7. Go / no-go for using state in v2

**Go.** The decision is recorded in
[ADR 0010](../decisions/0010-re-simulate-replays-headlessly-for-game-state.md);
this section keeps the numbers behind it.

- **1v1 (milestone 2, learned macro):** clear go. About 40 s and 90 KB per
  replay. 100,000 duels are about 1,100 core-hours, which is two weeks on this
  machine or a small cloud job, and 9 GB of state.
- **8v8 (team openings):** go, with a budget. A full game costs 7 to 11
  minutes of one core and 6 GB of RAM. For openings, stop at minute 10: about
  65 s per replay instead of 430 s. Whole games in bulk belong on a cloud
  cluster.

What the pipeline must do, all of it already in `reason8/headless/`:

1. Read engine, game version and map from each replay's header and fetch
   exactly those.
2. Run one engine per replay with 1 thread, its own write dir and a free port.
3. Reject any run with a desync warning, a non-zero exit code, or a timeout.

## Open items

- Reclaim between allies on the same feature is split by reclaim speed at the
  samples. Each builder's own income (`Spring.GetUnitResources`, which
  includes what it reclaims, summed over the engine's last 30 frames) would
  split it exactly, at the price of a line per reclaiming builder and second.
- Ten table files per game: if tens of thousands get slow to list or sync,
  merge the tables of a day into one file per table.
- The cloud cost per 1,000 replays. `reason8 headless batch` runs a list of
  replays with N engines at once and skips what is done, on one machine.
- Find out why engines slow each other down (memory bandwidth, or fast and
  slow cores) and whether a server CPU behaves better.
- Engines before 2025.03 use another download name and are untested. Engines
  older than 2025.06.24 are untested for playback.
- RAM: 4.6 GB per engine is mostly rendering data a headless run does not
  need. Engine settings that skip it would let more engines fit.
- Replays that end without a game over (host left) stop at the header's last
  frame; this path is only tested with `--max-frame`.
