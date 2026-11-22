# 0005. Start with team-game openings per start position

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

The proof of concept has to be small enough to test end to end. On popular
team maps such as Supreme Isthmus each start position has an established
opening meta, and build orders can be read straight from replay commands
without re-simulating the game. Large Team (8v8) is the biggest queue, and one
8v8 game holds 16 openings. Whole-game decisions are easier to learn from 1v1,
where one player makes every decision.

## Decision

The first milestone learns the opening build order for each start position on
popular team maps and has a bot play it in team games; BARb takes over after
the opening. Whole-game macro is learned from 1v1 games in milestone 2. PvE
modes (Scavengers, Raptors) and free-for-all games are out of scope for now.

## Consequences

- The PoC needs no game state, only commands and metadata.
- Start positions have to be recovered from replays, per map.
- Team play (help requests, raids, captain requests) becomes part of the goal
  for later milestones.
