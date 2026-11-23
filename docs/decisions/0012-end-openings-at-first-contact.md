# 0012. End openings at first contact and split games by match id

- **Status:** Accepted
- **Date:** 2026-11-23

## Context

The first milestone learns openings per start position
([ADR 0009](0009-start-with-team-game-openings.md)) from the build orders in
replay commands ([ADR 0005](0005-learn-decisions-with-their-context.md)). The
dataset, the baselines and later models need one definition of what an opening
is and one way to hold games out.

What we know about the orders
([`openings-dataset.md`](../reference/openings-dataset.md),
[`replay-format.md`](../reference/replay-format.md)):

- A player gives a median of 80 to 112 build orders in the first 8 minutes,
  depending on the map, and up to several hundred. One shift-drag places a
  whole line of buildings: about half of all orders repeat the unit of the
  order before them in the same frame.
- An order is an intention. It can be replaced, taken out of a factory queue,
  or never built; the replay says how it was given (`via`, shift, insert,
  factory quota widget, the count of a factory order), not what was finished.
- The first factory, the strongest part of the opening meta, is ordered well
  inside the first 8 minutes ([`maps/`](../research/maps/README.md)).

An opening can only be told apart from the rest of the game until the player
meets the enemy. After that, orders answer raids, losses and what teammates
ask for, and none of those causes is in the commands. We played the first 12
minutes of 72 slice games again headlessly
([ADR 0010](0010-re-simulate-replays-headlessly-for-game-state.md)) and wrote
down every first hit between two enemy units
([`first-contact.md`](../research/first-contact.md)):

- A player's units other than scouts are first hit by an enemy unit after a
  median of 4:08 on All That Glitters, 3:20 on Rosetta and 4:40 on Supreme
  Isthmus. 33%, 44% and 31% of the build orders of the first 8 minutes are
  given after that.
- It depends on where the player starts. Front positions are hit after 2 to
  4.5 minutes, air and sea positions after 4 to 5; most tech positions are not
  hit within 8 minutes. Within a front position the middle half of the players
  is 1 to 1.5 minutes apart.
- The other ways of saying "contact" that we measured (any hit given or taken,
  scouts included, the first unit lost, 500 damage taken) move the median by
  about a minute in either direction.
- Most games of the slice are not re-simulated yet.

The 16 openings of a game are not independent: the players share a game
version and a lobby and react to each other. Replays are downloaded in a fixed
random order and parsed over days
([ADR 0016](0016-download-and-store-the-data.md)), so the dataset is built
many times from a growing part of the slice.

## Decision

An **opening** is the build orders a player gives up to their **first
contact** with the enemy, and at most those of the first 8 minutes of game
time (the opening window), the pregame queue included, in the order of the
replay (`reason8.openings.extract.opening_orders()`).

**First contact** is the first frame in which a unit of the player, other than
a scout, is damaged by a unit of an enemy player
(`reason8.openings.contact.first_contact()`). Scouts are the units built to
look (`reason8.openings.contact.SCOUTS`).

Where an opening ends, in this order
(`reason8.openings.contact.opening_cutoff()`):

1. **Measured:** the game was re-simulated, and the opening ends at the
   player's own first contact.
2. **By position:** otherwise it ends at the median first contact measured for
   the map and the start position, the two mirrored positions of a map taken
   together (`POSITION_CUTOFF_SECONDS`, written from the measurements).
3. **Window:** on a map without measurements it ends with the opening window.

The dataset keeps every order of an opening as a row, including orders that
take units out of a factory queue and orders that were replaced later, with
how each was given. The sequence a model predicts is the orders that add a
unit, numbered by `seq_idx`. Every opening and row carries the frame its
opening ends at and which of the three rules decided it (`cutoff_frame`,
`cutoff_source`).

Games are **split as a whole** into train (80%), validation (10%) and test
(10%) by their match id alone: the first 8 bytes of
`sha256("reason8-openings-split/<match id>")` as a number, modulo 100. The
lists of match ids are written next to the dataset. Model choices are made on
validation; test is used only for the numbers a model is reported with.

The dataset is `openings_v2` in `data/datasets/`, built by `reason8 dataset`,
which records what went in (`manifest.json`). The window and the cutoff are
parameters of the builder; `--cutoff window` builds the 8-minute openings
(`openings_v1`) again.

## Consequences

- The orders kept are the ones a commands-only model can be expected to
  predict: 66% of the orders of the 8-minute window. An opening has a median
  of 33 to 39 steps once drags are merged, and 68% of the openings reach the
  30 scored steps of [ADR 0013](0013-evaluate-on-held-out-games.md), so the
  later steps are scored mostly on back positions.
- A cutoff by position is an estimate: 8 to 11% of the orders it keeps were
  given after the player's own contact, and 8 to 16% of the orders given
  before it are dropped. Every re-simulated game replaces the estimate with a
  measurement, and the table is rewritten from `reason8 contact --report` as
  the sample grows.
- Contact is damage. A player who has only seen the enemy, or who was asked
  for help by a teammate under attack, counts as not yet in contact; what a
  player could see is not recorded yet.
- Splitting by match id keeps the players of one game together, and a game's
  split never changes as more replays are parsed: later models are compared on
  the same held-out games. The split is not by time, so validation and test
  have the same mix of game versions as training; accuracy after a new patch
  is measured separately ([ADR 0015](0015-train-across-balance-patches.md)).
- Rosetta has about 1,100 games in the slice, so its validation and test
  splits have about 110 games each; results there have wide intervals.
- The in-game side has the same boundary: the opening it plays ends at the
  position's cutoff or when its own units are first hit, whichever comes
  first, and hands over to BARb's reactive logic
  ([`in-game.md`](../reference/in-game.md)).
- The measurements of the opening meta and of balance patches
  ([`maps/`](../research/maps/README.md),
  [`game-versions.md`](../research/game-versions.md)) were made on the
  8-minute window.
- A different definition is a new dataset version, not a rebuild of this one.
- Revisit when the whole slice is re-simulated (then every opening is cut at
  its own contact and the table is only needed in the game), when the state
  export records what each player could see, or when a model is given the
  state and can learn the answers too.
