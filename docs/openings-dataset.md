# The opening dataset

Opening build orders of the training slice as a dataset: one row per build
order of every player's opening, split by game into train, validation and
test. What an opening is and how games are split is
[ADR 0017](adr/0017-define-openings-by-time-and-split-games-by-match-id.md);
what is left out follows
[ADR 0012](adr/0012-keep-the-time-window-across-balance-patches.md) (balance
patches) and [ADR 0015](adr/0015-take-positions-from-the-map-metadata.md)
(positions). Code: `reason8/openings.py` (the opening) and
`reason8/opening_dataset.py` (the builder).

## Building it

```sh
uv run python -m reason8.map_metadata              # once: the pinned map list
uv run python -m reason8.opening_dataset           # parsed replays -> data/datasets/openings_v1/
uv run python -m reason8.opening_dataset --stats   # the tables below
```

The games are those of `select_matches()` over the slice's pinned window
(2026-05-23 to 2026-11-22, [`dataset.md`](dataset.md)) whose replays are
parsed in `data/parsed/`. Building again reads whatever is parsed by then and
rewrites the dataset: a game's split depends only on its match id, so nothing
moves between splits as more replays are parsed. With 12 processes it reads
about 12 replays a second.

## What goes in

An opening is every build order a player gives in the first 8 minutes of game
time, the pregame queue included, in replay order. Every order is a row, also
those that take units out of a factory queue (`count` below 0, `seq_idx`
empty). Orders are intentions, not finished units
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
  ([ADR 0012](adr/0012-keep-the-time-window-across-balance-patches.md)); other
  balance options are kept and recorded

changed water level
: the `map_waterlevel` option changes the terrain

not two teams of 8
: the replay does not have two ally teams of 8 players each

unreadable replay
: the parsed file cannot be read

Openings left out (`openings.parquet`, column `status`):

orders a removed unit
: the opening orders a unit that the newest game in the dataset with the same
  factions loaded does not have
  ([ADR 0012](adr/0012-keep-the-time-window-across-balance-patches.md)). Games
  with Legion are compared with the newest game with Legion, the others with
  the newest game without it, because a game with Legion defines 244 more
  units.

Kept and flagged instead
([ADR 0015](adr/0015-take-positions-from-the-map-metadata.md)): starts that
are not on the spot of their position (`on_spot`), games that did not show the
recommended positions (`positions_shown`) and games whose start boxes are not
the map's default (`default_boxes`: false, or empty when it cannot be told).

Players who picked Random (or whose faction the replay does not know) get the
faction whose units they ordered most; `faction_picked` keeps what the lobby
said.

## Files

`train.parquet`, `validation.parquet`, `test.parquet`
: One row per build order, sorted by match, player and order.

`openings.parquet`
: One row per player of every game used, with the split, the status and the
  removed units, and the number of orders (`orders`, `added`).

`games.parquet`
: One row per parsed game of the slice, with the split and the status.

`splits/train.txt`, `splits/validation.txt`, `splits/test.txt`
: The match ids of each split.

`manifest.json`
: What went in: the selection, the split rule, the reference builds of the
  vocabulary, the parser versions, the counts and the code version (commit,
  and whether the tree had uncommitted changes).

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
  opening-changing balance patch (`reason8.game_versions`)

`balance_options`
: The balance-changing lobby options that are on, as a JSON object (`{}` in a
  standard game)

`positions_shown`, `default_boxes`
: How the start was set up (`reason8.positions.start_setup()`)

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
  (`reason8.positions.replay_positions()`)

`won`
: Whether the player's ally team won

`skill`
: OpenSkill mu before the game (`old_skill` of the match dump)

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
`status` and `removed_units`. `games.parquet` has the game columns,
`team_count`, `opening_era_name`, `factions` (the unit name prefixes of the
factions loaded), `positions_source`, `parser`, `replay_file_name`,
`game_duration` and `avg_skill`.

## Statistics

Built on 2026-11-22 from the 3,597 slice replays parsed by then, 8.4% of the
42,913 games. The replays were parsed in the order of their file names, so
these games are mostly from May to August 2026 (3,140 of 3,510) and the newest
opening eras are thin. Rebuild and rerun `--stats` for the whole slice.

### Size

| map                      | train games | validation games | test games | openings |
| ------------------------ | ----------- | ---------------- | ---------- | -------- |
| All That Glitters v2.2.3 | 1095        | 116              | 132        | 21328    |
| Rosetta 1.4.4            | 679         | 79               | 92         | 11992    |
| Supreme Isthmus v2.1     | 1078        | 120              | 119        | 20941    |

Rows (build orders) per split:

| split      | games | openings | rows    |
| ---------- | ----- | -------- | ------- |
| train      | 2852  | 44100    | 5611143 |
| validation | 315   | 4862     | 624596  |
| test       | 343   | 5299     | 662177  |

Games of the slice that were parsed, by status:

| status                                 | games |
| -------------------------------------- | ----- |
| changed water level                    | 8     |
| custom unit tweaks or stat multipliers | 79    |
| ok                                     | 3510  |

Openings of the games used, by status:

| status                | openings |
| --------------------- | -------- |
| ok                    | 54261    |
| orders a removed unit | 1899     |

- starts on the spot: 53269 of 54261 (98.2%)
- games that showed the recommended positions: 3442 of 3510
- start boxes: cannot tell 1124, changed 4, default 2382
- games with a balance-changing lobby option: 2412 of 3510

Games per opening era:

| opening era                         | first build | games |
| ----------------------------------- | ----------- | ----- |
| Season 3                            | 29241       | 204   |
| May balance patch                   | 30236       | 1757  |
| July balance patch                  | 30755       | 1010  |
| August balance patch                | 31075       | 444   |
| Air constructors and mobile jammers | 31357       | 95    |

### Vocabulary per faction

| faction | unit names ordered | names for 99% of orders | orders  |
| ------- | ------------------ | ----------------------- | ------- |
| Armada  | 292                | 67                      | 3624318 |
| Cortex  | 294                | 70                      | 2850363 |
| Legion  | 222                | 75                      | 253448  |

### Sequence lengths

| map                      | openings | orders p10 | median | p90 | steps p10 | median | p90 |
| ------------------------ | -------- | ---------- | ------ | --- | --------- | ------ | --- |
| All That Glitters v2.2.3 | 21326    | 67         | 112    | 196 | 38        | 56     | 82  |
| Rosetta 1.4.4            | 11992    | 54         | 80     | 122 | 43        | 63     | 86  |
| Supreme Isthmus v2.1     | 20941    | 56         | 106    | 269 | 30        | 48     | 71  |

### Top 20 openings (first 6 orders)

| opening                         | openings | share |
| ------------------------------- | -------- | ----- |
| `mex mex mex win win win`       | 10423    | 19.2% |
| `mex mex mex solar solar lab`   | 8568     | 15.8% |
| `mex mex mex solar win win`     | 3609     | 6.7%  |
| `tide tide tide tide tide tide` | 2514     | 4.6%  |
| `mex mex mex solar solar solar` | 2032     | 3.7%  |
| `mex mex mex solar solar vp`    | 1621     | 3.0%  |
| `mex mex mex mex solar solar`   | 1214     | 2.2%  |
| `mex mex win win win win`       | 1213     | 2.2%  |
| `mex mex mex solar mex solar`   | 900      | 1.7%  |
| `mex mex mex solar solar win`   | 826      | 1.5%  |
| `mex mex win mex win win`       | 608      | 1.1%  |
| `mex mex mex solar solar ap`    | 608      | 1.1%  |
| `mex mex win win mex win`       | 526      | 1.0%  |
| `mex mex mex solar lab solar`   | 487      | 0.9%  |
| `mex mex mex mex win win`       | 486      | 0.9%  |
| `mex mex mex mex mex mex`       | 481      | 0.9%  |
| `mex mex mex solar mex mex`     | 463      | 0.9%  |
| `mex mex mex win win lab`       | 422      | 0.8%  |
| `mex mex mex mex mex solar`     | 418      | 0.8%  |
| `mex mex win win win lab`       | 362      | 0.7%  |

### Per map and position

Openings from a start on the spot only. Factions count every opening of the
position.

#### All That Glitters v2.2.3

| position | role  | openings | on the spot | Armada | Cortex | Legion | first factory  | share | first 6 orders                | share |
| -------- | ----- | -------- | ----------- | ------ | ------ | ------ | -------------- | ----- | ----------------------------- | ----- |
| P1       | front | 1322     | 1303        | 690    | 602    | 30     | bot lab        | 61.9% | `mex mex mex solar solar lab` | 21.4% |
| P2       | air   | 1333     | 1323        | 211    | 1083   | 39     | aircraft plant | 94.1% | `mex mex mex win win win`     | 12.0% |
| P3       | tech  | 1325     | 1322        | 1062   | 248    | 15     | bot lab        | 92.1% | `mex mex mex win win win`     | 10.9% |
| P4       | front | 1318     | 1314        | 736    | 546    | 36     | bot lab        | 58.0% | `mex mex mex solar win win`   | 16.9% |
| P5       | front | 1345     | 1314        | 544    | 772    | 29     | bot lab        | 78.9% | `mex mex mex solar solar lab` | 29.8% |
| P6       | front | 1343     | 1312        | 733    | 589    | 21     | bot lab        | 71.2% | `mex mex mex solar solar lab` | 27.9% |
| P7       | front | 1355     | 1331        | 762    | 565    | 28     | bot lab        | 71.8% | `mex mex mex solar solar lab` | 30.4% |
| P8       | front | 1325     | 1306        | 613    | 674    | 38     | bot lab        | 72.8% | `mex mex mex solar solar lab` | 29.5% |
| P9       | front | 1326     | 1310        | 682    | 615    | 29     | bot lab        | 62.0% | `mex mex mex solar solar lab` | 19.8% |
| P10      | air   | 1332     | 1329        | 213    | 1079   | 40     | aircraft plant | 93.5% | `mex mex mex win win win`     | 17.3% |
| P11      | tech  | 1335     | 1329        | 1049   | 273    | 13     | bot lab        | 91.8% | `mex mex mex mex solar solar` | 12.3% |
| P12      | front | 1305     | 1300        | 731    | 547    | 27     | bot lab        | 56.5% | `mex mex mex solar solar lab` | 16.6% |
| P13      | front | 1342     | 1306        | 549    | 761    | 32     | bot lab        | 76.5% | `mex mex mex solar solar lab` | 29.0% |
| P14      | front | 1360     | 1323        | 723    | 610    | 27     | bot lab        | 67.6% | `mex mex mex solar solar lab` | 25.2% |
| P15      | front | 1350     | 1317        | 760    | 569    | 21     | bot lab        | 72.7% | `mex mex mex solar solar lab` | 29.5% |
| P16      | front | 1312     | 1299        | 614    | 666    | 32     | bot lab        | 71.7% | `mex mex mex solar solar lab` | 31.9% |

#### Rosetta 1.4.4

| position | role       | openings | on the spot | Armada | Cortex | Legion | first factory  | share | first 6 orders                  | share |
| -------- | ---------- | -------- | ----------- | ------ | ------ | ------ | -------------- | ----- | ------------------------------- | ----- |
| P1       | front      | 828      | 811         | 302    | 419    | 107    | bot lab        | 94.7% | `mex mex mex solar solar lab`   | 42.3% |
| P2       | front/tech | 753      | 748         | 310    | 330    | 113    | bot lab        | 96.4% | `mex mex mex solar solar lab`   | 26.7% |
| P3       | front      | 820      | 778         | 336    | 371    | 113    | bot lab        | 77.9% | `mex mex mex solar solar lab`   | 47.2% |
| P4       | front      | 557      | 527         | 261    | 245    | 51     | bot lab        | 85.6% | `mex mex solar solar lab solar` | 11.8% |
| P5       | air        | 690      | 686         | 68     | 451    | 171    | aircraft plant | 75.7% | `mex mex mex solar solar ap`    | 21.7% |
| P6       | front      | 774      | 729         | 340    | 341    | 93     | bot lab        | 76.4% | `mex mex mex solar solar lab`   | 36.8% |
| P7       | front/tech | 792      | 790         | 424    | 263    | 105    | bot lab        | 96.6% | `mex mex mex solar solar lab`   | 37.3% |
| P8       | front      | 782      | 762         | 252    | 412    | 118    | bot lab        | 95.5% | `mex mex mex solar solar lab`   | 52.6% |
| P9       | front      | 816      | 806         | 308    | 406    | 102    | bot lab        | 94.5% | `mex mex mex solar solar lab`   | 39.5% |
| P10      | front/tech | 757      | 754         | 328    | 317    | 112    | bot lab        | 95.1% | `mex mex mex solar mex solar`   | 26.8% |
| P11      | front      | 817      | 791         | 347    | 348    | 122    | bot lab        | 74.0% | `mex mex mex solar solar lab`   | 45.9% |
| P12      | front      | 558      | 536         | 270    | 244    | 44     | bot lab        | 86.0% | `mex mex solar solar lab solar` | 7.8%  |
| P13      | air        | 700      | 698         | 63     | 499    | 138    | aircraft plant | 78.1% | `mex mex mex solar solar ap`    | 21.1% |
| P14      | front      | 768      | 731         | 346    | 307    | 115    | bot lab        | 78.5% | `mex mex mex solar solar lab`   | 37.8% |
| P15      | front/tech | 795      | 791         | 418    | 263    | 114    | bot lab        | 97.9% | `mex mex mex solar solar lab`   | 37.9% |
| P16      | front      | 785      | 761         | 269    | 405    | 111    | bot lab        | 95.8% | `mex mex mex solar solar lab`   | 55.8% |

#### Supreme Isthmus v2.1

| position | role       | openings | on the spot | Armada | Cortex | Legion | first factory  | share | first 6 orders                  | share |
| -------- | ---------- | -------- | ----------- | ------ | ------ | ------ | -------------- | ----- | ------------------------------- | ----- |
| P1       | sea        | 1276     | 1262        | 563    | 689    | 24     | bot lab        | 89.7% | `mex mex mex win win win`       | 64.8% |
| P2       | tech       | 1301     | 1293        | 1222   | 66     | 13     | bot lab        | 98.6% | `mex mex mex win win win`       | 73.6% |
| P3       | air        | 1303     | 1300        | 240    | 1027   | 36     | aircraft plant | 97.2% | `mex mex mex win win win`       | 66.7% |
| P4       | front      | 1309     | 1278        | 948    | 326    | 35     | bot lab        | 74.6% | `tide tide tide tide tide tide` | 95.0% |
| P5       | front      | 1337     | 1282        | 771    | 541    | 25     | bot lab        | 86.3% | `lab mex win win mex mex`       | 2.2%  |
| P6       | front      | 1327     | 1282        | 781    | 514    | 32     | bot lab        | 69.0% | `mex mex mex win win win`       | 3.9%  |
| P7       | front/tech | 1312     | 1292        | 888    | 390    | 34     | bot lab        | 94.5% | `mex mex mex win win win`       | 30.1% |
| P8       | sea        | 1305     | 1276        | 579    | 698    | 28     | shipyard       | 74.3% | `mex mex mex win win win`       | 49.7% |
| P9       | sea        | 1299     | 1286        | 581    | 698    | 20     | bot lab        | 89.7% | `mex mex mex win win win`       | 67.2% |
| P10      | tech       | 1308     | 1301        | 1204   | 92     | 12     | bot lab        | 98.2% | `mex mex mex win win win`       | 75.0% |
| P11      | air        | 1301     | 1291        | 227    | 1040   | 34     | aircraft plant | 97.2% | `mex mex mex win win win`       | 67.5% |
| P12      | front      | 1311     | 1257        | 930    | 348    | 33     | bot lab        | 74.5% | `tide tide tide tide tide tide` | 95.1% |
| P13      | front      | 1322     | 1267        | 782    | 517    | 23     | bot lab        | 88.7% | `mex mex mex lab win win`       | 2.4%  |
| P14      | front      | 1311     | 1284        | 819    | 462    | 30     | bot lab        | 67.1% | `mex mex mex win win win`       | 3.6%  |
| P15      | front/tech | 1316     | 1299        | 920    | 369    | 27     | bot lab        | 94.5% | `mex mex mex win win win`       | 30.3% |
| P16      | sea        | 1303     | 1280        | 603    | 676    | 24     | shipyard       | 71.6% | `mex mex mex win win win`       | 50.5% |

## Findings

- **Half of all orders are drags.** 53% of the rows repeat the unit of the
  order before them in the same frame. An opening has a median of 80 to 112
  orders in 8 minutes, but 48 to 63 steps once those repeats are merged. The
  Isthmus pond positions (`P4`, `P12`) start with a dragged line of tidal
  generators in 95% of openings.
- **Few orders are queue edits.** 2.4% of the rows take units out of a factory
  queue, 1.1% are inserted into a queue and 0.1% come from the factory-quota
  widget; 75% were clicked and 77% were given with shift.
- **The vocabulary is small in practice.** Each faction ordered 222 to 294
  different units in the first 8 minutes, but 67 to 75 names cover 99% of the
  orders.
- **The meta is in the first factory.** Tech and air positions agree on their
  first factory in 92 to 99% of openings on Isthmus and Glitters, and the
  exact first six orders are much less settled, as in
  [`maps/`](maps/README.md).
- **Legion loses many openings.** 1,853 of 4,469 Legion openings (41%) order
  the T1.5 metal extractor `legmext15`, which the August 2026 patch removed,
  and are dropped whole. Armada and Cortex lose 46 openings between them, to
  the same unit in games with Legion.
- **Random is common enough to matter.** 1,470 players (2.6%) picked Random or
  have no faction in the replay; their faction comes from what they ordered.
- **Every player has a skill and a result.** No opening lacks `skill` or
  `won`.

## Limits

- **Orders, not builds.** The dataset says what players asked for. Replaced
  and never-finished orders stay in; finishing needs re-simulated replays
  ([ADR 0002](adr/0002-recover-game-state-by-re-running-replays.md)).
- **A partial slice.** The numbers above come from the first replays parsed,
  which are not a random sample of the window. The split is fixed per game, so
  they will change by adding games, not by moving them.
- **Small held-out sets per position.** Rosetta has about 110 games per
  held-out split in the whole slice, so about 110 openings per position.
