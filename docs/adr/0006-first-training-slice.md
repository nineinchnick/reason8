# 0006. First training slice

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

BAR's public match dumps hold over 1.5 million games
([`dataset.md`](../dataset.md)). Two maps dominate ranked Large Team, and a
third is far ahead of the rest. Lobbies are mixed in skill: requiring a
top-500-level lobby average leaves under 4k games. Skill levels also differ
between maps. Replays older than about 2023 no longer download.

## Decision

The first slice, implemented as the defaults of
`reason8.match_dumps.select_matches()`:

- ranked Large Team games with exactly two teams of 8;
- on Supreme Isthmus v2.1, All That Glitters v2.2.3 and Rosetta 1.4.4 (exact
  map versions);
- from the last 182 days of the dump;
- at least 10 minutes long, with nobody leaving in the first 10 minutes;
- lobby average skill at or above that map's median;
- with a replay file.

Strong players are picked out per player, by leaderboard level, for weighting
or an evaluation set, rather than by filtering whole lobbies.

## Consequences

- About 43k games and 687k openings, enough for per-position models on the two
  big maps; Rosetta is small but tests generalisation.
- The slice spans several engines and about 200 game versions, which matters
  once replays are re-simulated (ADR 0002).
- Selections are reproducible only with explicit `since`/`until`; the default
  window moves with each dump rebuild.
