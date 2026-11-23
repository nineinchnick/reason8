# The opening dataset

Opening build orders of the training slice as a dataset: one row per build
order of every player's opening, split by game into train, validation and
test. An opening ends at the player's first contact with the enemy
([ADR 0019](adr/0019-end-openings-at-first-contact.md),
[`first-contact.md`](first-contact.md)); how games are split is
[ADR 0017](adr/0017-define-openings-by-time-and-split-games-by-match-id.md);
what is left out follows
[ADR 0012](adr/0012-keep-the-time-window-across-balance-patches.md) (balance
patches) and [ADR 0015](adr/0015-take-positions-from-the-map-metadata.md)
(positions). Code: `reason8/openings.py` (the orders), `reason8/contact.py`
(where an opening ends) and `reason8/opening_dataset.py` (the builder).

## Building it

```sh
uv run python -m reason8.map_metadata              # once: the pinned map list
uv run python -m reason8.contact                   # re-simulated games -> data/contact/
uv run python -m reason8.opening_dataset           # parsed replays -> data/datasets/openings_v2/
uv run python -m reason8.opening_dataset --stats   # the tables below
```

The games are those of `select_matches()` over the slice's pinned window
(2026-05-23 to 2026-11-22, [`dataset.md`](dataset.md)) whose replays are
parsed in `data/parsed/`. Building again reads whatever is parsed by then and
rewrites the dataset: a game's split depends only on its match id, so nothing
moves between splits as more replays are parsed. With 12 processes it reads
about 12 replays a second.

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
  (`reason8.contact.POSITION_CUTOFF_SECONDS`, the table in
  [`first-contact.md`](first-contact.md#per-map-and-position)).

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
: the opening, up to where it ends, orders a unit that the newest game in the
  dataset with the same factions loaded does not have
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

`openings_v2` as built on 2026-11-22 from the 5,066 slice replays parsed by
then, 11.8% of the 42,913 games, with the first contacts of the 72
re-simulated games of [`first-contact.md`](first-contact.md). The parsed
replays are not a random sample of the window. Rebuild and rerun `--stats` for
the whole slice.

### Size

| map                      | train games | validation games | test games | openings |
| ------------------------ | ----------- | ---------------- | ---------- | -------- |
| All That Glitters v2.2.3 | 1556        | 165              | 190        | 30501    |
| Rosetta 1.4.4            | 885         | 103              | 128        | 16964    |
| Supreme Isthmus v2.1     | 1590        | 180              | 174        | 30999    |

Rows (build orders) per split:

| split      | games | openings | rows    |
| ---------- | ----- | -------- | ------- |
| train      | 4031  | 63636    | 5354862 |
| validation | 448   | 7063     | 599359  |
| test       | 492   | 7765     | 635943  |

Games of the slice that were parsed, by status:

| status                                 | games |
| -------------------------------------- | ----- |
| changed water level                    | 8     |
| custom unit tweaks or stat multipliers | 87    |
| ok                                     | 4971  |

Openings of the games used, by status:

| status                | openings |
| --------------------- | -------- |
| ok                    | 78464    |
| orders a removed unit | 1072     |

- starts on the spot: 76940 of 78464 (98.1%)
- games that showed the recommended positions: 4903 of 4971
- start boxes: cannot tell 1124, changed 21, default 3826
- games with a balance-changing lobby option: 2933 of 4971

Games per opening era:

| opening era                         | first build | games |
| ----------------------------------- | ----------- | ----- |
| Season 3                            | 29241       | 204   |
| May balance patch                   | 30236       | 1757  |
| July balance patch                  | 30755       | 1010  |
| August balance patch                | 31075       | 610   |
| Air constructors and mobile jammers | 31357       | 1390  |

### Vocabulary per faction

| faction | unit names ordered | names for 99% of orders | orders  |
| ------- | ------------------ | ----------------------- | ------- |
| Armada  | 270                | 60                      | 3698744 |
| Cortex  | 262                | 62                      | 2538660 |
| Legion  | 189                | 64                      | 229999  |

### Sequence lengths

| map                      | openings | orders p10 | median | p90 | steps p10 | median | p90 |
| ------------------------ | -------- | ---------- | ------ | --- | --------- | ------ | --- |
| All That Glitters v2.2.3 | 30499    | 37         | 71     | 144 | 25        | 39     | 60  |
| Rosetta 1.4.4            | 16964    | 24         | 40     | 74  | 20        | 34     | 56  |
| Supreme Isthmus v2.1     | 30998    | 23         | 66     | 212 | 18        | 33     | 57  |

### Where openings end

Openings end at the player's first contact with the enemy, at the latest after
8 minutes (72 games with a measured contact).

| map                      | openings | measured contact | by position | whole window | end p10 | median | p90  | orders of the window kept |
| ------------------------ | -------- | ---------------- | ----------- | ------------ | ------- | ------ | ---- | ------------------------- |
| All That Glitters v2.2.3 | 30501    | 383              | 30118       | 0            | 3:15    | 3:50   | 8:00 | 67.2%                     |
| Rosetta 1.4.4            | 16964    | 363              | 16601       | 0            | 2:45    | 3:00   | 6:35 | 53.2%                     |
| Supreme Isthmus v2.1     | 30999    | 382              | 30617       | 0            | 2:05    | 4:55   | 8:00 | 69.5%                     |

### Top 20 openings (first 6 orders)

| opening                         | openings | share |
| ------------------------------- | -------- | ----- |
| `mex mex mex win win win`       | 15211    | 19.4% |
| `mex mex mex solar solar lab`   | 12358    | 15.8% |
| `mex mex mex solar win win`     | 5081     | 6.5%  |
| `tide tide tide tide tide tide` | 3726     | 4.7%  |
| `mex mex mex solar solar solar` | 3017     | 3.8%  |
| `mex mex mex solar solar vp`    | 2206     | 2.8%  |
| `mex mex win win win win`       | 1842     | 2.3%  |
| `mex mex mex mex solar solar`   | 1686     | 2.1%  |
| `mex mex mex solar mex solar`   | 1361     | 1.7%  |
| `mex mex mex solar solar win`   | 1174     | 1.5%  |
| `mex mex mex solar solar ap`    | 917      | 1.2%  |
| `mex mex win mex win win`       | 859      | 1.1%  |
| `mex mex win win mex win`       | 772      | 1.0%  |
| `mex mex mex mex win win`       | 720      | 0.9%  |
| `mex mex mex solar lab solar`   | 659      | 0.8%  |
| `mex mex mex solar mex mex`     | 655      | 0.8%  |
| `mex mex mex mex mex mex`       | 649      | 0.8%  |
| `mex mex mex win win lab`       | 566      | 0.7%  |
| `mex mex mex mex mex solar`     | 541      | 0.7%  |
| `mex mex win win win lab`       | 537      | 0.7%  |

### Per map and position

Openings from a start on the spot only. Factions count every opening of the
position.

#### All That Glitters v2.2.3

| position | role  | openings | on the spot | Armada | Cortex | Legion | first factory  | share | first 6 orders                | share |
| -------- | ----- | -------- | ----------- | ------ | ------ | ------ | -------------- | ----- | ----------------------------- | ----- |
| P1       | front | 1892     | 1863        | 970    | 884    | 38     | bot lab        | 65.5% | `mex mex mex solar solar lab` | 22.1% |
| P2       | air   | 1905     | 1891        | 287    | 1573   | 45     | aircraft plant | 94.2% | `mex mex mex win win win`     | 12.3% |
| P3       | tech  | 1886     | 1881        | 1512   | 354    | 20     | bot lab        | 91.8% | `mex mex mex win win win`     | 10.9% |
| P4       | front | 1879     | 1874        | 1042   | 785    | 52     | bot lab        | 60.2% | `mex mex mex solar solar lab` | 18.1% |
| P5       | front | 1920     | 1874        | 791    | 1091   | 38     | bot lab        | 79.9% | `mex mex mex solar solar lab` | 31.1% |
| P6       | front | 1925     | 1877        | 1032   | 866    | 27     | bot lab        | 71.8% | `mex mex mex solar solar lab` | 28.2% |
| P7       | front | 1931     | 1900        | 1089   | 801    | 41     | bot lab        | 73.8% | `mex mex mex solar solar lab` | 32.1% |
| P8       | front | 1913     | 1887        | 879    | 973    | 61     | bot lab        | 74.1% | `mex mex mex solar solar lab` | 31.5% |
| P9       | front | 1892     | 1871        | 974    | 879    | 39     | bot lab        | 64.4% | `mex mex mex solar solar lab` | 21.8% |
| P10      | air   | 1894     | 1889        | 292    | 1551   | 51     | aircraft plant | 94.1% | `mex mex mex win win win`     | 17.8% |
| P11      | tech  | 1905     | 1897        | 1476   | 415    | 14     | bot lab        | 90.8% | `mex mex mex mex solar solar` | 13.1% |
| P12      | front | 1866     | 1858        | 1042   | 788    | 36     | bot lab        | 59.0% | `mex mex mex solar solar lab` | 18.7% |
| P13      | front | 1937     | 1881        | 811    | 1075   | 51     | bot lab        | 78.4% | `mex mex mex solar solar lab` | 29.9% |
| P14      | front | 1933     | 1885        | 1028   | 869    | 36     | bot lab        | 68.8% | `mex mex mex solar solar lab` | 26.6% |
| P15      | front | 1935     | 1890        | 1107   | 794    | 34     | bot lab        | 73.3% | `mex mex mex solar solar lab` | 30.1% |
| P16      | front | 1888     | 1862        | 868    | 971    | 49     | bot lab        | 73.6% | `mex mex mex solar solar lab` | 32.4% |

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
| P1       | sea        | 1891     | 1836        | 846    | 1003   | 42     | bot lab        | 89.4% | `mex mex mex win win win`       | 64.7% |
| P2       | tech       | 1921     | 1908        | 1796   | 102    | 23     | bot lab        | 98.7% | `mex mex mex win win win`       | 74.5% |
| P3       | air        | 1938     | 1932        | 349    | 1536   | 53     | aircraft plant | 97.0% | `mex mex mex win win win`       | 66.4% |
| P4       | front      | 1949     | 1890        | 1409   | 484    | 56     | bot lab        | 73.7% | `tide tide tide tide tide tide` | 94.5% |
| P5       | front      | 1968     | 1886        | 1126   | 807    | 35     | bot lab        | 87.9% | `mex mex mex win win win`       | 1.8%  |
| P6       | front      | 1959     | 1899        | 1163   | 745    | 51     | bot lab        | 70.1% | `mex mex mex win win win`       | 3.6%  |
| P7       | front/tech | 1951     | 1921        | 1324   | 576    | 51     | bot lab        | 94.6% | `mex mex mex win win win`       | 30.7% |
| P8       | sea        | 1920     | 1875        | 817    | 1059   | 44     | shipyard       | 75.9% | `mex mex mex win win win`       | 51.4% |
| P9       | sea        | 1916     | 1862        | 859    | 1018   | 39     | bot lab        | 89.8% | `mex mex mex win win win`       | 68.0% |
| P10      | tech       | 1928     | 1917        | 1783   | 127    | 18     | bot lab        | 98.4% | `mex mex mex win win win`       | 75.7% |
| P11      | air        | 1935     | 1920        | 313    | 1575   | 47     | aircraft plant | 97.2% | `mex mex mex win win win`       | 68.4% |
| P12      | front      | 1939     | 1856        | 1386   | 507    | 46     | bot lab        | 74.4% | `tide tide tide tide tide tide` | 95.5% |
| P13      | front      | 1959     | 1882        | 1166   | 761    | 32     | bot lab        | 89.3% | `mex mex mex lab win win`       | 2.0%  |
| P14      | front      | 1937     | 1891        | 1188   | 698    | 51     | bot lab        | 67.9% | `mex mex mex win win win`       | 3.2%  |
| P15      | front/tech | 1956     | 1927        | 1372   | 540    | 44     | bot lab        | 94.7% | `mex mex mex win win win`       | 31.0% |
| P16      | sea        | 1932     | 1893        | 855    | 1038   | 39     | shipyard       | 72.9% | `mex mex mex win win win`       | 51.2% |

## Findings

- **A third of the first 8 minutes comes after first contact.** Ending
  openings at first contact keeps 66% of the build orders of the 8-minute
  window: 67% on Glitters, 53% on Rosetta and 70% on Isthmus. The median
  opening ends after 3:50, 3:00 and 4:55; a tenth end by 3:15, 2:45 and 2:05,
  and the tech positions keep their 8 minutes.
- **Half of all orders are drags.** 53% of the rows repeat the unit of the
  order before them in the same frame. An opening has a median of 40 to 71
  orders, but 33 to 39 steps once those repeats are merged (48 to 63 steps in
  the whole 8 minutes). The Isthmus pond positions (`P4`, `P12`) start with a
  dragged line of tidal generators in 95% of openings.
- **Few orders are queue edits.** 1.9% of the rows take units out of a factory
  queue, 0.9% are inserted into a queue and 0.1% come from the factory-quota
  widget; 72% were clicked and 78% were given with shift.
- **The vocabulary is small in practice.** Each faction ordered 189 to 270
  different units, but 60 to 64 names cover 99% of the orders.
- **The meta is in the first factory.** Tech and air positions agree on their
  first factory in 91 to 99% of openings on Isthmus and Glitters, and the
  exact first six orders are much less settled, as in
  [`maps/`](maps/README.md).
- **Legion loses fewer openings than with 8 minutes.** 1,041 of 5,176 Legion
  openings (20%) order the T1.5 metal extractor `legmext15`, which the August
  2026 patch removed, before their first contact, and are dropped whole; in
  the whole 8 minutes 1,853 do. Armada and Cortex lose 31 openings between
  them, to the same unit in games with Legion.
- **Random is common enough to matter.** 2,058 players (2.6%) picked Random or
  have no faction in the replay; their faction comes from what they ordered.
- **Every player has a skill and a result.** No opening lacks `skill` or
  `won`.

## Limits

- **Orders, not builds.** The dataset says what players asked for. Replaced
  and never-finished orders stay in; finishing needs re-simulated replays
  ([ADR 0002](adr/0002-recover-game-state-by-re-running-replays.md)).
- **Most ends are estimates.** 1,128 of the 78,464 openings end at a measured
  first contact. The others end at the median of their map and position, which
  is after the player's own contact for about half of them and before it for
  the rest; 8 to 11% of the orders kept that way were given after contact
  ([`first-contact.md`](first-contact.md#cutoffs-for-games-that-were-not-re-simulated)).
- **A partial slice.** The numbers above come from the first replays parsed,
  which are not a random sample of the window. The split is fixed per game, so
  they will change by adding games, not by moving them.
- **Small held-out sets per position.** Rosetta has about 110 games per
  held-out split in the whole slice, so about 110 openings per position.
