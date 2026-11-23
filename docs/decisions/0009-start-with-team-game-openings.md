# 0009. Start with team-game openings per start position

- **Status:** Accepted
- **Date:** 2026-11-23

## Context

The proof of concept has to be small enough to test end to end. On popular
team maps such as Supreme Isthmus each start position has an established
opening meta ([`maps/`](../research/maps/README.md)), and the opening is the
part of a game a bot can play from a plan made before the game starts. Large
Team (8v8) is the biggest queue, and one 8v8 game holds 16 openings.
Whole-game decisions are easier to learn from 1v1, where one player makes
every decision.

## Decision

The first milestone learns the opening for each start position on popular team
maps and has a bot play it in team games; BARb takes over after the opening.
Whole-game macro is learned from 1v1 games in milestone 2. PvE modes
(Scavengers, Raptors) and free-for-all games are out of scope for now.

## Consequences

- Start positions need one definition, per map
  ([ADR 0011](0011-take-positions-from-the-map-metadata.md)), and so does
  where an opening ends ([ADR 0012](0012-end-openings-at-first-contact.md)).
- The opening is learned with its context
  ([ADR 0005](0005-learn-decisions-with-their-context.md)), so even the first
  milestone re-simulates a sample of games.
- Success is measured on one map, Supreme Isthmus
  ([ADR 0003](0003-define-success-as-in-game-measures.md)); the other maps of
  the slice test how far the models carry.
- Team play (help requests, raids, captain requests) becomes part of the goal
  for later milestones.
