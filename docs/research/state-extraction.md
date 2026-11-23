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
: Yes. Units, positions, health, build progress, resources and wind, plus an
  event for every unit created / finished / destroyed and for every first hit
  between two enemy units

Is the re-run the same game?
: Yes. 0 desync warnings, same winner and length as recorded, byte-identical
  output across runs

Disk per game (snapshot every 5 s, gzip)
: 1v1 (13 min): 86 KB. 8v8 (26 min): 6.0 MB

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
  the state as `<replay name>.jsonl.gz`, skips the ones already done

`state`
: Reads a state file; prints sizes and counts, and the first finished builds
  per team

`widgets/reason8_state_export.lua`
: The widget that writes the state file

`startscripts/barb_vs_barb.txt`
: BARb vs BARb start script template

`reason8 header` (in `reason8/replays/sdfz.py`) reads a replay's header:
engine version, game version, map, length.

```sh
# fetch what a replay needs (engine, game version, map)
uv run reason8 headless setup --data-dir data/bar \
    --replay data/replays/X.sdfz
# play it and keep the state
uv run reason8 headless run --data-dir data/bar --threads 1 --snapshots \
    --out data/state/X.jsonl data/replays/X.sdfz
uv run reason8 headless state data/state/X.jsonl --builds
# the first 12 game minutes of many replays, 4 engines at once
uv run reason8 headless batch --data-dir data/bar --out-dir data/state \
    --jobs 4 --max-frame 21600 data/replays/A.sdfz data/replays/B.sdfz

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

`header`
: *When:* once
: *Content:* game, map, engine, map size, the map's wind range and tidal
  strength, teams (number, ally team, AI or not, side), unit type id to name

`s`
: *When:* every N game seconds
: *Content:* the wind strength at that moment; per team: metal and energy
  (stored, storage, income, expense); per unit: id, type, team, x, z, health
  %, build %

`created`
: *When:* unit placed
: *Content:* frame, unit, type, team, position, builder

`finished`
: *When:* unit completed
: *Content:* frame, unit, type, team, position

`destroyed`
: *When:* unit died
: *Content:* frame, unit, type, team, position, whether it was finished,
  attacker's team

`given`
: *When:* unit changed team
: *Content:* frame, unit, type, new team, old team

`hit`
: *When:* a unit is damaged by a given enemy team for the first time
: *Content:* frame, unit, type, team, position, the attacking unit, its type
  and team, the damage

`damage`
: *When:* every second in which one team damaged units of an enemy team
: *Content:* frame, damaged team, attacking team, number of hits, damage

`end`
: *When:* game over or last frame
: *Content:* frame, reason, winning ally teams, how the attackers were told
  (below)

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

### Not recorded yet

- What each player could **see** (line of sight). The spectator sees
  everything; the bot must learn from what its player saw. The widget can ask
  the engine per ally team; this is the main addition needed for milestone 2.
- Wrecks and other reclaimable features, unit orders, and the map's metal
  spots.

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

- Record what each player could see (line of sight per ally team); needed
  before the state is used for training.
- A compact binary state format for 8v8.
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
