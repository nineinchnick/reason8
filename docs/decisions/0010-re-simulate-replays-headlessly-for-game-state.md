# 0010. Re-simulate replays headlessly for game state

- **Status:** Accepted
- **Date:** 2026-11-23

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

## Decision

Recover game state by re-running each replay in `spring-headless` with a
spectator widget that writes snapshots and events
(`reason8/headless/widgets/reason8_state_export.lua`): each team's resources
and the wind per snapshot, units created, finished, destroyed and given, the
first hit of each unit by an enemy, and damage per second between teams.
`reason8 headless run` plays one replay and `reason8 headless batch` many.

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
- The state is the spectator's full view. Line of sight per player must be
  recorded before the state is used for training
  ([ADR 0008](0008-play-under-human-like-limits.md)).
- Revisit if a replay stops re-simulating exactly, or if per-replay cost makes
  the needed part of 8v8 games too expensive even in the cloud.
