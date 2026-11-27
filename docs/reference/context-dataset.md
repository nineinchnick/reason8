# The decision table (`context_v2`)

The orders players gave their builders in their openings, build orders and
jobs, with the builders that got them and the game state just before each. It
is built from the games of the context sample that have been re-simulated
([ADR 0010](../decisions/0010-re-simulate-replays-headlessly-for-game-state.md)),
and it is what the first learned model, asked by every builder
([ADR 0019](../decisions/0019-first-model-trees-asked-by-every-builder.md)),
learns from and is scored on
([ADR 0018](../decisions/0018-learn-from-orders-joined-with-the-state-before-them.md)).
What the builders, the jobs and the context add to prediction is measured in
[`context.md`](../research/context.md). Code: `reason8/context/`.

```sh
uv run reason8 context build                   # -> data/datasets/context_v2/
uv run reason8 context check                   # the join, on 20 games
uv run reason8 context measure --split test    # docs/research/context.md
```

The first version, `context_v1`, held the build orders only, one row per
order, without builders, jobs, build power or skill. `reason8 context check`
and `reason8 context measure --table data/datasets/context_v1` still read it;
building it again needs the code of its build (see its manifest).

## What goes in

The sample
: `data/logs/context-sample.parquet`: 3,000 games drawn with a fixed seed from
  the `ok` games of `openings_v2` (1,350 Supreme Isthmus, 1,350 All That
  Glitters, 300 Rosetta), with `match_id`, `replay_file_name`, `map` and
  `split`. `reason8 headless batch` re-simulates them, the first 10 minutes of
  each.

The build orders
: The rows of the opening dataset (`openings_v2`,
  [`openings-dataset.md`](openings-dataset.md)) of the sample's games: the
  same orders, where each opening ends and the same split. A game is used once
  its state is there in format 5 or later (resources every second), reaches
  past the last order of its openings, and its replay is in the replay tables
  (`data/tables`), whose commands and selections say which units each order
  went to.

The job orders
: The commands that give builders a job, up to the end of each opening
  (`cutoff_frame` of `openings_v2`), from the replay tables: `GUARD`,
  `REPAIR`, `RECLAIM` and `RESURRECT`, clicked or sent by a widget.

The state
: The Parquet tables next to each state file in `data/state/`
  (`reason8/headless/tables.py`): `game` (teams, wind range, game version),
  `resources` (every second) and `events` (units created, finished, given and
  destroyed, and builders going idle). The snapshots, hits and damage are not
  used.

The unit types
: The unit files of each game version, installed in `data/bar` by
  `reason8 headless setup` (`reason8/game/unitdefs.py`): the build power
  (`workertime`) of each unit, its build list and the jobs it can do. They are
  read as written; what the game changes when it loads them is not applied.

## Builders

A `COMMAND` packet goes to the player's selection, the last `select` event of
the player before it in the replay's stream; an `AICOMMAND` or `AICOMMANDS`
packet goes to the units it lists (`reason8.context.builders.command_units`).
The re-simulated game says what each of those unit ids was in the order's
frame: its type, its team, whether it was alive and finished. A unit id used
again after its unit died names the new unit from then on.

The builders of an order are the units it went to that were the player's,
alive, and can carry it out: a build order the units whose build list has the
unit, a job the units that can do the job. Units in the selection that cannot
carry it out ignore it, as they do in the game. Each builder has a kind:

commander
: A unit with `customparams.iscommander`.

factory
: A structure with a build list.

construction
: A mobile unit with a build list (construction bots, vehicles, aircraft,
  ships, combat engineers).

tower
: A structure with build power and no build list (construction turrets).

other
: A mobile unit with build power and no build list (resurrection bots).

The jobs each kind can do follow the engine's defaults for the `can*` fields
of the unit files: a builder can assist, reclaim and repair unless its file
says otherwise, only units whose file says so can resurrect, and factories do
no jobs.

## Rows

One row per order and builder that got it. An order given to several builders
at once is one decision of the player, and in the bot each of those builders
asks the model on its own; the table keeps both views:

- `decision_index` numbers a player's orders, build orders and jobs together,
  in the order of the replay's stream. Every row of one order has the same
  `decision_index`.
- `builder_index` numbers the builders of an order by build power, most first,
  then by unit id. The row with `builder_index` 0 stands for the order (the
  order view); all rows together are the asks (the ask view).
- `builders` is how many builders got the order, `targets` how many units the
  command went to, `other_units` how many of those had no build power.

An order that reached no builder keeps one row with the builder's columns
null. That happens to build orders only: a job that reached no builder went to
army units only and is not in the table.

### Answers and steps

`answer` is what the model predicts: the unit a build order adds, or the job
(`assist`, `reclaim`, `repair`, `resurrect`); null for orders that take units
out of a factory queue. The job of a command:

`GUARD`
: assist.

`REPAIR`
: assist when its one target is a unit still being built (helping to build
  it); repair otherwise, a finished unit or an area.

`RECLAIM`
: reclaim, of a feature, a unit or an area.

`RESURRECT`
: resurrect, of a feature or an area.

`job_command` keeps the command, and `job_target` says what it pointed at:
`unit`, `feature` or `area`. Other commands, such as move, fight, patrol,
attack or capture, are not answers of the model and are not rows; they still
count for whether a builder is idle (below).

Which orders start a step is not a column: `reason8 context measure` and
`reason8 context check` number the steps of each player when they load the
rows, by the rule of the opening models
([ADR 0013](../decisions/0013-evaluate-on-held-out-games.md),
`reason8.openings.dataset.step_index`) with the answer in place of the unit:
an order with the answer of the decision before it at most 6 frames later is
part of its step. A job between two orders of one unit breaks their run, and a
widget's reclaim of an area, sent as one reclaim per feature in one frame, is
one step. The scored steps are those numbered below 30.

## When the state is taken

An order in frame F gets the state written at the end of frame F − 1 (the
`state_frame`, 0 for orders of frame 0): the world as it was when the command
arrived, before anything the command itself did. The resources are those of
the last line up to that frame, at most a second old (`resources_frame`); the
units are those standing after the events of that frame, as
`reason8.headless.standing.standing_units()` rebuilds them; the build power
sums are taken the same way. Every builder of an order has the same state.

## Columns

Every column of the opening dataset's rows
([`openings-dataset.md`](openings-dataset.md); null in job rows for the
columns of a build order: `order_index`, `seq_idx`, `unit`, `count`), and:

`replay`
: The replay's name without `.sdfz`: the name the state tables use.

`decision_index`, `builder_index`, `answer`, `builders`, `targets`, `other_units`
: See above. `kind` is `structure`, `factory` or `job`.

`job`, `job_command`, `job_target`
: For job rows: the job, the command and what it pointed at.

`builder_id`, `builder_unit`
: The builder's unit id, and its type under today's name.

`builder_idle`
: Whether the builder was idle at `state_frame`: it had written an idle line
  and got no command that gives it something to do since (`BUILD`, `MOVE`,
  `FIGHT`, `PATROL`, `ATTACK`, `GUARD`, `REPAIR`, `RECLAIM`, `RESURRECT` and
  the like; state toggles do not count). Null when the builder had not gone
  idle before (most often a builder that is new). The bot asks when a builder
  is idle; this column finds the rows in the same situation. It describes the
  player's timing and is not an input of the models.

`state_frame`, `resources_frame`
: The frame whose state the row has, and the frame of its resources line.

The context columns come in groups, listed with their columns in the manifest,
so that a model can take any of them:

time
: `time_s`: game time of the order in seconds.

pace
: `since_previous_s`: seconds since the player's last order in an earlier
  frame (null before there is one). It describes how the order being predicted
  was given more than the game, and the measurement keeps it out of the models
  ([`context.md`](../research/context.md)).

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

builder
: `builder_kind`, `builder_role` (its type without the faction prefix),
  `builder_moves`, and `builder_previous`: the answer of the order before this
  one that went to the same builder (`<start>` for its first).

build_power
: `builder_build_power`: the asking builder's. `team_build_power` and
  `team_build_power_<kind>`: the build power of the team's finished builders,
  in all and by kind. `idle_build_power` and `idle_build_power_<kind>`: the
  same of the builders that were idle (as `builder_idle`), so a builder that
  has not gone idle yet counts as busy.

skill
: `skill`: the player's rating before the game, the column of the opening
  dataset.

Nothing about the enemy and nothing about what any team could see is in the
table: everything in it is the player's own team or its allies, which the bot
can read through the engine's AI interface
([ADR 0007](../decisions/0007-ship-the-model-as-tables-in-a-barb-variant.md)).

## Files

In `data/datasets/context_v2/`:

`train.parquet`, `validation.parquet`, `test.parquet`
: The rows of each split, by player, `decision_index` and `builder_index`.

`builder_types.parquet`
: One row per game version and unit type with build power: `game`, `unit_def`
  (the name in that version), `builder_unit` (today's name), `builder_kind`,
  `builder_moves`, `build_power`, `can_assist`, `can_reclaim`, `can_repair`,
  `can_resurrect` and `build_options` (today's names). The answers a builder
  can give, which the models' mask keeps
  ([ADR 0019](../decisions/0019-first-model-trees-asked-by-every-builder.md)),
  are its build options and its jobs.

`games.parquet`
: One row per game of the sample: `match_id`, `replay_file_name`, `map`,
  `split`, `status` (`ok`, `not re-simulated yet`, `state before format 5`,
  `state ends before the opening does`, `no openings in the opening dataset`,
  `replay not in the replay tables`), the state's format `version`,
  `last_frame` and the game version `game`.

`splits/<split>.txt`
: The match ids of each split that are in the table.

`manifest.json`
: When and from which code it was built, the source dataset (name, build time,
  commit), the sample file and its SHA-256, the split rule, when the state is
  taken, the unit types, the answers (jobs, job commands, builder kinds), the
  groups with their columns, the columns that hold names, and the counts of
  games, openings, decisions by kind and by number of builders, rows and
  steps.

`README.md`
: The counts, for a reader of the data directory.

A build of 2,025 games takes 5 minutes with up to 32 threads and at most 9.4
GB of memory (100 games per chunk; it reads 50 now). The table has about 3,000
rows per game: 2,800 decisions, of which 1,400 build orders and the rest jobs,
most of them reclaims of single features sent by widgets.

## Checking the join

`reason8 context check --games N` picks N games of the table at random
(`--seed`) and compares the rows of their build orders with the state tables
directly: the resources line is the one of the order's second and has the same
values, and the units of the team and of its allies equal what
`standing_units()` gives for `state_frame`, counted by type. It matches each
structure order with a unit of the same type that the team created on the same
spot (within 16 map units) after the order, and counts the units created of
each type the players ordered from factories.

For the builders, it asks whether the unit that then built the thing is one of
the order's builders: for a structure, the unit named in the `created` line of
the unit made on the spot; for a factory order, whether the factory created a
unit of that type after it. The results are in
[`context.md`](../research/context.md#the-join).
