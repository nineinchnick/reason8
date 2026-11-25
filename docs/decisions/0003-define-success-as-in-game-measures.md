# 0003. Define success as in-game measures

- **Status:** Accepted
- **Date:** 2026-11-23

## Context

Reason8 is meant to play like a strong human teammate
([README](../../README.md)). Models are trained to predict what players did
([ADR 0004](0004-learn-from-human-replays-by-imitation.md)), and the first
ones are scored on how often they predict the next build of held-out openings
([ADR 0013](0013-evaluate-on-held-out-games.md)). That says how well a model
imitates the replays, not whether the bot plays well: a model can be right
about most steps and still play an opening that falls apart in the game, and
BARb decides much of what happens after a table says what to build
([ADR 0007](0007-ship-the-model-as-tables-in-a-barb-variant.md)).

Win rate is the obvious in-game measure, but it is too noisy for the number of
games one machine can run. Apex, a BARb fork, ran an A/A test (the same AI on
both sides) and found that telling a 10% change in game score apart takes
about 1,100 paired games, against 28 pairs for "metal produced by minute 16"
([`related-work.md`](../research/related-work.md)). An 8v8 game takes minutes
of a core and gigabytes of RAM to simulate headlessly
([`state-extraction.md`](../research/state-extraction.md)).

## Decision

The first milestone succeeds when, on Supreme Isthmus 8v8:

1. **Human-like openings:** a classifier cannot tell the openings the Reason8
   bot plays from human openings at the same start position. It is trained on
   the openings of both and tested on games it has not seen; the bot passes
   when the classifier does no better than chance within its interval.
2. **Economy at least BARb's:** at first contact
   ([ADR 0012](0012-end-openings-at-first-contact.md)), the bot's economy
   (metal and energy income, and the value of what it has built) is at least
   that of stock BARb at the same position. It is measured over N headless
   games, each played twice with the sides swapped, on the same seeds; N is
   set by an A/A test of stock BARb against itself. That test found 3 to 11
   seeds enough to see a 10% difference, so N is 30 seeds, 60 games
   ([`evaluation.md`](../reference/evaluation.md#the-aa-test)).

Prediction accuracy on held-out replays is a development metric: it compares
models quickly and picks which ones are worth playing, but it is not the goal.
Win rate is reported when there are enough games, not used to decide.

## Consequences

- Every model that is a candidate for the bot is played in the game, not only
  scored on replays. The headless runs, the state export and the opening check
  ([ADR 0010](0010-re-simulate-replays-headlessly-for-game-state.md),
  [`in-game.md`](../reference/in-game.md)) become the evaluation harness.
- The state export has to record each team's economy at first contact, and an
  A/A run of stock BARb comes before the first comparison.
- The opening classifier needs held-out human openings per position; the
  dataset's test split ([ADR 0012](0012-end-openings-at-first-contact.md))
  provides them.
- Later milestones add their own in-game measures (economy at fixed minutes,
  team play), in the same style: a measure that a few dozen games can settle.
- Revisit when Supreme Isthmus stops being a main map, or when the bot plays
  beyond the opening and economy at first contact no longer says enough.
