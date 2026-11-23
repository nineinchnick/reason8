# 0017. Define openings by time and split games by match id

- **Status:** Accepted; superseded in part by
  [0019](0019-end-openings-at-first-contact.md): an opening ends at first
  contact, the 8 minutes are the upper limit
- **Date:** 2026-11-22

## Context

The first milestone learns openings per start position
([ADR 0005](0005-start-with-team-game-openings.md)) from build orders read
straight from replay commands
([ADR 0007](0007-read-build-orders-from-replay-commands.md)). The dataset, the
baselines and later models need one definition of what an opening is and one
way to hold games out.

What we know about the orders
([`openings-dataset.md`](../openings-dataset.md),
[`replay-format.md`](../replay-format.md)):

- A player gives a median of 80 to 112 build orders in the first 8 minutes,
  depending on the map, and up to several hundred. One shift-drag places a
  whole line of buildings: about half of all orders repeat the unit of the
  order before them in the same frame. Without those repeats a median opening
  has 48 to 63 steps.
- An order is an intention. It can be replaced, taken out of a factory queue,
  or never built; the replay says how it was given (`via`, shift, insert,
  factory quota widget, the count of a factory order), not what was finished.
- The measurements of the opening meta and of balance patches
  ([`maps/`](../maps/README.md), [`game-versions.md`](../game-versions.md))
  used the first 8 minutes. The first factory, the strongest part of the meta,
  is ordered well inside them.
- The 16 openings of a game are not independent: the players share a game
  version and a lobby and react to each other.
- Replays are downloaded in a fixed random order per map
  ([ADR 0013](0013-download-replays-in-a-fixed-random-order-per-map.md)) and
  parsed over days, so the dataset is built many times from a growing part of
  the slice.

The options for the opening were a number of orders (the first N), a time (the
first M minutes), or an event (up to the first factory, or to the first order
of the second tier). For held-out games: a random split of rows, a split by
time, or a split of whole games.

## Decision

An **opening** is every build order a player gives in the first 8 minutes of
game time (frame 14,400 and earlier), the pregame queue included, in the order
of the replay (`reason8.openings.opening_orders()`). The dataset keeps every
one of them as a row, including orders that take units out of a factory queue
and orders that were replaced later, with how each was given. The sequence a
model predicts is the orders that add a unit, numbered by `seq_idx`; telling
"ordered" from "probably built" is left to whoever uses the rows, and does not
need a rebuild.

Games are **split as a whole** into train (80%), validation (10%) and test
(10%) by their match id alone: the first 8 bytes of
`sha256("reason8-openings-split/<match id>")` as a number, modulo 100. The
lists of match ids are written next to the dataset. Model choices are made on
validation; test is used only for the numbers a model is reported with.

The dataset lives in `data/datasets/openings_v1/` and is built by
`python -m reason8.opening_dataset`, which records what went in
(`manifest.json`). It follows ADR 0012 and ADR 0015 for what is left out and
what is flagged; the columns and the rules are in
[`openings-dataset.md`](../openings-dataset.md).

## Consequences

- A cut by time is the same for every player, whatever they drag; a cut by
  count would end a dragged opening after a few seconds. Models that want
  fewer steps cut further (the first N steps, repeats merged) without changing
  the dataset.
- Splitting by match id keeps the players of one game together, and a game's
  split never changes as more replays are parsed or the dataset is rebuilt:
  later models are compared on the same held-out games.
- The split is not by time, so validation and test have the same mix of game
  versions as training. A model's accuracy on games after a new patch is
  measured separately (ADR 0012).
- Rosetta has about 1,100 games in the slice, so its validation and test
  splits have about 110 games each; results there have wide intervals.
- About half the rows are repeats of a drag, and the whole slice will have
  about 85 million rows. The files are sorted by match, player and order, and
  read lazily.
- A different window or definition is a new dataset (`openings_v2`), not a
  rebuild of this one.
- Revisit when the bot needs to know where an opening ends (an event rather
  than a time), when finished builds from re-simulated replays
  ([ADR 0002](0002-recover-game-state-by-re-running-replays.md)) can replace
  orders, or when a model needs more than 8 minutes.
