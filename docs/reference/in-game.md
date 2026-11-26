# How a trained model controls a bot in BAR

A model that predicts what a good player does next is only useful if its
predictions reach a running game. This document compares the ways to do that,
describes the one we built, and gives the measurements behind the choice. The
decision itself is
[ADR 0007](../decisions/0007-ship-the-model-as-tables-in-a-barb-variant.md).

Read [`barb.md`](../research/barb.md) first: it explains BARb, the AI that
ships with BAR, and the scripts mentioned here.

## Summary

- **A BARb variant under its own short name works, with no C++ build.** We
  copied the engine's BARb library, added the game's BARb scripts with hooks
  in two of them, and installed it as the Skirmish AI `Reason8`. It loads next
  to stock BARb and plays against it headlessly.
- **It plays a build order we give it.** The commander builds the listed
  structures in order and the first factory makes the listed units in order,
  by unit name. Then stock BARb takes over. Checked against what was really
  built in 11 games: the commander's part was complete and in order in all 11;
  the factory's part was in order in all 11 and complete in 10 (in one game
  the economy was too weak to finish it in time).
- **It plays the model's opening of its start position.** `reason8 bot export`
  writes one opening per map, position and faction from the next-build model,
  and the AI picks the one whose position is nearest to its commander. In two
  8v8 games every Reason8 team found its position; see
  [Learned openings in team games](#learned-openings-in-team-games).
- **The model does not have to run inside the game yet.** For openings its
  output is known before the game starts, so it is exported to a data file and
  compiled into a script table.
- **Failures are silent.** A missing AI or a script error leaves the team
  standing still while the game runs on and exits normally. Every result has
  to be checked against the log and the replay, and there is a tool for it.
- **BARb is not human-like in how often it gives orders**: 40 to 700 commands
  a minute in the first five minutes, peaks of 1,100 to 3,200 a minute later,
  and up to 125 in one second. The scripts cannot change that.
- **Past the tables, our own build of BARb's library is the route that covers
  everything.** We built CircuitAI from source in under 7 minutes, loaded it
  as `Reason8`, and capped its commands at a human budget. A script-to-widget
  bridge also works, but only adds a little state and cannot cap commands. See
  [Past the tables](#past-the-tables).

## The options

Each option is judged on the same points: how a decision gets into the game,
how long that takes, what the bot can see, how it is installed and whether it
works in a normal lobby, and how it is tested headlessly. "Measured" means we
ran it; everything else was read from the engine, the game or the lobby
source.

### 1. BARb variant with tables generated offline (built)

How decisions get in
: The model's predictions are written to a data file before the game. The
  build turns the file into an AngelScript table inside the AI's folder. Hooks
  in BARb's builder and factory scripts play the table. *Measured.*

Latency
: None at decision time: a table lookup inside the AI's own update.

What it sees
: Whatever BARb's scripts are given (listed below): own economy, own units,
  map name, side, positions, sums about the enemy. Enemy information goes
  through BARb's own tracking, which uses line of sight and radar unless the
  `cheating` option is on ([`barb.md`](../research/barb.md)); our options
  leave it off. An opening table needs none of it.

Install and lobbies
: One folder, `AI/Skirmish/Reason8/<version>/`, in the engine folder or in the
  data folder. *Measured for both, headlessly.* A Skirmish AI runs on the
  computer of the player who added it, and its orders travel as ordinary
  network commands, so only that player needs the folder; the game archive is
  not changed. Details and what is still untested are under
  [Installing](#installing-it-in-a-real-game).

Headless test
: `reason8 headless run` with a start script that names the AI. *Measured:* 30
  s of wall time for a 5-minute game.

Limits
: Only decisions that are known before the game, or that depend on the little
  the scripts can see. The scripts have no file or network access.

### 2. BARb variant that asks a model during the game

How decisions get in
: Two routes. (a) The script calls Lua with `ai.CallUI(text)`; a widget on the
  same computer answers with a string. *Measured: the call and the answer
  arrive, and an outside process can answer through files.* (b) A C++ build of
  the AI (CircuitAI) that runs the model itself or talks to another process,
  which is what Apex does ([`related-work.md`](../research/related-work.md)).
  *Measured: it builds, loads and plays.* Both are in
  [Past the tables](#past-the-tables).

Latency
: (a) The call is synchronous and in-process. The widget's log line and the
  script's log line with the answer were 14 microseconds apart. The game waits
  for the answer, so a slow model would freeze it; a real bridge has to ask in
  one update and read the answer in a later one. (b) In-process.

What it sees
: (a) The script can only send what it sees itself; the widget could add what
  the local player's interface sees. (b) Everything the AI interface offers.

Install and lobbies
: (a) The AI folder plus a widget on the same computer. BAR runs user widgets
  in a sandbox that removes `socket` (*measured: `socket` is `nil`*) and
  allows files only under `LuaUI/Config/` and `LuaUI/Widgets/` (*measured:
  anything else is refused*). So a user widget reaches another process through
  files only. The host can also switch user widgets off (`allowuserwidgets`,
  or anonymous mode). (b) One folder, but a library to build for Windows and
  Linux against each engine release.

Headless test
: Same runner; `--widget` installs the widget.

Limits
: (a) In one of three early runs that had a test widget installed, the engine
  stopped advancing after frame 289 and had to be killed; the two later runs
  with a widget finished. The cause is unknown, so a bridge needs a timeout.
  The test widgets and the script changes are not in the repo.

### 3. Own native Skirmish AI

How decisions get in
: A library the engine loads through its C interface, like BARb. It is
  ordinary native code, so it can embed a model runtime or open a socket or
  pipe to a Python process. The engine ships a minimal example, `NullAI`
  (`AIInfo.lua`, `AIOptions.lua` and one library).

Latency
: In-process; a second process adds one round trip per decision.

What it sees
: The AI interface: own units and resources, the map, and enemy units as the
  team sees them, unless cheats are switched on. *By the interface's design;
  not checked here.*

Install and lobbies
: Like option 1: a folder under `AI/Skirmish/`, needed only by the player who
  adds the bot. A second process would have to be started and found on that
  player's computer too.

Headless test
: Same runner.

Limits
: Everything BARb does (pathing, placement, threat maps, army control) has to
  be written again or done without. That is against
  [ADR 0006](../decisions/0006-build-on-barb-and-replace-its-decisions-layer-by-layer.md).
  The library has to be built for each platform and engine version.

### 4. Lua AI (a gadget in the game)

How decisions get in
: BAR's own Lua AIs (`SimpleAI`, `ScavengersAI`, `RaptorsAI`, listed in the
  game's `luaai.lua`) are synced gadgets inside the game archive, for example
  `luarules/gadgets/ai_simpleai.lua`. The model would be Lua tables or Lua
  code in such a gadget.

Latency
: Runs inside the simulation on every player's computer, so it must be
  deterministic and cheap. No sockets, no files, no other process.

What it sees
: Everything. Synced code is not limited to a team's line of sight, so the
  limits of [ADR 0008](../decisions/0008-play-under-human-like-limits.md)
  would be self-imposed.

Install and lobbies
: It has to be in the game archive that every player runs. That means getting
  it merged into BAR, or a modified game, which normal lobbies do not host.

Headless test
: Same runner, with `ShortName=<Lua AI name>` and no library. *Not tried.*

Limits
: Not installable by one player. Ruled out for the proof of concept.

### 5. Widget that plays a player's slot

How decisions get in
: A widget is unsynced Lua on one player's computer. It gives orders for that
  player's own team, so the bot occupies a human slot, not an AI slot.

Latency
: Per frame, in-process.

What it sees
: Exactly what that player sees, enforced by the engine. This is the only
  option that is human-like in what it sees by construction. *Not checked
  here.*

Install and lobbies
: A file in the player's widget folder, but one game client per bot. BAR's
  sandbox stops user widgets from giving orders when the host switches off
  `allowunitcontrolwidgets`, and removes `socket`, so the model has to be Lua
  or sit behind files. *Read in the game's `luaui/barwidgets.lua`; both mod
  options are on by default.*

Headless test
: Possible in principle (our state export is a widget), but the runner would
  have to join as a player. *Not tried.*

Limits
: No AI slot, so no "add a bot" in the lobby; a whole client per bot; and
  everything BARb does would have to be written in Lua.

## What we built

The AI lives in [`ai/Reason8`](../../ai/Reason8):

`AIInfo.lua`, `AIOptions.lua`
: The AI's identity (short name `Reason8`, version `0.1`) and its options. Two
  defaults differ from BARb's: `game_config` is off, because the game archive
  has no scripts for this AI, and the only profile is `hard`.

`openings.json`
: The openings, as data, written by `reason8 bot export` from the next-build
  model ([`results.md`](../results.md#using-it-in-the-game)). For each side,
  map and start position, five openings (`variant` 0 to 4, the one the model
  finds most likely first): where the position's players start, the structures
  the commander builds with where the human placed each (`places`), and the
  first units of its first factory, by unit name. A separate `tasks` map says
  which BARb task type builds each structure. An opening without a map is
  played on any map, by side only; the tests use a file of deliberately
  unusual ones, so that a game shows at once whether they were played.

`script/hard/reason8/opening.as`
: The logic, about 400 lines of AngelScript. It finds the position of the AI's
  side and map whose start is nearest to the commander, picks one of its
  openings at random, and gives the commander one build task per step and the
  factory one task per unit, moving on when a task is done and trying again,
  after a pause, when it fails.

`script/hard/manager/builder.as`, `factory.as`
: Copies of BARb's two scripts with six added calls into `opening.as`, marked
  `Reason8:`.

`base.json`
: The SHA-256 of the stock scripts those two copies were made from.

```json
{
  "tasks": {
    "armlab": "factory",
    "armmex": "mex",
    "armwin": "energy"
  },
  "openings": [
    {
      "side": "armada",
      "map": "Supreme Isthmus v2.1",
      "position": "P1",
      "start": [
        681,
        7376
      ],
      "candidates": 1977,
      "log_likelihood": -9.197,
      "commander": [
        "armmex",
        "armmex",
        "armmex",
        "armwin",
        "armwin",
        "armwin",
        "armwin",
        "armlab"
      ],
      "factories": {
        "armlab": [
          "armck",
          "armrectr",
          "armck"
        ]
      },
      "dropped": {
        "after the commander's last structure": 4
      }
    }
  ]
}
```

(Shortened: the opening has 30 commander steps and six factory units.)
`candidates` is how many human openings the export scored for the position and
`log_likelihood` the model's score of the one chosen; `dropped` counts what
the AI cannot play (see [`results.md`](../results.md#using-it-in-the-game)).

`reason8 bot build` puts the AI folder together from three sources:

1. the engine's own `AI/Skirmish/BARb/stable/`: the library, unchanged;
2. the installed game's `luarules/configs/BARb/stable/`: BARb's scripts and
   configs for the `hard` profile, read from the game package;
3. `ai/Reason8`, on top, with `openings.json` turned into
   `script/hard/reason8/opening_table.as`. Each opening's steps and factory
   units are one string there, decoded only for the opening played: 480
   openings as nested script arrays made each Reason8 AI take minutes to
   compile.

It stops when a stock script that we replace no longer has the recorded hash,
because our copy would silently drop the game's change.

### How the hooks work

Commander
: `Builder::AiMakeTask` is called whenever a builder has nothing to do. For
  the commander, `opening.as` returns a task for the next step, created with
  BARb's own task functions (`TaskB::Common`, `TaskB::Factory`), so BARb still
  chooses the exact spot and handles the walk. `AiTaskRemoved` tells the
  script that the step finished or failed. After the last step the hook
  returns nothing and BARb's default takes over.

Extractors
: An extractor task needs one of BARb's metal spots. BAR publishes the map's
  spots as game rules (`mex_count`, `mex_x1`, `mex_z1`, ...), BARb reads them
  in that order, and scripts can read game rules, so spot `i` of the game is
  BARb's spot `i - 1`. For a `mex` step the script takes the free spot nearest
  to where the human player built that extractor and creates the task on it
  (`TaskB::Spot`). Without a known place, or without the game's spots, it asks
  BARb for its default task and accepts it only if it is an extractor of the
  ordered type; after the first three extractors BARb rarely offers one.

Placement
: Every step carries where the human player placed it (`places` in
  `openings.json`). The first try builds there, BARb choosing the exact site
  around it; when that fails, the next tries build next to the builder.

Hidden timers
: BARb's configs hold some units back (`since` in `behaviour.json`): the radar
  until 120 s, the light laser tower until 70 s. The script sets the unit's
  `sinceFrame` to 0 when an opening orders it earlier. *Measured:* the radar
  was ordered at second 28 and the laser tower at second 25.

Factory
: `Factory::AiUnitAdded` is called when a factory is finished; the script
  remembers the first factory the opening has units for. `Factory::AiMakeTask`
  is called whenever a factory has nothing to do, and the script returns a
  recruit task for the next listed unit, by name. BARb's own opener works in
  roles (RAIDER, SCOUT...); a recruit task takes a unit, so no mapping from
  units to roles is needed. One unit is queued at a time, so a task that BARb
  gives up on can be queued again without changing the order.

Log
: Every decision is logged with the prefix `Reason8 opening: team <id>:`, so
  the lines of several Reason8 teams in one game can be told apart.

```
Reason8 opening: team 0: side 'armada', map 'Supreme Isthmus v2.1', start 711 7215: position P1 (start 681 7376), opening 2 of 5, 30 commander steps, 1 factories
Reason8 opening: team 0: step 1 armmex: BARb's extractor task, frame 81
Reason8 opening: team 0: step 1: finished, frame 334
Reason8 opening: team 0: step 4 armwin: task queued, frame 1017
Reason8 opening: team 0: step 8: finished, frame 2768
Reason8 opening: team 0: factory armlab: will make armck armrectr armck armrectr armck armrectr, frame 2768
Reason8 opening: team 0: factory unit 1 armck: task queued, frame 2789
Reason8 opening: team 0: factory unit 1: done, frame 3520
```

### What a script can see and do

Read from CircuitAI's script bindings (`src/circuit/script/*.cpp`).

Can see
: Frame number, team and ally team, side name, map name (`ai.GetMapName()`),
  any unit's position, own metal and energy (stored, income, pull, storage),
  how many of each unit type the team has, game and team rules parameters, and
  sums about the enemy: threat by role, cost by role, mobile threat.

Can do
: Create build tasks and factory tasks for a named unit, change a unit type's
  timer, limit and role, pick the next factory, call Lua (`ai.CallUI`,
  `ai.CallRules`) and receive a Lua message (`AiLuaMessage`).

Cannot
: Read files, open sockets, read a clock, list enemy units, read the current
  wind or line of sight, or send or limit unit commands except through BARb's
  tasks. Metal spots are readable only because BAR publishes them as game
  rules (`mex_count`, `mex_x1`, ...); the wind only as the map's average, in
  the energy BARb expects from a wind generator
  (`aiEconomyMgr.GetEnergyMake`).

*So the start position needed for per-position openings is available: the map
name and the commander's position at frame 0. The opening script uses both.*

## How to run it

All paths are arguments; nothing under `data/` is committed. `data/bar` is the
content folder made by `reason8 headless setup`
([`state-extraction.md`](../research/state-extraction.md)).

```sh
# 0. the openings, from the saved model (written to ai/Reason8/openings.json)
uv run reason8 bot export --data-dir data/bar \
    --game "Beyond All Reason test-32018-ad135b9"

# 1. build the AI into the folder the game will run in
uv run reason8 bot build --data-dir data/bar \
    --game "Beyond All Reason test-32018-ad135b9" \
    --skirmish-dir data/runs/reason8/AI/Skirmish

# 2. Reason8 (Armada) against stock BARb (Cortex), 5 game minutes
uv run reason8 headless run --data-dir data/bar --threads 1 \
    --run-dir data/runs/reason8 --timeout 300 \
    --var "MAP=Supreme Isthmus v2.1" \
    --var "GAME=Beyond All Reason test-32018-ad135b9" \
    --var SEED=1 --var FRAMES=9000 \
    --var "AI0=ShortName=Reason8;" \
    --var "AI1=ShortName=BARb; Version=stable;" \
    reason8/headless/startscripts/ai_vs_ai.txt

# 3. what was really built: play the recorded game again and keep the state
uv run reason8 headless run --data-dir data/bar --threads 1 --snapshots \
    --max-frame 7500 --out data/runs/reason8.state.jsonl \
    data/runs/reason8/demos/*.sdfz

# 4. check the log, the orders and what was built
uv run reason8 bot check data/runs/reason8/demos/*.sdfz \
    --infolog data/runs/reason8/infolog.txt \
    --state data/runs/reason8.state.jsonl
```

For a team game on the map's recommended positions, `reason8 bot game` writes
the start script in place of step 2's `ai_vs_ai.txt`: eight Reason8 teams of
one side against eight stock BARb teams of the other.

```sh
uv run reason8 bot game --map "Supreme Isthmus v2.1" \
    --game "Beyond All Reason test-32018-ad135b9" --minutes 6 \
    --out data/runs/team-isthmus/script.txt
uv run reason8 headless run --data-dir data/bar --threads 2 \
    --engine-dir data/bar/engine-variants/reason8 \
    --run-dir data/runs/team-isthmus --timeout 1500 \
    data/runs/team-isthmus/script.txt
```

Step 1 can instead make a copy of the engine with the AI inside
(`--engine-copy data/bar/engine-variants/reason8`, then
`--engine-dir data/bar/engine-variants/reason8` in step 2). The shared engine
folder is never changed.

`AI0` and `AI1` hold everything that identifies an AI in the start script.
Leaving `Version` out is what a lobby does.

With `--infolog`, `reason8 bot check` also counts each team's opening log
lines (`opening_by_team`): its position, the steps finished and skipped, and
the factory units made.

`reason8 bot check` exits non-zero unless the AI loaded without errors and
every team it played followed its opening. Its output has three parts per
team: what was `ordered` (from the replay's commands, read with
`reason8.replays.parse`), what was `built` (from the state file) and the
`log`.

## Measurements

Setup: engine `recoil_2026.09.03`, game
`Beyond All Reason test-32018-ad135b9`, map Supreme Isthmus v2.1, one AI per
side, BARb `stable` with the `hard` profile (library version 1.6.29 by its own
log line), the machine of
[`state-extraction.md`](../research/state-extraction.md), one worker thread,
speed cap 100.

### Does a custom variant load?

Yes. This settles the open point in [`barb.md`](../research/barb.md).

Stock scripts under the name `Reason8`, no `Version` in the start script
: Loads. The log says
  `Skirmish AI <Reason8-0.0>: Load script: <engine>/AI/Skirmish/Reason8/0.0/script/hard/init.as`,
  where stock BARb says
  `Load script: LuaRules/Configs/BARb/stable/script/hard/init.as` (the game
  archive). So the AI falls back to the files next to its library when the
  game has none under its short name, as Apex described. The build orders are
  stock BARb's.

Two versions installed (`0.0` and `0.1`), no `Version` in the start script
: The engine loads `0.1`, the higher one. The replay records the AI's short
  name and no version.

AI folder in `<write dir>/AI/Skirmish/` instead of the engine folder
: Loads, with the untouched stock engine.

Default options
: The profile (`hard`) and `game_config = false` are taken from our
  `AIOptions.lua` when the start script sets nothing.

### Does it play the opening?

Eleven games of Reason8, with the deliberately unusual openings of the tests,
against stock BARb: ten of 5 minutes and one of 15 (seed 21). Odd seeds have
Reason8 as Armada, even seeds as Cortex. Each recorded game was played again
with state export up to frame 7,500 (250 s), and `reason8 bot check` compared
what was built with the opening. "Done" is the second the last listed
structure or unit was finished.

| Seed | Side   | Commander steps built | Done (s) | Factory units built | Done (s) | Orders as listed |
| ---- | ------ | --------------------- | -------- | ------------------- | -------- | ---------------- |
| 1    | Armada | 5 of 5                | 54       | 5 of 5              | 139      | yes              |
| 2    | Cortex | 4 of 4                | 59       | 2 of 4              | -        | no               |
| 11   | Armada | 5 of 5                | 55       | 5 of 5              | 170      | yes              |
| 12   | Cortex | 4 of 4                | 58       | 4 of 4              | 199      | no               |
| 13   | Armada | 5 of 5                | 53       | 5 of 5              | 167      | yes              |
| 14   | Cortex | 4 of 4                | 62       | 4 of 4              | 198      | yes              |
| 15   | Armada | 5 of 5                | 59       | 5 of 5              | 170      | yes              |
| 16   | Cortex | 4 of 4                | 60       | 4 of 4              | 238      | yes              |
| 17   | Armada | 5 of 5                | 58       | 5 of 5              | 168      | yes              |
| 18   | Cortex | 4 of 4                | 59       | 4 of 4              | 234      | no               |
| 21   | Armada | 5 of 5                | 58       | 5 of 5              | 164      | yes              |

- **Commander: 11 of 11.** Every listed structure was built, in order, and the
  last one was finished within 53 to 62 s.
- **Factory: in order in all 11, complete in 10.** In the game with seed 2 the
  factory had made two of its four units, both the right ones, when the check
  ended. In that game the team ordered five more laser towers and only one
  wind generator after the opening, and the factory starved. The opening's
  units compete with whatever BARb spends on afterwards.
- **No script errors, no failed or skipped steps** in any log, and no desyncs
  when the replays were played again.
- **"Orders as listed" is "no" in three games** although the right units were
  built: BARb sent a factory order twice. See the next section.
- Stock BARb took over each time. In the 15-minute game the Reason8 team gave
  201 build orders for 30 different unit types.

#### The first version lost a unit

The first version of the script queued all of the factory's units as soon as
the factory was finished, as BARb's own opener does. In 11 games of the same
kind the commander's part was right in all 11, the factory's orders were sent
twice in 3, and in 1 of those a unit was lost: the extra order made the
factory start a second resurrection bot, BARb cancelled it three frames later,
and only one of the two anti-air bots was made. The built units were
`armrectr, armjeth, armck, armham` instead of
`armrectr, armjeth, armjeth, armck, armham`.

The current version queues one unit at a time and queues a failed task again.
It lost no unit in 11 games, with orders sent twice in 3 of them, and the
retry was never needed. *Eleven games are too few to say the change is what
fixed it; the loss may simply not have come up.*

### Learned openings in team games

Two 8v8 games of 6 minutes, eight Reason8 teams against eight stock BARb
teams, each team on its recommended position (`reason8 bot game`), with the
openings of `reason8 bot export`: Reason8 as Armada on Supreme Isthmus with
seed 1, and as Cortex on All That Glitters with seed 2. Counted from each
team's log lines (`reason8 bot check --infolog`, `opening_by_team`). "Built"
is the commander steps finished; a skipped step was given up after five tries.

| Map             | Position | Steps | Built | Skipped | Factory units made |
| --------------- | -------- | ----- | ----- | ------- | ------------------ |
| Supreme Isthmus | P1       | 30    | 28    | 0       | 6                  |
| Supreme Isthmus | P2       | 30    | 17    | 0       | 0                  |
| Supreme Isthmus | P3       | 30    | 25    | 2       | 7                  |
| Supreme Isthmus | P4       | 30    | 24    | 3       | 0                  |
| Supreme Isthmus | P5       | 6     | 3     | 3       | 25                 |
| Supreme Isthmus | P6       | 8     | 6     | 2       | 19                 |
| Supreme Isthmus | P7       | 30    | 14    | 3       | 10                 |
| Supreme Isthmus | P8       | 30    | 18    | 6       | 14                 |
| Glitters        | P1       | 30    | 27    | 3       | 18                 |
| Glitters        | P2       | 30    | 28    | 1       | 8                  |
| Glitters        | P3       | 30    | 28    | 0       | 9                  |
| Glitters        | P4       | 29    | 24    | 5       | 0                  |
| Glitters        | P5       | 30    | 26    | 4       | 9                  |
| Glitters        | P6       | 30    | 24    | 4       | 20                 |
| Glitters        | P7       | 30    | 22    | 6       | 18                 |
| Glitters        | P8       | 30    | 18    | 7       | 16                 |

- **Every team found its position.** Each of the 16 Reason8 teams chose the
  opening of the position it started on. Fifteen started within 170 map units
  of the median start of that position's human players. Isthmus `P4`, the
  pond, started 800 units from it, because the map list's spot is that far
  from where its human players stand; it was still nearest to its own.
- **No script errors and no desyncs.** The Isthmus game took 114 s of wall
  time (9.5 times real time), the Glitters game 45 s.
- **Most skipped steps are extractors** (46 of 49): BARb offered another task
  five times in a row, usually when no free metal spot was near. One was a
  geothermal plant and two a second bot lab that BARb's limit held back.
- **Six minutes are not enough for the long openings.** The commander works
  through 30 structures one at a time, where a human shares them with the
  first constructors. Isthmus `P2` ordered its bot lab as the 18th structure,
  and its wind economy had not paid for it when the game ended; Glitters `P4`
  is the one opening with no factory before first contact.
- **A task that fails at once needs a pause.** In a first run the tidal
  generators of Isthmus `P4` failed the moment they were queued and used up
  their five tries in a second each, and 28 of its 30 steps were skipped. The
  script now waits 2 s times the number of tries before trying a failed step
  again.

### What failure looks like

Script error (one bad token in `opening.as`)
: The log has the file, line and message
  (`opening.as (60, 25) : ERR : Unexpected token '<identifier>'`), then
  `Script: Fix compilation errors!`, and the AI is removed before the game
  starts. The team gives **no orders at all**. The game runs to the end and
  the engine exits with code 0. (Apex saw "near-stock behaviour" in this case
  on its own fork; on this engine the team does nothing.)

AI that cannot be loaded (we broke `interfaceVersion` in `AIInfo.lua` by accident)
: `Error: [FetchSkirmishAILibrary] unknown skirmish AI specified`. Same
  result: an idle team and exit code 0.

Stock BARb checked against our opening
: `reason8 bot check --ai BARb` fails, as it should: the commander's first
  orders were `armmex, armmex, armmex, armwin, armwin`.

`reason8 bot check` reports all three as failures.

### Cost

5-minute game, Reason8 against BARb
: 30 to 36 s wall time with the machine to ourselves, of which about 22 s is
  loading; the simulation runs at about 50 times real time. 33 to 45 s when
  other jobs shared the machine. Peak memory 5.5 GB.

15-minute game
: 55 to 64 s wall time, 26 to 34 times real time, peak memory 5.6 GB.

Building the AI folder
: Under a second; 38 files, 8.5 MB, almost all of it the library.

### Command rate

Commands per minute, counted from the replay of the 15-minute game. This is
BARb's own behaviour: both sides run the same library, and after the opening
the script does nothing.

| Minute  | 1   | 2   | 3   | 4   | 5   | 8    | 10  | 13   | 15   |
| ------- | --- | --- | --- | --- | --- | ---- | --- | ---- | ---- |
| Reason8 | 46  | 74  | 80  | 223 | 669 | 1112 | 613 | 2558 | 925  |
| BARb    | 46  | 44  | 103 | 172 | 437 | 477  | 511 | 968  | 1150 |

The busiest single second had 77 commands (Reason8) and 49 (BARb). An earlier
15-minute game went higher: 3,239 commands in its last minute and 125 in one
second. In a 5-minute game most commands were `MOVE`, `WAIT` and `REMOVE`.

*This is far from a person's rate, and it comes from BARb's unit handling, not
from the opening: the opening itself is 5 build orders in the first minute.
The limits of [ADR 0008](../decisions/0008-play-under-human-like-limits.md)
cannot be met by scripts; they need a change in the library (see
[the governor](#a-command-governor)) or have to be accepted for the layers
BARb still plays.*

The opening's own timing is not human-like either: each order is given 2 to 4
s after the previous structure is finished, one at a time. People queue the
first buildings at once. *So order times of the bot and of humans cannot be
compared directly; compare when things are started or finished.*

## Past the tables

Three pieces of planned work need more than a table fixed before the game:
models that decide from the game state
([ADR 0005](../decisions/0005-learn-decisions-with-their-context.md)), the
action budget of
[ADR 0008](../decisions/0008-play-under-human-like-limits.md), and placement
and other things the scripts cannot see. We compared three routes for them.

Setup for everything measured here: engine `recoil_2026.09.03`, game
`Beyond All Reason test-32018-ad135b9`, Supreme Isthmus v2.1, Reason8 (Armada)
against stock BARb (Cortex), 5 game minutes (9,000 frames), one worker thread.
Each game took 73 to 100 s of wall time while other jobs shared the machine.

### A. Tables that branch on state

Read, not run.

What a table can branch on
: Whatever the scripts see (see
  [What a script can see and do](#what-a-script-can-see-and-do)): the frame,
  own metal and energy, how many of each unit the team has, game and team
  rules parameters (BAR publishes the metal spots there), BARb's sums of the
  enemy's threat and cost by role, and the map's average wind through the
  energy BARb expects from a wind generator.

What fits
: A decision tree or an n-gram whose context includes a few state buckets,
  such as income bands or "has a factory", exported like today's openings.
  Tables have to stay strings decoded when used: 480 openings as nested script
  arrays took minutes to compile.

What cannot be done
: Anything that needs the current wind, the team's line of sight or a list of
  enemy units; any limit on the commands BARb's library sends; placement
  beyond "near this position" and "this metal spot".

*Covers part of the first need only. It costs nothing new to build or keep.*

### B. A bridge to a widget and another process

Measured with a stand-in for a model. One line added to `Main::AiUpdate`,
which BARb runs every 30 frames, sends the frame and the team's metal and
energy income with `ai.CallUI`. A user widget answers: it reads the wind,
writes the request to a file, and returns the reply that a Python process
wrote to another file after the previous call. The Python process polls every
0.5 ms. The widget, the script line and the process are not in the repo.

Calls
: 301 in 5 minutes, one per update, all answered by the widget in the same
  frame.

The outside process
: Answered 300 of 300 requests before the next call. The game ran at about 15
  times real time, so it had about 67 ms; in a real game it has a second.

Cost in the game
: The widget spent 0.19 ms per call on average, 2 ms at most, on reading and
  writing the files.

Files
: User widgets may read only under `LuaUI/` and write only under
  `LuaUI/Config/` and `LuaUI/Widgets/`. Our first try wrote to the write
  folder's root: the sandbox refused, the widget was removed at frame 0, and
  the AI got empty answers for the rest of the game without any script error.

What it sees
: The current wind, which scripts cannot read (0 at frame 0, 1.5 to 19 later).
  Otherwise what the hosting player sees: in our runs the host spectates, and
  `Spring.GetSpectatingState` gave a full view of the map. In a lobby game the
  widget runs on the computer of the player who added the AI, with that
  player's view, which is not the AI team's.

Hangs
: None in the two runs with a widget. One early run hung (see option 2).

Read in the game: `ai.CallRules` reaches only LuaRules gadgets, which live in
the game archive. User widgets are off when the host sets `allowuserwidgets`
to false or turns on anonymous mode. A player would install the AI folder, the
widget and the model's process, and start the process before the game.

*Covers the wind, but not the team's view, not the action budget and not
placement beyond what scripts already pass to BARb. Cheap to build; every
install has three parts, and the game can take the widget away.*

### C. Our own build of BARb's library

Measured. BAR's engine repository
([RecoilEngine](https://github.com/beyond-all-reason/RecoilEngine)) at tag
`2026.09.03` pins BARb as a git submodule: CircuitAI
([rlcevg/CircuitAI](https://github.com/rlcevg/CircuitAI)), commit `f4a6ca3` on
branch `barbarian`, two commits behind its head. The AI is built inside the
engine's CMake tree, which generates the C++ wrapper around the AI interface.
[`ai/native/build.sh`](../../ai/native/build.sh) does every step.

Toolchain
: This machine had no compiler and no root. GCC 13 (the version in BAR's own
  build image), CMake and Ninja came from conda-forge through `micromamba` in
  11 s. Configuring the engine tree needs DevIL and SDL2 even for the AI
  alone; BAR's prebuilt `spring-static-libs` and conda's SDL2 headers satisfy
  it, with the engine's own targets switched off.

Pinned downloads
: The script builds on Linux x86-64 only and stops elsewhere. Everything it
  downloads is checked before it runs: `micromamba` against a SHA-256 in the
  script, the 98 toolchain packages against the SHA-256 of each in
  [`ai/native/toolchain.lock`](../../ai/native/toolchain.lock), the engine and
  `spring-static-libs` against their commits. The engine commit fixes the
  commit of every submodule, BARb included. Another engine tag needs its
  commit as an argument. To change the toolchain, create the environment from
  package names and write the lock again with
  `micromamba list --explicit --sha256`.

Build time
: 4 min 56 s of wall time on 4 cores (18 min of CPU) for the first build; 6
  min 50 s (23 min of CPU) for a clean rerun of the script with the governor.
  Peak memory 1 GB. A change to our own files rebuilds in seconds.

Result
: 8.3 MB after stripping (stock: 8.5 MB), with `libstdc++` linked in like
  stock. conda's default sysroot made it need glibc 2.38, where the engine
  needs 2.27; the script pins the glibc 2.17 sysroot.

Loads next to stock BARb
: Yes. Copied over the library of a `reason8 bot build` folder, it logged
  `Skirmish AI <Reason8-0.1>: 1.6.29`, the stock library's version, and played
  its opening: 27 of 30 commander steps and 13 factory units in 5 minutes, no
  script errors.

Another engine
: The same library, in a `Reason8` folder built from engine
  `recoil_2026.07.04`, loaded in that engine and played. The AI interface did
  not change in between.

Windows
: Not tried. BAR builds its Windows engine on Linux with MinGW, in a public
  image (`ghcr.io/beyond-all-reason/recoil-build-amd64-windows`) next to the
  Linux one; a CI job could use both.

#### A command governor

Every command the library sends goes through one function. The engine hands
the AI a table of callbacks (`SSkirmishAICallback`) in `init` in
`src/AIExport.cpp`. BARb gives unit orders through `CCircuitUnit::Cmd*` (245
call sites) and a few direct calls to the C++ wrapper; all of them end in the
table's `Engine_handleCommand`, and only debug drawing calls the table itself.
The governor ([`ai/native`](../../ai/native)) copies the table, replaces that
one pointer, and counts each unit command the way
`reason8.analysis.apm.ActionCounter` counts a player's: at most one action a
frame, and a command counts only if its unit got no command in the 7 frames
before. In `cap` mode it drops a command that would go over any window of the
30-40 band's budget. A spike setting (`REASON8_GOVERNOR=count` or `cap`)
switches it on; it is off otherwise. It is three added lines in BARb's code
and two new files of about 200 lines.

The governor's counts and the replay's, for the Reason8 team. Two seeds, each
played counting and capped; the opening script drew a different opening (of
the position's five) in each game.

| Game           | Opening |  Sent | Actions | Dropped | Replay: commands | Replay: actions | Most in 1 s | 10 s | 60 s |
| -------------- | ------: | ----: | ------: | ------: | ---------------: | --------------: | ----------: | ---: | ---: |
| seed 1, count  |       2 | 1,565 |     969 |       0 |            1,562 |             946 |          11 |   74 |  345 |
| seed 1, cap    |       3 |   445 |     250 |     377 |              445 |             244 |           8 |   41 |   91 |
| seed 11, count |       2 | 1,410 |     797 |       0 |            1,399 |             776 |          10 |   53 |  262 |
| seed 11, cap   |       4 |   526 |     250 |     387 |              526 |             247 |           7 |   39 |   91 |

"Sent" is what reached the engine; the last three columns are from the replay
(the budget allows 11, 50 and 90).

- **The counts agree with the replay.** Every command the capped governor let
  through is in the replay, and its action count is within 3% of the replay's.
  The replay saw 91 actions in one 60-second window against a cap of 90.
- **The cap holds and costs half of BARb's commands.** Each capped game used
  its whole 5-minute budget of 250 actions, and 45% of the commands BARb sent
  were dropped, all from minute 3 on and most in minutes 4 and 5. Uncapped,
  the Reason8 team took up to 345 actions in a minute.
- **Stock BARb on the other side** took 541 actions in the first counted game:
  by this count it is over a strong player's budget on its own.
- **Effect on play: not known.** No game had script errors. The capped games
  drew late-factory openings (3 and 4) and the counting ones the factory-first
  opening 2, so the openings, not the cap, explain most of the difference in
  what was built. In the seed 1 capped game, the factory was lost at 4:38.

Read in the source: a dropped command returns success, because CircuitAI
treats an error as a broken unit. BARb then believes the unit has its order; a
unit that was idle gets no new idle event and may wait until a task times out.
*Dropping proves the budget can be enforced underneath BARb, not that BARb
plays well under it; the governor has to defer commands, or BARb's tasks have
to plan within the budget.*

#### What a model could use and how it would run

Read from the AI interface (`rts/ExternalAI/Interface/SSkirmishAICallback.h`)
and CircuitAI:

State
: The current wind (`Map_getCurWind`) as well as its range; the team's line of
  sight, air sight and radar maps; enemy units in line of sight or radar, as
  the engine allows without cheats; every unit's command queue; game, team and
  unit rules parameters; and what CircuitAI already keeps: metal spots, the
  threat map, terrain and pathing.

Running a model
: Tables loaded from a data file at start: the library already contains a JSON
  reader (`jsoncpp`), so the export stays data. A runtime such as ONNX Runtime
  is one more library per platform in the AI folder; not tried. A socket to
  another process is possible in native code, but players would have to
  install and start that process.

What has to be rebuilt
: The library for every engine release, from the engine's BARb commit with our
  changes carried over, for Linux and Windows. The scripts still come from the
  game: a game whose scripts call something our library lacks fails to compile
  them, and the team stands still (`reason8 bot check` reports it).

*Covers all three needs. The cost is a fork of CircuitAI to keep current with
each engine release and a build for two platforms.*

### Comparison

A. Tables that branch on state
: *Measured:* nothing new; the scripts' reach was read from the bindings.
  *Needs:* state in part (resources, units, average wind); no budget; no new
  placement. *Build:* nothing new. *Keep working:* as today, rebuilt per
  engine and game. *Install:* one folder.

B. Bridge to a widget and a process
: *Measured:* calls, an outside answer within one update, the widget's cost,
  the file sandbox. *Needs:* adds the current wind, with the host's view
  instead of the team's; no budget; no new placement. *Build:* small, in Lua
  and Python. *Keep working:* follows BAR's widget sandbox, which changed
  since the first measurement. *Install:* folder, widget and process; the host
  can switch widgets off.

C. Own build of the library
: *Measured:* build, load next to stock BARb, the governor counting and
  capping, the library in an older engine. *Needs:* all three. *Build:* a
  toolchain and 5 to 7 minutes per platform. *Keep working:* a fork rebased
  for each engine release, two platforms. *Install:* one folder, as today.

### Recommendation

Build the library ourselves (C) and keep the scripts and their tables on top
of it; the opening hooks need no change. Do not use the bridge (B) for play.
Tables that branch on state (A) stay useful for anything the scripts can see,
in either library.

Next steps, in order:

1. Make the governor defer commands over budget instead of dropping them, and
   compare capped and uncapped games with the same opening.
2. Let `reason8 bot build` take the library from our build instead of the
   engine's, and build Linux and Windows libraries in CI with BAR's images.
3. Pass the first piece of state a model needs (the current wind) from the
   library to the scripts.

## What we learned that the next step needs

1. **Check every run.** Nothing fails loudly. Use the log and the replay.
2. **An order is not a build.** BARb sometimes sends a factory order twice (3
   of 11 games in both versions). The check on orders cannot tell a re-sent
   order from a second unit; the check on what was built can. Judge an opening
   by what was built.
3. **Games are not repeatable.** With the same seed, stock BARb as Cortex
   opened with four wind generators and a bot lab in one game, and with three
   solar collectors and a vehicle plant in another. BARb seeds its own random
   numbers from the clock. Evaluation needs several games per setting.
4. **Placement is shared.** Extractors go on the free spot nearest to where
   the human built them. Other structures get a position from the opening and
   BARb picks the exact site around it.
5. **The parser's `kind` is wrong for AI factories.** An AI's factory orders
   carry a position, so `reason8.replays.replay` labels them `structure`. Tell
   factories from the builder's id, as `reason8 bot check` does.
6. **Use a timeout.** One run never finished (see option 2).
7. **The two replaced scripts follow the game.** When BAR changes `builder.as`
   or `factory.as`, the build stops and the hook lines have to be carried
   over.

## Installing it in a real game

Not tried: we have no graphical BAR install here. What we know:

- Build the folder with `--skirmish-dir` pointing at the BAR install's
  `engine/<version>/AI/Skirmish/`. The data folder's `AI/Skirmish/` worked
  headlessly and may survive engine updates, which replace the engine folder
  (Apex's README says an engine update wipes the AI folder). The library still
  has to match the engine, so rebuild after an update either way.
- BAR's lobby lists every AI the engine finds (`VFS.GetAvailableAIs`), but its
  "Simple AI list" setting, on by default, shows only AIs it knows by name.
  Apex's installer turns the setting off for that reason.
- The lobby sends the short name and no version, so the engine loads the
  highest installed version. Keep one installed.
- The lobby sends AI options to the host only when they are set, and fills in
  a default profile only for the name `BARb`. Our `AIOptions.lua` defaults
  make that unnecessary.
- On Windows the library is `SkirmishAI.dll`; `reason8 bot build` copies
  whatever library the engine's BARb folder holds, but only Linux was run.

## Not covered

- A real lobby, Legion, Rosetta (only Supreme Isthmus and All That Glitters
  were played), and Reason8 next to human players.
- A model that runs during the game. The bridge and our own library were
  measured with a stand-in, not with a model.
- A Windows build of the library, and our library in a real lobby.
- Whether BARb plays worse under the command cap: the capped and uncapped
  games drew different openings.
- Whether queueing one unit at a time really prevents the lost unit; more
  games are needed.
- Saving and loading a game in the middle of an opening.
- Human command rates to compare with; only BARb's were measured.

## Sources

- CircuitAI, branch `barbarian`, commit `e3bebd3`:
  `src/circuit/setup/SetupManager.cpp` and `script/ScriptManager.cpp` (game
  archive first, then the AI's own folder), `util/FileSystem.h` (the game-side
  path is `LuaRules/Configs/<shortName>/<version>/`), `script/*.cpp` (what
  scripts can call), `module/BuilderManager.cpp`, `module/FactoryManager.cpp`,
  `module/EconomyManager.cpp`, `task/builder/MexTask.cpp`
- Beyond All Reason `test-32018-ad135b9`: `luarules/configs/BARb/stable/`,
  `luaai.lua`, `luarules/gadgets/ai_simpleai.lua`, `luaui/barwidgets.lua`
  (widget sandbox, `RecvSkirmishAIMessage`), `modoptions.lua`
- BYAR-Chobby (the lobby), commit `214cb3f`:
  `LuaMenu/widgets/chobby/components/ai_list_window.lua`, `configuration.lua`
- Apex, commit `927ff16c`: `README.md` (installing), `tools/deploy_ai.py`
  (header). Read for ideas; no code copied
- Engine `recoil_2026.09.03`: `AI/Skirmish/BARb/stable/`,
  `AI/Skirmish/NullAI/`
- RecoilEngine, tag `2026.09.03`: `.gitmodules` and the BARb submodule commit,
  `CMakeLists.txt`, `docker-build-v2/` (BAR's build images),
  `rts/ExternalAI/Interface/` (`SSkirmishAICallback.h`, `AISCommands.h`); the
  generated `AI/Wrappers/Cpp/src-generated/CombinedCallbackBridge.c`
- CircuitAI, commit `f4a6ca3`: `src/AIExport.cpp`,
  `src/circuit/CircuitAI.cpp`, `unit/CircuitUnit.h`,
  `module/EconomyManager.cpp` (wind), `script/*.cpp`
- BAR's `spring-static-libs`, branch `18.04`
- Our runs: engine logs and replays of the games described above
