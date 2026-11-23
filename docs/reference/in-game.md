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
- **The model does not have to run inside the game yet.** For openings its
  output is known before the game starts, so it is exported to a data file and
  compiled into a script table.
- **Failures are silent.** A missing AI or a script error leaves the team
  standing still while the game runs on and exits normally. Every result has
  to be checked against the log and the replay, and there is a tool for it.
- **BARb is not human-like in how often it gives orders**: 40 to 700 commands
  a minute in the first five minutes, peaks of 1,100 to 3,200 a minute later,
  and up to 125 in one second. The scripts cannot change that.

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
  arrive.* (b) A C++ build of the AI (CircuitAI) that runs the model itself or
  talks to another process, which is what Apex does
  ([`related-work.md`](../research/related-work.md)). *Not tried.*

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
  leaves file access under the game's write folder (*measured: a file could be
  written*). So a user widget reaches another process through files only. The
  host can also switch user widgets off (`allowuserwidgets`). (b) One folder,
  but a library to build for Windows and Linux against each engine version.

Headless test
: Same runner; `--widget` installs the widget.

Limits
: (a) In one of three runs that had the test widget installed, the engine
  stopped advancing after frame 289 and had to be killed. The run that hung
  and one that finished both made the call; we could not reproduce it, so we
  do not know the cause. Treat the bridge as unproven. The test widget and the
  one-line script change are not in the repo.

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
: The openings, as data. For each side: the structures the commander builds
  and the first units of each factory, by unit name. A separate `tasks` map
  says which BARb task type builds each structure. This is the file a trained
  model's export will write. The openings in the repo are deliberately
  unusual, so that a game shows at once whether they were played.

`script/hard/reason8/opening.as`
: The logic, about 300 lines of AngelScript. It picks the opening for the AI's
  side and gives the commander one build task per step and the factory one
  task per unit, moving on when a task is done and trying again when it fails.

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
    "armrad": "radar",
    "armwin": "energy"
  },
  "openings": [
    {
      "side": "armada",
      "commander": [
        "armwin",
        "armwin",
        "armmex",
        "armrad",
        "armlab"
      ],
      "factories": {
        "armlab": [
          "armrectr",
          "armjeth",
          "armjeth",
          "armck",
          "armham"
        ]
      }
    }
  ]
}
```

Stock BARb opens with four extractors, then wind generators, then a factory
whose first unit is a constructor or a scout. The opening above starts with
two wind generators, builds a radar in the first minute, and makes a
resurrection bot and two anti-air bots first.

`reason8 bot build` puts the AI folder together from three sources:

1. the engine's own `AI/Skirmish/BARb/stable/`: the library, unchanged;
2. the installed game's `luarules/configs/BARb/stable/`: BARb's scripts and
   configs for the `hard` profile, read from the game package;
3. `ai/Reason8`, on top, with `openings.json` turned into
   `script/hard/reason8/opening_table.as`.

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
: A script cannot create an extractor task, because that needs a metal spot
  and scripts cannot see metal spots. For a `mex` step the script asks BARb
  for its default task and accepts it only if it is an extractor of the
  ordered type. In every game BARb offered one at the first try.

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
: Every decision is logged with the prefix `Reason8 opening:`.

```
Reason8 opening: team 0, side 'armada', map 'Supreme Isthmus v2.1': 5 commander steps, 1 factories
Reason8 opening: step 1 armwin: task queued, frame 25
Reason8 opening: step 1: finished, frame 265
Reason8 opening: step 3 armmex: BARb's extractor task, frame 569
Reason8 opening: lifting BARb's timer on armrad (was 120 s)
Reason8 opening: step 5: finished, frame 1641
Reason8 opening: commander steps done at frame 1641, BARb takes over
Reason8 opening: factory armlab: will make armrectr armjeth armjeth armck armham, frame 1641
Reason8 opening: factory unit 1 armrectr: task queued, frame 1661
Reason8 opening: factory unit 1: done, frame 2263
Reason8 opening: factory units done at frame 4177, BARb takes over
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
: Read files, open sockets, read a clock, list enemy units, or see metal
  spots.

*So the start position needed for per-position openings is available: the map
name and the commander's position at frame 0. The opening script logs the map
name already and matches on the side only.*

## How to run it

All paths are arguments; nothing under `data/` is committed. `data/bar` is the
content folder made by `reason8 headless setup`
([`state-extraction.md`](../research/state-extraction.md)).

```sh
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

Step 1 can instead make a copy of the engine with the AI inside
(`--engine-copy data/bar/engine-variants/reason8`, then
`--engine-dir data/bar/engine-variants/reason8` in step 2). The shared engine
folder is never changed.

`AI0` and `AI1` hold everything that identifies an AI in the start script.
Leaving `Version` out is what a lobby does.

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

Eleven games of Reason8 against stock BARb: ten of 5 minutes and one of 15
(seed 21). Odd seeds have Reason8 as Armada, even seeds as Cortex. Each
recorded game was played again with state export up to frame 7,500 (250 s),
and `reason8 bot check` compared what was built with the opening. "Done" is
the second the last listed structure or unit was finished.

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
cannot be met by scripts; they need a change in the library or have to be
accepted for the layers BARb still plays.*

The opening's own timing is not human-like either: each order is given 2 to 4
s after the previous structure is finished, one at a time. People queue the
first buildings at once. *So order times of the bot and of humans cannot be
compared directly; compare when things are started or finished.*

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
4. **Extractors are BARb's choice.** The opening says when, BARb says where.
   Placing other structures is also BARb's: the script gives a position near
   the commander and BARb picks the spot.
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

- A real lobby, a team game, more than one Reason8 on a team, Legion.
- Openings chosen by map and start position (the script matches the side
  only).
- A model that runs during the game. The script-to-widget call was shown once
  and one run hung; a C++ build was not tried.
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
- Our runs: engine logs and replays of the games described above
