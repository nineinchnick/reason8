# 0013. Evaluate on held-out games, one step per decision

- **Status:** Accepted
- **Date:** 2026-11-23

## Context

Models of the opening will be compared for a long time: counting baselines
first, learned models later. The comparison only means something if every
model is scored the same way, on the same games, with the noise known. It is a
development metric that picks which models are worth playing in the game;
whether the bot succeeds is measured there
([ADR 0003](0003-define-success-as-in-game-measures.md)).

What shapes the protocol:

- The dataset ([ADR 0012](0012-end-openings-at-first-contact.md)) keeps every
  build order of an opening. About half of them repeat the order before them
  in the same frame: one drag of the mouse places a line of buildings.
  Predicting the 20th wind turbine of a drag from the 19th is free and says
  nothing about the player's decisions; on raw orders the faction trigram
  scores 59% top-1, on merged steps 47% ([`results.md`](../results.md)).
- An opening has a median of 33 to 39 steps once drags are merged, and some
  have hundreds of orders. Scoring every step lets the longest openings decide
  the result.
- The 16 openings of a game share a lobby, a version and the players'
  reactions to each other, so steps and openings are not independent; games
  are.
- Accuracy alone hides how sure a model is. The bot will play one opening per
  position, but a model that later samples, or a mixture of models, needs
  calibrated probabilities.
- [ADR 0015](0015-train-across-balance-patches.md) asks for accuracy per
  opening era; the milestone asks for it per map and position.

## Decision

A model predicts the unit of the **next step** of an opening from the steps
before it and what is known before the game: faction, map, start position and
its role. A step is one order, with the orders that repeat its unit in the
same frame merged into it (`step_starts()` in `reason8.openings.dataset`,
which every model, the evaluation, the decision table and the bot's export
use). Scoring is `reason8.models.evaluate`, run by `reason8 baseline`.

- **Scored steps:** the first 30 steps of every opening of the held-out split,
  off-spot starts included (their position is the nearest spawn point). An
  opening that ends at first contact before its 30th step is scored whole.
- **Metrics:** top-1 and top-3 accuracy, and log-loss in nats. A model must
  give every unit a probability above zero, including units it never saw (one
  shared "unknown" entry). When the true unit ties with others, the ties rank
  above it.
- **Noise:** 95% intervals from 1,000 bootstrap draws of whole games;
  differences between two models are paired (the same draws for both).
- **Breakdowns:** by step (1, 2–5, 6–10, 11–20, 21–30), map, faction, opening
  era, and map and position, each with its number of games and steps.
- **Selection:** models are compared and chosen on the validation split, by
  log-loss. The test split is scored once per reported model, and those are
  the numbers in [`results.md`](../results.md). A new model is compared with
  the best baseline on the same dataset version and split.
- **Raw orders** are scored once, with the faction trigram, only to connect
  with earlier measurements.
- **Saved models** carry what they were trained on (`TrainedOn`: first and
  last build, the units they can order) and the dataset's manifest, and are
  checked with `check_game_version()` before use.

## Consequences

- Drags no longer inflate accuracy, and a model is not rewarded for guessing
  the length of a drag. How many buildings a drag places is not predicted at
  all; the in-game export has to choose that separately.
- The counting baselines set the bar: the repeat baseline already scores 40%
  top-1 and the chosen n-gram (4-gram, faction, map and position) 51.2% on
  test ([`results.md`](../results.md)).
- Intervals over games make small maps and positions honest: a position of
  Rosetta has about 110 openings in a held-out split of the whole slice.
- Choosing on validation and reporting test keeps the test numbers unbiased,
  as long as nobody tunes on test.
- Models that see the game state
  ([ADR 0005](0005-learn-decisions-with-their-context.md)) are scored the same
  way on the same games, so the gain from each kind of context is measured
  against these baselines.
