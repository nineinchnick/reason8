# 0007. Ship the model as generated tables in a BARb variant

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

A trained model has to get its decisions into a running game. We compared the
ways to do that, built the most promising one, and later measured the three
routes past it ([`in-game.md`](../reference/in-game.md)):

- A Lua AI is part of the game archive, so it cannot be used in normal lobbies
  without changing the game itself, and it sees the whole map.
- A widget plays a human's slot, needs a game client per bot, and BAR's
  sandbox takes away its network access and, when the host says so, its right
  to give orders.
- A BARb variant under its own short name loads next to stock BARb with no C++
  build. Its AngelScript hooks were enough to make the commander and the first
  factory play a given build order by unit name. In 11 headless games the
  commander's part was complete every time and the factory's part in 10, and
  stock BARb played on afterwards.

For the first milestone the model's output is small and known before the game
starts: one opening per map, side and start position
([ADR 0009](0009-start-with-team-game-openings.md)). The next pieces of work
need more, and the scripts cannot give it:

- Models that decide from the game state
  ([ADR 0005](0005-learn-decisions-with-their-context.md)). Scripts see own
  resources, unit counts, the frame and game rules parameters, but not the
  current wind, line of sight or a list of enemy units.
- The action budget of [ADR 0008](0008-play-under-human-like-limits.md).
  BARb's library sends 400 to 3,000 commands a minute, and scripts cannot
  touch them.
- Placement and anything else the scripts cannot see.

Measured for the routes past the scripts:

- **A bridge from the script to a Lua widget** works in a headless game:
  `ai.CallUI` reached a user widget 301 times in a 5-minute game, and an
  outside process answered every request, through files, before the next call
  a second of game time later. But the widget is a second thing to install, it
  is switched off by the host's `allowuserwidgets` or anonymous mode, it can
  only use files under `LuaUI/Config/`, and it sees what the hosting player
  sees: everything, when the host spectates. It cannot limit BARb's commands
  either.
- **Our own build of BARb's library** (CircuitAI) took under 7 minutes on four
  cores with a toolchain installed without root, loaded as `Reason8` next to
  stock BARb, and played. A command governor of about 200 lines sits in front
  of the one engine callback every command goes through. Counting, it agreed
  with the replay within 2%; capping at the 30-40 band's budget, it kept the
  AI within every window and dropped 45% of BARb's commands. The same library
  loaded in an engine two months older. Holding the commands instead and
  sending them later kept 160 team-games within every window with no command
  lost, at no measurable cost in economy or openings
  ([`command-governor.md`](../research/command-governor.md)). The same sources
  cross-compiled for Windows in BAR's own build image in 6 minutes, and the
  `SkirmishAI.dll` played in the Windows engine as the Linux library does: 48
  teams in 8v8 games within every window, no command lost.

## Decision

Reason8 is installed as a Skirmish AI with the short name `Reason8`. Its
folder is built by `reason8 bot build` from our own build of BARb's library,
the game's BARb scripts and configs for one profile, and the files in
`ai/Reason8`.

The model does not run inside the game. Its predictions are exported offline
to a data file (`ai/Reason8/openings.json`), and the build turns that file
into an AngelScript table that the hooks in BARb's builder and factory scripts
play. When there is no opening, or it is over, BARb decides as before.

Every headless evaluation checks the engine log and the recorded replay with
`reason8 bot check` before its result is used.

### Build the library ourselves

We build BARb's library from source instead of copying the engine's: CircuitAI
at the commit the engine pins for BARb, plus our changes in `ai/native`, built
for the tag of the engine the AI is installed into. `reason8 bot build` builds
it, or reuses the build for that tag, and the library checks at start that it
runs in the engine it was built for. Our changes are:

- the command governor, which keeps every command the AI sends within the
  action budget of [ADR 0008](0008-play-under-human-like-limits.md) by holding
  what does not fit and sending it later, in order;
- the live state for the scripts: the current wind, the team's stored metal
  and energy with storage, income and expense, and its finished units by name,
  read from the engine when a script asks, and the frame of the team's first
  contact, kept from the engine's unit-damaged events.

The scripts and the opening tables stay as they are and run on top of it.
Models run inside the library or its scripts: first as tables loaded from a
data file, a runtime such as ONNX only when a model needs it, and no second
process. The widget bridge is not used for play.

The library is built for the platform of the engine it goes into, from the
same sources: Linux x86-64 with a pinned toolchain, Windows x86-64
(`SkirmishAI.dll`) cross-compiled in BAR's own Windows build image, pinned by
the digest the engine release used. Both builds run on Linux. Where neither
can be built, the engine's own library can be installed instead
(`--library stock`): the AI plays its openings, without the command budget and
with the live state unknown.

## Consequences

- No change to the game: only the player who adds the bot needs the AI
  installed. Installing stays one folder.
- The AI folder is tied to one engine version (the library) and one game
  version (the scripts), so it is rebuilt when either changes. A library built
  for another engine tag stops the build and logs a mismatch at run time; the
  build stops when a BARb script we replace has changed upstream.
- The action budget is enforced on every command BARb's library sends, and
  BARb keeps playing under it, because a held command is sent later instead of
  being lost.
- The scripts see the current wind, the team's economy and what it has
  standing at the moment they decide, so wind generators can be judged from
  the wind that blows, not only from the map's average. A model can read more
  of what the AI interface gives a team (line of sight and radar, enemy units
  in them, unit queues) by adding a binding in `ai/native`.
- Extractors still go on the human player's spots through the game rules BAR
  publishes (`mex_count`, `mex_x1`, ...); other buildings are placed by BARb
  near a position the opening gives.
- A wrong script or a missing AI does not stop the game; the team just stands
  still. That is why the log and replay check is mandatory.
- We keep a fork of CircuitAI current with the engine: on each engine release,
  move to the engine's BARb commit, carry our changes over (two new pairs of
  files and two small patches) and build both platforms. BAR's public build
  images do that for the engine itself; a GitHub Actions job could use them.
- Windows players need the `SkirmishAI.dll` we build; it is built on Linux, so
  a release of the AI folder for Windows is made there too.
- Revisit if keeping the fork current costs more than an engine release
  allows, or if BAR's scripts gain bindings for wind, line of sight and
  command limits, which would make the scripts enough.
