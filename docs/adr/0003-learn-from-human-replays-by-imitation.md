# 0003. Learn from human replays by imitation

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

BAR's own AI, BARb, plays from hand-written rules and tables. Writing better
rules by hand doesn't scale, and learning from game outcomes needs far more
games than one person can simulate: Apex, a BARb fork, tried several
outcome-driven methods and found that telling a 10% difference in game score
apart takes about 1,100 paired games
([`related-work.md`](../related-work.md)). Meanwhile hundreds of thousands of
public human replays exist, with match metadata and player ratings
([`dataset.md`](../dataset.md)).

## Decision

Train models to predict what a good human player does next in a given
situation (imitation learning, or behavioural cloning) from public replays of
human games. Offline RL and self-play come later, only after imitation works
(see the roadmap in the README).

## Consequences

- Every decision in a replay is a labelled example, so far fewer games are
  needed than for learning from wins and losses.
- We need a replay pipeline: selection, polite download, parsing, and later
  re-simulation for game state.
- Models are evaluated first by how often they predict the human's choice on
  unseen games, against a simple baseline, not by win rate.
- The bot can only be as good as the players it learns from, so the data is
  filtered by skill.
