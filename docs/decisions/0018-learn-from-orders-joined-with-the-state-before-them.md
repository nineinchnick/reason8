# 0018. Learn from orders joined with the state just before them

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

Models are to decide from the game state as well as from the orders before
([ADR 0005](0005-learn-decisions-with-their-context.md)). The state comes from
re-simulating replays
([ADR 0010](0010-re-simulate-replays-headlessly-for-game-state.md)): every
second each team's resources and the wind, and a line for every unit created,
finished, given and destroyed. Before re-simulating the whole slice, a sample
of a few thousand games measures what the state adds over the order-only
baselines ([`results.md`](../results.md)).

A model only helps the bot if the bot can read the same inputs while it plays.
Our own build of BARb's library reads, through the engine's AI interface, the
team's resources, the current wind, the team's and its allies' units, and
enemy units in line of sight or radar
([ADR 0007](0007-ship-the-model-as-tables-in-a-barb-variant.md)). The bot
plays only on what a player could see
([ADR 0008](0008-play-under-human-like-limits.md)), and the state export does
not record what each team could see yet. An opening, as the dataset defines
it, ends at first contact ([ADR 0012](0012-end-openings-at-first-contact.md)),
before the enemy matters much.

The join was checked against the state tables, and the measurement of what
each kind of state adds is in [`context.md`](../research/context.md).

## Decision

Models of the opening learn from and are scored on the **decision table**
(`reason8 context build`,
[`context-dataset.md`](../reference/context-dataset.md)):

- **The rows are the opening dataset's rows** of the re-simulated games: the
  same orders, steps and splits as `openings_v2`, so that every model,
  order-only or not, is scored on the same steps
  ([ADR 0013](0013-evaluate-on-held-out-games.md)).
- **The state of an order is the one just before it**: what the game wrote at
  the end of the frame before the order's, so nothing the order caused is in
  its context.
- **Only the player's own team and its allies**: game time, the team's metal
  and energy (stored, storage, income, expense), the current wind and the
  map's wind range, the team's units by type, finished and under construction,
  and the allies' resources and units summed. No enemy units and no visibility
  data. A player sees their own and their allies' units and resources, so this
  needs no line of sight.
- **Unit types are names without the faction prefix**, those that make up 99%
  of the orders of the training split, with the commander, and every other
  type counted together.
- **The context comes in named groups**, so that what each group adds is
  measured on its own against the same model with the order history alone.
- **The time since the player's previous order is not context.** The table
  keeps it (the `pace` group), but it says how the order being predicted was
  clicked, not what the game looked like: a step a tenth of a second after the
  one before is nearly always the same unit again, and the time since an order
  of the same frame gives the unit away entirely. Models are judged without
  it.

## Consequences

- Opening models need no visibility data. Line of sight per ally team is still
  needed before enemy units are used, after first contact or for scouting.
- The bot must read the same inputs at decision time: the allies' resources
  and units through the AI interface, which has to be checked in our build of
  the library before a model that uses the allies group is played.
- A row knows when the player gave the order, so a model trained on the table
  predicts what comes next given that the player acts now. In the game the bot
  decides when to act (the reaction delays of
  [ADR 0008](0008-play-under-human-like-limits.md)), and the state is what the
  bot reads at that moment.
- Quick runs of clicks of one unit are separate steps under
  [ADR 0013](0013-evaluate-on-held-out-games.md), and they are what the pace
  of the orders predicts. Merging them into one step, as drags are, would
  change the protocol and every baseline, and is left to that record.
- The openings end where `openings_v2` ends them, mostly at the usual contact
  of the position, not at the re-simulated game's own contact. A dataset that
  ends them at the measured contact is a new version of both datasets.
- Every newly re-simulated game makes the table bigger without changing the
  rows of the others, so the measurement is repeated as the sample grows.
- Revisit when the bot plays past first contact, when the state export records
  visibility, or when the measurement shows that a kind of state the table
  leaves out (placement, metal spots, queues) is what models need.
