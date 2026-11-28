# 0018. Learn from orders joined with the state just before them

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

Models are to decide from the game state as well as from the orders before
([ADR 0005](0005-learn-decisions-with-their-context.md)). The state comes from
re-simulating replays
([ADR 0010](0010-re-simulate-replays-headlessly-for-game-state.md)): every
second each team's resources and the wind, and a line for every unit created,
finished, given and destroyed and every builder that runs out of orders.
Before re-simulating the whole slice, a sample of a few thousand games
measures what the state adds over the order-only baselines
([`results.md`](../results.md)).

The first learned model decides for every unit with build power what it does
next, a unit to build or a job, and takes that builder and the team's build
power and the player's skill as inputs
([ADR 0019](0019-first-model-decides-each-builders-next-order.md)). The
commands of a replay say which units each order went to: a clicked command
goes to the player's selection, a widget's command lists its units. The
re-simulated game says what those units were, and the game's unit files what
each type can build and do.

A model only helps the bot if the bot can read the same inputs while it plays.
Our own build of BARb's library reads, through the engine's AI interface, the
team's resources, the current wind, the team's and its allies' units, and
enemy units in line of sight or radar
([ADR 0007](0007-ship-the-model-as-tables-in-a-barb-variant.md)). The bot
plays only on what a player could see
([ADR 0008](0008-play-under-human-like-limits.md)), and only the games
re-simulated in state format 7 record what each team could see. An opening, as
the dataset defines it, ends at first contact
([ADR 0012](0012-end-openings-at-first-contact.md)), before the enemy matters
much.

The join was checked against the state tables and against the units that built
what was ordered, and the measurement of what each kind of state adds is in
[`context.md`](../research/context.md).

## Decision

Models of the opening learn from and are scored on the **decision table**
(`reason8 context build`,
[`context-dataset.md`](../reference/context-dataset.md)):

- **The rows are the orders players gave their builders** in the openings of
  the re-simulated games: the build orders of `openings_v2`, with the same
  openings and splits, and the job orders (guard, repair, reclaim, resurrect),
  with the unit or the job as the answer. Steps are formed from both by the
  one rule of the opening models
  ([ADR 0013](0013-evaluate-on-held-out-games.md)), with the answer in place
  of the unit. Other commands, such as moves, are not answers.
- **Every order has the builders it went to**: the units the command reached
  that were the player's and alive and can carry it out (the unit is in their
  build list, or they can do the job). The table has one row per order and
  builder, so that an order to several builders can be scored once, as the
  player's decision, or once per builder, as the bot asks.
- **The state of an order is the one just before it**: what the game wrote at
  the end of the frame before the order's, so nothing the order caused is in
  its context.
- **Only the player's own team and its allies**: game time, the team's metal
  and energy (stored, storage, income, expense), the current wind and the
  map's wind range, the team's units by type, finished and under construction,
  the allies' resources and units summed, the builder the order is for (its
  kind, type, whether it moves, the answer it got before), the build power of
  the builder and of the team's finished and idle builders by kind, and the
  player's skill. No enemy units and no visibility data. A player sees their
  own and their allies' units and resources, so this needs no line of sight.
- **Unit types are names without the faction prefix**, those that make up 99%
  of the orders of the training split, with the commander, and every other
  type counted together.
- **The context comes in named groups**, so that what each group adds is
  measured on its own against the same model with the order history alone.
- **The time since the player's previous order is not context.** The table
  keeps it (the `pace` group), but it says how the order being predicted was
  clicked, not what the game looked like: a step within 0.2 s of the order
  before has a different answer by the rule that forms steps, and a step a few
  seconds after it is much likelier to repeat the answer than one after a long
  pause. Models are judged without it. Whether the builder was idle when it
  got the order is kept for the same reason and is not an input either: the
  bot decides for a builder when it is idle.

## Consequences

- Opening models need no visibility data. Line of sight per ally team, which
  state format 7 records, is needed before enemy units are used, after first
  contact or for scouting.
- The bot must read the same inputs at decision time: the allies' resources
  and units through the AI interface, which has to be checked in our build of
  the library before a model that uses the allies group is played, and the
  build power and idle state of its builders.
- A row knows when the player gave the order, so a model trained on the table
  predicts what comes next given that the player acts now. In the game the bot
  decides when to act (the reaction delays of
  [ADR 0008](0008-play-under-human-like-limits.md)), and the state is what the
  bot reads at that moment.
- Quick runs of clicks of one unit or job are one step, as drags are
  ([ADR 0013](0013-evaluate-on-held-out-games.md)), and the table numbers its
  steps when it is loaded, by the same rule as the opening models, so a change
  of what a step is needs no new build.
- What a builder type can do is read from the unit files as written, not as
  the game changes them when it loads; a builder that built something its file
  does not list loses that order's builder, and the mask of
  [ADR 0019](0019-first-model-decides-each-builders-next-order.md) would
  remove that answer. Both are rare ([`context.md`](../research/context.md)).
  Games re-simulated in state format 7 carry the unit types as loaded
  ([ADR 0010](0010-re-simulate-replays-headlessly-for-game-state.md)).
- Whether a builder is idle is known only from the idle lines of the state
  export and the commands it got after them; a new builder counts as busy
  until it first runs out of orders. The work each builder does, which state
  format 6 records, would tell it exactly.
- The openings end where `openings_v2` ends them, mostly at the usual contact
  of the position, not at the re-simulated game's own contact. A dataset that
  ends them at the measured contact is a new version of both datasets.
- Every newly re-simulated game makes the table bigger without changing the
  rows of the others, so the measurement is repeated as the sample grows.
- Revisit when the bot plays past first contact, when the state export records
  visibility, or when the measurement shows that a kind of state the table
  leaves out (placement, metal spots, reclaimable features, queues) is what
  models need.
