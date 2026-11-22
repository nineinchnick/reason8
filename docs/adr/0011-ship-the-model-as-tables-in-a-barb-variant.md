# 0011. Ship the model as generated tables in a BARb variant

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

A trained model has to get its decisions into a running game. We compared five
ways to do that and built the most promising one
([`in-game.md`](../in-game.md)):

- A Lua AI is part of the game archive, so it cannot be used in normal lobbies
  without changing the game itself, and it sees the whole map.
- A widget plays a human's slot, needs a game client per bot, and BAR's
  sandbox takes away its network access and, when the host says so, its right
  to give orders.
- An own native AI can do anything, but has to be written from scratch and
  built for every platform and engine version.
- A BARb variant under its own short name loads next to stock BARb with no C++
  build. Its AngelScript hooks were enough to make the commander and the first
  factory play a given build order by unit name. In 11 headless games the
  commander's part was complete every time and the factory's part in 10, and
  stock BARb played on afterwards.

For the first milestone the model's output is small and known before the game
starts: one opening per map, side and start position
([ADR 0005](0005-start-with-team-game-openings.md)).

## Decision

Reason8 is installed as a Skirmish AI with the short name `Reason8`. Its
folder is built by `tools/variant/build.py` from the engine's own BARb
library, the game's BARb scripts and configs for one profile, and the files in
`ai/Reason8`.

The model does not run inside the game. Its predictions are exported offline
to a data file (`ai/Reason8/openings.json`), and the build turns that file
into an AngelScript table that the hooks in BARb's builder and factory scripts
play. When there is no opening, or it is over, BARb decides as before.

Every headless evaluation checks the engine log and the recorded replay with
`tools/variant/check_opening.py` before its result is used.

## Consequences

- No C++ build and no change to the game: only the player who adds the bot
  needs the AI installed.
- The AI folder is tied to one engine version (the library) and one game
  version (the scripts), so it is rebuilt when either changes. The build stops
  when a BARb script we replace has changed upstream.
- The scripts see only what BARb exposes to them. Metal spots are not exposed,
  so the opening says *when* to build an extractor and BARb picks *where*.
- A wrong script or a missing AI does not stop the game; the team just stands
  still. That is why the log and replay check is mandatory.
- BARb's own command rate (hundreds to thousands of commands a minute, up to
  125 in one second) is outside the scripts' reach, so the limits of
  [ADR 0009](0009-play-under-human-like-limits.md) are not met by this path
  alone.
- A model that needs the game state at decision time (milestone 2) cannot be a
  table. Revisit then: the choice is between a script-to-widget bridge, which
  we measured once, and a C++ build of the AI.
