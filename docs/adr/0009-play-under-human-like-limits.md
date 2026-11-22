# 0009. Play under human-like limits

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

An AI can win by seeing everything or acting faster than any person, which
makes it neither a fair opponent nor a good teammate. AlphaStar is the main
lesson here. Imitation of humans also only makes sense if the bot acts on the
same information people have.

## Decision

The bot plays under the same limits as people: only what it can see, human
command rates (including bursts), reaction time and limited attention. It
should win by decisions, not by speed or extra information. This holds for
every milestone, including any later reinforcement learning.

## Consequences

- Game state used for training has to be what the player could see, not the
  spectator's full view (line of sight per ally team).
- The in-game side needs explicit limits on command rate and reaction time.
- Evaluation must check that the bot stays within these limits.
