# The opening dataset

Opening build orders of the training slice as a dataset: one row per build
order of every player's opening, split by game into train, validation and
test. An opening ends at the player's first contact with the enemy, and games
are split by match id
([ADR 0012](../decisions/0012-end-openings-at-first-contact.md); the
measurements are in [`first-contact.md`](../research/first-contact.md)); what
is left out follows
[ADR 0015](../decisions/0015-train-across-balance-patches.md) (balance
patches) and
[ADR 0011](../decisions/0011-take-positions-from-the-map-metadata.md)
(positions). Code: `reason8/openings/extract.py` (the orders),
`reason8/openings/contact.py` (where an opening ends) and
`reason8/openings/dataset.py` (the builder).

## Building it

```sh
uv run reason8 maps fetch        # once: the pinned map list
uv run reason8 contact           # re-simulated games -> data/contact/
uv run reason8 dataset           # parsed replays -> data/datasets/openings_v2/
uv run reason8 dataset --stats   # the tables below
```

The games are those of `select_matches()` over the slice's pinned window
(2026-05-23 to 2026-11-22, [`dataset.md`](dataset.md)) whose replays are
parsed in `data/parsed/`; `--since` and `--until` narrow the window to some
days of the date partitions. Building again reads whatever is parsed by then
and rewrites the dataset: a game's split depends only on its match id, so
nothing moves between splits as more replays are parsed. With 24 processes it
reads about 35 replays a second.

`--cutoff window` builds the openings as they were before they ended at first
contact (`openings_v1`: every order of the first 8 minutes),
`--window-seconds` changes the 8 minutes, and `--contact` names the file with
the measured first contacts.

## What goes in

An opening is every build order a player gives until their first contact with
the enemy, the pregame queue included, in replay order, and at most the orders
of the first 8 minutes of game time (the opening window). First contact is the
first time a unit of the player other than a scout is damaged by an enemy
unit. Where an opening ends (`cutoff_frame`) comes from one of three places
(`cutoff_source`):

`measured`
: The game was played again headlessly, and the opening ends at the player's
  own first contact, or with the window when there was none in it.

`position`
: The game was not re-simulated: the opening ends at the median first contact
  measured for its map and start position
  (`reason8.openings.contact.POSITION_CUTOFF_SECONDS`, the table in
  [`first-contact.md`](../research/first-contact.md#per-map-and-position)).

`window`
: Nothing is known about the map: the opening ends with the window.

Every order is a row, also those that take units out of a factory queue
(`count` below 0, `seq_idx` empty). Orders are intentions, not finished units
([`replay-format.md`](replay-format.md#commands-arent-outcomes)); the columns
that say how an order was given are there to tell "ordered" from "probably
built" later.

Games left out (`games.parquet`, column `status`):

bots in the game
: a team is played by an AI

not a released game version
: the version is not `test-<build>-<hash>`

custom unit tweaks or stat multipliers
: a `tweakdefs*` or `tweakunits*` option or a `multiplier_*` other than 1
  ([ADR 0015](../decisions/0015-train-across-balance-patches.md)); other
  balance options are kept and recorded

changed water level
: the `map_waterlevel` option changes the terrain

not two teams of 8
: the replay does not have two ally teams of 8 players each

unreadable replay
: the parsed file cannot be read

Openings left out (`openings.parquet`, column `status`):

orders a removed unit
: the opening, up to where it ends, orders a unit that the newest game in the
  dataset with the same factions loaded does not have
  ([ADR 0015](../decisions/0015-train-across-balance-patches.md)). Games with
  Legion are compared with the newest game with Legion, the others with the
  newest game without it, because a game with Legion defines 244 more units.

Kept and flagged instead
([ADR 0011](../decisions/0011-take-positions-from-the-map-metadata.md)):
starts that are not on the spot of their position (`on_spot`), games that did
not show the recommended positions (`positions_shown`) and games whose start
boxes are not the map's default (`default_boxes`: false, or empty when it
cannot be told).

Players who picked Random (or whose faction the replay does not know) get the
faction whose units they ordered most; `faction_picked` keeps what the lobby
said.

## Files

`train.parquet`, `validation.parquet`, `test.parquet`
: One row per build order, sorted by match, player and order.

`openings.parquet`
: One row per player of every game used, with the split, the status and the
  removed units, where the opening ends, and the number of orders (`orders`,
  `added`, and `orders_in_window` for the whole opening window).

`games.parquet`
: One row per parsed game of the slice, with the split and the status.

`splits/train.txt`, `splits/validation.txt`, `splits/test.txt`
: The match ids of each split.

`manifest.json`
: What went in: the selection, the opening (the window, the cutoff, the
  definition of contact, the cutoffs per map and position and the number of
  re-simulated games), the split rule, the reference builds of the vocabulary,
  the parser versions, the counts and the code version (commit, and whether
  the tree had uncommitted changes).

`README.md`
: The counts, for whoever finds the directory.

## Columns of the order rows

Game:

`match_id`
: The lobby's match id, as in the match dumps

`map`, `team_size`, `start_time`
: From the replay and the match dump

`game_version`, `build`, `opening_era`
: The version, its build number and the first build of the last
  opening-changing balance patch (`reason8.game.versions`)

`balance_options`
: The balance-changing lobby options that are on, as a JSON object (`{}` in a
  standard game)

`positions_shown`, `default_boxes`
: How the start was set up (`reason8.game.positions.start_setup()`)

Player:

`player_slot`, `ally_team`
: The player's team id and ally team in the replay

`faction`
: Armada, Cortex or Legion

`start_x`, `start_z`
: The start point, in map units

`position`, `role`, `position_index`, `on_spot`
: The nearest recommended start position of the player's side (`P10`), its
  role, its place in the side's list, and whether the start is on it
  (`reason8.game.positions.replay_positions()`)

`won`
: Whether the player's ally team won

`skill`
: OpenSkill mu before the game (`old_skill` of the match dump)

`cutoff_frame`, `cutoff_source`
: The last frame of the player's opening and where it comes from (`measured`,
  `position` or `window`, see above)

Order:

`order_index`
: Index among all build orders of the opening, from 0

`seq_idx`
: Index among the orders that add a unit, from 0: the sequence a model
  predicts. Empty for removals.

`frame`
: Game frame of the order (30 per second; pregame orders come at frames 5 to
  13\)

`unit`
: The unit's name today (`UNIT_RENAMES` applied)

`kind`
: `structure` (placed by a builder) or `factory` (unit production)

`count`
: Units added by a factory order (×5 with shift, ×20 with ctrl); negative when
  taken out of the queue; 1 for structures

`via`
: `COMMAND` (clicked), `AICOMMAND` or `AICOMMANDS` (sent by a widget, such as
  the pregame queue or area mex)

`queued`
: Given with shift: appended to the queue. A structure order without it
  replaces the builder's queue.

`inserted`, `quota`
: Placed inside the queue (`INSERT`), and inserted by BAR's factory-quota
  widget rather than clicked

`repeat`
: Same unit in the same frame as the order before: part of one drag or click

`x`, `z`
: Where a structure is placed

`openings.parquet` has the player columns, `faction_picked`, `position_side`,
`position_distance`, `skill_uncertainty`, and per opening `orders`, `added`,
`orders_in_window`, `status` and `removed_units`. `games.parquet` has the game
columns, `team_count`, `opening_era_name`, `factions` (the unit name prefixes
of the factions loaded), `positions_source`, `parser`, `contact_measured` (the
game was re-simulated), `replay_file_name`, `game_duration` and `avg_skill`.

## Statistics

`openings_v2` as built on 2026-11-24 from the 42,904 replays of the slice that
parsed (42,909 were downloaded; 4 of the 42,913 games are no longer on the
server and 5 replays fail to parse), with the first contacts of the 72
re-simulated games of [`first-contact.md`](../research/first-contact.md).

### Size

| map                      | train games | validation games | test games | openings |
| ------------------------ | ----------- | ---------------- | ---------- | -------- |
| All That Glitters v2.2.3 | 15542       | 1873             | 1961       | 309364   |
| Rosetta 1.4.4            | 885         | 103              | 128        | 16964    |
| Supreme Isthmus v2.1     | 17230       | 2192             | 2181       | 344486   |

Rows (build orders) per split:

| split      | games | openings | rows     |
| ---------- | ----- | -------- | -------- |
| train      | 33657 | 536310   | 49994328 |
| validation | 4168  | 66433    | 6198578  |
| test       | 4270  | 68071    | 6315705  |

Games of the slice that were parsed, by status:

| status                                 | games |
| -------------------------------------- | ----- |
| changed water level                    | 14    |
| custom unit tweaks or stat multipliers | 795   |
| ok                                     | 42095 |

Openings of the games used, by status:

| status                | openings |
| --------------------- | -------- |
| ok                    | 670814   |
| orders a removed unit | 2706     |

- starts on the spot: 658300 of 670814 (98.1%)
- games that showed the recommended positions: 41405 of 42095
- start boxes: cannot tell 12276, changed 247, default 29572
- games with a balance-changing lobby option: 24084 of 42095

Games per opening era:

| opening era                         | first build | games |
| ----------------------------------- | ----------- | ----- |
| Season 3                            | 29241       | 1955  |
| May balance patch                   | 30236       | 14096 |
| July balance patch                  | 30755       | 7692  |
| August balance patch                | 31075       | 5578  |
| Air constructors and mobile jammers | 31357       | 12774 |

### Vocabulary per faction

| faction | unit names ordered | names for 99% of orders | orders   |
| ------- | ------------------ | ----------------------- | -------- |
| Armada  | 393                | 60                      | 36584900 |
| Cortex  | 364                | 62                      | 23577774 |
| Legion  | 320                | 74                      | 1292788  |

### Sequence lengths

| map                      | openings | orders p10 | median | p90 | steps p10 | median | p90 |
| ------------------------ | -------- | ---------- | ------ | --- | --------- | ------ | --- |
| All That Glitters v2.2.3 | 309350   | 37         | 71     | 143 | 25        | 39     | 60  |
| Rosetta 1.4.4            | 16964    | 24         | 40     | 74  | 20        | 34     | 56  |
| Supreme Isthmus v2.1     | 344470   | 23         | 65     | 212 | 18        | 33     | 57  |

### Where openings end

Openings end at the player's first contact with the enemy, at the latest after
8 minutes (72 games with a measured contact).

| map                      | openings | measured contact | by position | whole window | end p10 | median | p90  | orders of the window kept |
| ------------------------ | -------- | ---------------- | ----------- | ------------ | ------- | ------ | ---- | ------------------------- |
| All That Glitters v2.2.3 | 309364   | 383              | 308981      | 0            | 3:15    | 3:50   | 8:00 | 67.1%                     |
| Rosetta 1.4.4            | 16964    | 363              | 16601       | 0            | 2:45    | 3:00   | 6:35 | 53.2%                     |
| Supreme Isthmus v2.1     | 344486   | 382              | 344104      | 0            | 2:05    | 4:25   | 8:00 | 69.5%                     |

### Top 20 openings (first 6 orders)

| opening                         | openings | share |
| ------------------------------- | -------- | ----- |
| `mex mex mex win win win`       | 161245   | 24.0% |
| `mex mex mex solar solar lab`   | 75176    | 11.2% |
| `mex mex mex solar win win`     | 50631    | 7.5%  |
| `tide tide tide tide tide tide` | 41386    | 6.2%  |
| `mex mex win win win win`       | 20570    | 3.1%  |
| `mex mex mex solar solar vp`    | 17742    | 2.6%  |
| `mex mex mex solar solar solar` | 15104    | 2.3%  |
| `mex mex mex solar solar win`   | 11975    | 1.8%  |
| `mex mex mex mex solar solar`   | 10253    | 1.5%  |
| `mex mex win mex win win`       | 9158     | 1.4%  |
| `mex mex win win mex win`       | 8166     | 1.2%  |
| `mex mex mex mex win win`       | 6865     | 1.0%  |
| `mex mex win win win lab`       | 6046     | 0.9%  |
| `mex mex mex win win lab`       | 5860     | 0.9%  |
| `mex mex mex solar solar ap`    | 5269     | 0.8%  |
| `mex mex win win win mex`       | 4720     | 0.7%  |
| `mex mex mex mex mex mex`       | 3960     | 0.6%  |
| `mex mex mex solar mex solar`   | 3925     | 0.6%  |
| `mex mex mex mex solar win`     | 3904     | 0.6%  |
| `mex mex mex solar win lab`     | 3223     | 0.5%  |

### Per map and position

Openings from a start on the spot only. Factions count every opening of the
position.

#### All That Glitters v2.2.3

| position | role  | openings | on the spot | Armada | Cortex | Legion | first factory  | share | first 6 orders                | share |
| -------- | ----- | -------- | ----------- | ------ | ------ | ------ | -------------- | ----- | ----------------------------- | ----- |
| P1       | front | 19199    | 18894       | 9868   | 8968   | 363    | bot lab        | 66.9% | `mex mex mex solar solar lab` | 22.5% |
| P2       | air   | 19320    | 19163       | 3084   | 15804  | 432    | aircraft plant | 94.2% | `mex mex mex mex solar solar` | 12.5% |
| P3       | tech  | 19200    | 19127       | 15045  | 3977   | 178    | bot lab        | 91.4% | `mex mex mex solar solar lab` | 11.1% |
| P4       | front | 19043    | 19003       | 10674  | 7987   | 382    | bot lab        | 61.4% | `mex mex mex solar solar lab` | 20.0% |
| P5       | front | 19497    | 18977       | 8166   | 10914  | 417    | bot lab        | 79.3% | `mex mex mex solar solar lab` | 31.0% |
| P6       | front | 19496    | 19004       | 10599  | 8557   | 340    | bot lab        | 70.8% | `mex mex mex solar solar lab` | 27.9% |
| P7       | front | 19529    | 19103       | 11064  | 8116   | 349    | bot lab        | 72.6% | `mex mex mex solar solar lab` | 31.1% |
| P8       | front | 19389    | 19068       | 8975   | 9926   | 488    | bot lab        | 74.5% | `mex mex mex solar solar lab` | 31.3% |
| P9       | front | 19139    | 18937       | 9761   | 9008   | 370    | bot lab        | 66.4% | `mex mex mex solar solar lab` | 21.6% |
| P10      | air   | 19255    | 19185       | 3013   | 15817  | 425    | aircraft plant | 94.1% | `mex mex mex win win win`     | 17.1% |
| P11      | tech  | 19200    | 19105       | 15032  | 4016   | 152    | bot lab        | 91.3% | `mex mex mex mex solar solar` | 12.9% |
| P12      | front | 19015    | 18982       | 10708  | 7905   | 402    | bot lab        | 60.9% | `mex mex mex solar solar lab` | 18.7% |
| P13      | front | 19597    | 19058       | 8178   | 11001  | 418    | bot lab        | 79.5% | `mex mex mex solar solar lab` | 31.5% |
| P14      | front | 19646    | 19130       | 10782  | 8539   | 325    | bot lab        | 70.6% | `mex mex mex solar solar lab` | 27.8% |
| P15      | front | 19547    | 19119       | 11174  | 8043   | 330    | bot lab        | 72.7% | `mex mex mex solar solar lab` | 29.8% |
| P16      | front | 19292    | 18992       | 8999   | 9861   | 432    | bot lab        | 73.8% | `mex mex mex solar solar lab` | 32.2% |

#### Rosetta 1.4.4

| position | role       | openings | on the spot | Armada | Cortex | Legion | first factory  | share | first 6 orders                  | share |
| -------- | ---------- | -------- | ----------- | ------ | ------ | ------ | -------------- | ----- | ------------------------------- | ----- |
| P1       | front      | 1123     | 1098        | 399    | 567    | 157    | bot lab        | 95.0% | `mex mex mex solar solar lab`   | 41.4% |
| P2       | front/tech | 1018     | 1013        | 429    | 445    | 144    | bot lab        | 96.4% | `mex mex mex solar mex solar`   | 27.5% |
| P3       | front      | 1126     | 1074        | 452    | 506    | 168    | bot lab        | 78.4% | `mex mex mex solar solar lab`   | 47.4% |
| P4       | front      | 937      | 888         | 406    | 356    | 175    | bot lab        | 87.7% | `mex mex solar solar lab solar` | 10.0% |
| P5       | air        | 1042     | 1034        | 112    | 642    | 288    | aircraft plant | 78.3% | `mex mex mex solar solar ap`    | 22.2% |
| P6       | front      | 1083     | 1026        | 480    | 438    | 165    | bot lab        | 77.1% | `mex mex mex solar solar lab`   | 36.1% |
| P7       | front/tech | 1055     | 1051        | 574    | 341    | 140    | bot lab        | 96.9% | `mex mex mex solar solar lab`   | 37.0% |
| P8       | front      | 1101     | 1074        | 367    | 546    | 188    | bot lab        | 95.6% | `mex mex mex solar solar lab`   | 54.1% |
| P9       | front      | 1098     | 1087        | 418    | 542    | 138    | bot lab        | 95.4% | `mex mex mex solar solar lab`   | 40.1% |
| P10      | front/tech | 1026     | 1021        | 440    | 433    | 153    | bot lab        | 95.3% | `mex mex mex solar mex solar`   | 32.4% |
| P11      | front      | 1112     | 1081        | 478    | 457    | 177    | bot lab        | 73.1% | `mex mex mex solar solar lab`   | 44.8% |
| P12      | front      | 914      | 887         | 414    | 347    | 153    | bot lab        | 86.9% | `mex mex solar solar lab solar` | 6.9%  |
| P13      | air        | 1060     | 1058        | 105    | 691    | 264    | aircraft plant | 79.7% | `mex mex mex solar solar ap`    | 22.9% |
| P14      | front      | 1104     | 1052        | 473    | 426    | 205    | bot lab        | 78.4% | `mex mex mex solar solar lab`   | 36.5% |
| P15      | front/tech | 1056     | 1052        | 558    | 351    | 147    | bot lab        | 97.8% | `mex mex mex solar solar lab`   | 38.8% |
| P16      | front      | 1109     | 1067        | 393    | 546    | 170    | bot lab        | 96.2% | `mex mex mex solar solar lab`   | 57.4% |

#### Supreme Isthmus v2.1

| position | role       | openings | on the spot | Armada | Cortex | Legion | first factory  | share | first 6 orders                  | share |
| -------- | ---------- | -------- | ----------- | ------ | ------ | ------ | -------------- | ----- | ------------------------------- | ----- |
| P1       | sea        | 21184    | 20498       | 9458   | 11211  | 515    | bot lab        | 90.1% | `mex mex mex win win win`       | 65.0% |
| P2       | tech       | 21407    | 21249       | 19912  | 1264   | 231    | bot lab        | 98.4% | `mex mex mex win win win`       | 74.7% |
| P3       | air        | 21508    | 21361       | 3652   | 17215  | 641    | aircraft plant | 97.3% | `mex mex mex win win win`       | 67.1% |
| P4       | front      | 21498    | 20879       | 15161  | 5734   | 603    | bot lab        | 73.4% | `tide tide tide tide tide tide` | 95.0% |
| P5       | front      | 21945    | 21060       | 12574  | 8849   | 522    | bot lab        | 88.5% | `mex mex mex lab win win`       | 2.0%  |
| P6       | front      | 21861    | 21134       | 13282  | 8007   | 572    | bot lab        | 68.8% | `mex mex mex win win win`       | 2.9%  |
| P7       | front/tech | 21504    | 21233       | 14774  | 6196   | 534    | bot lab        | 94.9% | `mex mex mex win win win`       | 29.5% |
| P8       | sea        | 21323    | 20859       | 9269   | 11592  | 462    | shipyard       | 75.7% | `mex mex mex win win win`       | 50.5% |
| P9       | sea        | 21237    | 20621       | 9488   | 11272  | 477    | bot lab        | 90.0% | `mex mex mex win win win`       | 65.2% |
| P10      | tech       | 21459    | 21304       | 19949  | 1299   | 211    | bot lab        | 98.3% | `mex mex mex win win win`       | 74.8% |
| P11      | air        | 21511    | 21375       | 3691   | 17199  | 621    | aircraft plant | 97.3% | `mex mex mex win win win`       | 67.4% |
| P12      | front      | 21503    | 20945       | 15153  | 5717   | 633    | bot lab        | 73.4% | `tide tide tide tide tide tide` | 95.2% |
| P13      | front      | 21864    | 21036       | 12716  | 8630   | 518    | bot lab        | 88.5% | `mex mex mex lab win win`       | 2.1%  |
| P14      | front      | 21679    | 21145       | 13051  | 8023   | 605    | bot lab        | 68.5% | `mex mex mex win win win`       | 2.9%  |
| P15      | front/tech | 21568    | 21257       | 14870  | 6141   | 557    | bot lab        | 95.0% | `mex mex mex win win win`       | 29.3% |
| P16      | sea        | 21435    | 20919       | 9412   | 11540  | 483    | shipyard       | 75.4% | `mex mex mex win win win`       | 50.6% |

## Findings

- **A third of the first 8 minutes comes after first contact.** Ending
  openings at first contact keeps 68% of the build orders of the 8-minute
  window: 67% on Glitters, 53% on Rosetta and 70% on Isthmus. The median
  opening ends after 3:50, 3:00 and 4:25; a tenth end by 3:15, 2:45 and 2:05,
  and the tech positions keep their 8 minutes.
- **Half of all orders are drags.** 57% of the rows repeat the unit of the
  order before them in the same frame. An opening has a median of 40 to 71
  orders, but 33 to 39 steps once those repeats are merged (48 to 63 steps in
  the whole 8 minutes). The Isthmus pond positions (`P4`, `P12`) start with a
  dragged line of tidal generators in 95% of openings.
- **Few orders are queue edits.** 1.7% of the rows take units out of a factory
  queue, 0.8% are inserted into a queue and 0.05% come from the factory-quota
  widget; 73% were clicked and 80% were given with shift.
- **The vocabulary is small in practice.** Each faction ordered 320 to 393
  different units, but 60 to 74 names cover 99% of the orders.
- **The meta is in the first factory.** Tech and air positions agree on their
  first factory in 91 to 99% of openings on Isthmus and Glitters, and the
  exact first six orders are much less settled, as in
  [`maps/`](../research/maps/README.md).
- **Legion loses fewer openings than with 8 minutes.** 2,577 of 19,397 Legion
  openings (13%) are dropped whole, nearly all for ordering the T1.5 metal
  extractor `legmext15`, which the August 2026 patch removed, before their
  first contact; in the whole 8 minutes 4,320 are. Armada and Cortex lose 129
  openings between them, mostly to the same unit in games with Legion.
- **Random is common enough to matter.** 10,364 players (1.5%) picked Random
  or have no faction in the replay; their faction comes from what they
  ordered.
- **Every player has a skill and a result.** No opening lacks `skill` or
  `won`.

## Limits

- **Orders, not builds.** The dataset says what players asked for. Replaced
  and never-finished orders stay in; finishing needs re-simulated replays
  ([ADR 0010](../decisions/0010-re-simulate-replays-headlessly-for-game-state.md)).
- **Most ends are estimates.** 1,128 of the 670,814 openings end at a measured
  first contact. The others end at the median of their map and position, which
  is after the player's own contact for about half of them and before it for
  the rest; 8 to 11% of the orders kept that way were given after contact
  ([`first-contact.md`](../research/first-contact.md#cutoffs-for-games-that-were-not-re-simulated)).
- **Rosetta is rare.** 1,116 of the 42,095 games are on Rosetta, against about
  19,000 on each of the other two maps.
- **Small held-out sets per position.** Rosetta has about 110 games per
  held-out split in the whole slice, so about 110 openings per position.
