# The decision table (`context_v1`)

Opening build orders with the game state just before each order. It is built
from the games of the context sample that have been re-simulated
([ADR 0010](../decisions/0010-re-simulate-replays-headlessly-for-game-state.md)),
and it is what models that decide from the state learn from and are scored on
([ADR 0018](../decisions/0018-learn-from-orders-joined-with-the-state-before-them.md)).
What the context adds to prediction is measured in
[`context.md`](../research/context.md). Code: `reason8/context/`.

```sh
uv run reason8 context build                   # -> data/datasets/context_v1/
uv run reason8 context check                   # the join, on 20 games
uv run reason8 context measure --split test    # docs/research/context.md
```

## What goes in

The sample
: `data/logs/context-sample.parquet`: 3,000 games drawn with a fixed seed from
  the `ok` games of `openings_v2` (1,350 Supreme Isthmus, 1,350 All That
  Glitters, 300 Rosetta), with `match_id`, `replay_file_name`, `map` and
  `split`. `reason8 headless batch` re-simulates them, the first 10 minutes of
  each.

The rows
: The rows of the opening dataset (`openings_v2`,
  [`openings-dataset.md`](openings-dataset.md)) of the sample's games: the
  same orders, where each opening ends, the same steps and the same split. A
  game is used once its state is there in format 5 or later (resources every
  second) and reaches past the last order of its openings. Building again
  reads whatever games are done by then and rewrites the table; the split of a
  game never changes.

The state
: The Parquet tables next to each state file in `data/state/`
  (`reason8/headless/tables.py`): `game` (teams, wind range), `resources`
  (every second) and `events` (units created, finished, given and destroyed).
  The snapshots, hits and damage are not used.

## When the state is taken

An order in frame F gets the state written at the end of frame F − 1 (the
`state_frame`, 0 for orders of frame 0): the world as it was when the command
arrived, before anything the command itself did. The resources are those of
the last line up to that frame, at most a second old (`resources_frame`); the
units are those standing after the events of that frame, as
`reason8.headless.standing.standing_units()` rebuilds them. Both joins are
Polars joins over all games of a chunk: `join_asof` on the frame for
resources, and for units a running sum of the changes the unit events make
(`unit_changes()`: +1 when created, finished moves a unit from building to
done, given moves it between teams, destroyed takes it away).

## Columns

Every column of the opening dataset's rows
([`openings-dataset.md`](openings-dataset.md)), and:

`replay`
: The replay's name without `.sdfz`: the name the state tables use.

`state_frame`, `resources_frame`
: The frame whose state the row has, and the frame of its resources line.

Which orders start a step is not a column: `reason8 context measure` and
`reason8 context check` number the steps when they load the rows
(`reason8.openings.dataset.step_index`, the rule of
[ADR 0013](../decisions/0013-evaluate-on-held-out-games.md)), as the opening
models do, so the table always has the steps the models are scored on, and a
change of the rule needs no new build. The scored steps are those numbered
below 30.

The context columns come in groups, listed with their columns in the manifest,
so that a model can take any of them:

time
: `time_s`: game time of the order in seconds.

pace
: `since_previous_s`: seconds since the player's last build order in an
  earlier frame (null before there is one). It is not the time since the order
  before this one: orders of one frame are given at once, and an order in the
  frame of the step before it starts a new step only when its unit differs, so
  that time would give the answer away. Even so, it describes how the order
  being predicted was given (a step that follows the one before by a tenth of
  a second is nearly always the same unit again, clicked in a quick run) more
  than the game, and the measurement keeps it out of the model with all
  context ([`context.md`](../research/context.md)).

economy
: The team's `metal` and `energy`: stored, `_storage`, `_income` and
  `_expense`, as the engine reports them for the team.

wind
: `wind`: the current wind speed. `wind_min`, `wind_max`: the map's range.

own_units
: `own_done_<type>` and `own_building_<type>`: the team's units of each type,
  finished and under construction. A type is a unit name without its faction
  prefix (`armmex` and `cormex` are both `mex`). The types are those that make
  up 99% of the added orders of `openings_v2`'s training split (79 types),
  plus `com` (the commander); every other type is counted as `other`.

allies
: `allies_<economy column>` and `allies_done_<type>`,
  `allies_building_<type>`: the same summed over the other teams of the
  player's ally team.

Nothing about the enemy and nothing about what any team could see is in the
table: everything in it is the player's own team or its allies, which the bot
can read through the engine's AI interface
([ADR 0007](../decisions/0007-ship-the-model-as-tables-in-a-barb-variant.md)).

## Files

In `data/datasets/context_v1/`:

`train.parquet`, `validation.parquet`, `test.parquet`
: The rows of each split, in the order of the opening dataset.

`games.parquet`
: One row per game of the sample: `match_id`, `replay_file_name`, `map`,
  `split`, `status` (`ok`, `not re-simulated yet`, `state before format 5`,
  `state ends before the opening does`, `no openings in the opening dataset`),
  the state's format `version` and `last_frame`.

`splits/<split>.txt`
: The match ids of each split that are in the table.

`manifest.json`
: When and from which code it was built, the source dataset (name, build time,
  commit), the sample file and its SHA-256, the split rule, when the state is
  taken, the unit types, the groups with their columns, and the counts of
  games, openings, rows and steps.

`README.md`
: The counts, for a reader of the data directory.

A build of 503 games took 30 s in one process and 2.7 GB of memory, most of it
reading the state tables; the table has about 1,400 rows per game.

## Checking the join

`reason8 context check --games N` picks N games of the table at random
(`--seed`) and compares every row with the state tables directly: the
resources line is the one of the order's second and has the same values, and
the units of the team and of its allies equal what `standing_units()` gives
for `state_frame`, counted by type. It also matches each structure order with
a unit of the same type that the team created on the same spot (within 16 map
units) after the order, and counts the units created of each type the players
ordered from factories. The results are in
[`context.md`](../research/context.md#the-join).
