# Rosetta 1.4.4

The small third map of the slice, played by much stronger lobbies than the
other two: a dry asteroid, two teams of 8 on the long edges, a front line of
five. Like All That Glitters it has three roles. Method, sample and the terms
used in the tables are in [`README.md`](README.md).

## The map

From the map file (`mapinfo.lua`, the resource spot layout and the placed
features) and the
[official map page](https://www.beyondallreason.info/map/rosetta):

size
: 20 × 16, that is 10,240 × 8,192 map units; by Moose; 16 players

layout
: a half turn about a point some 40 units north of the middle: all 138 metal
  spots have their image within 100 units

water
: none at the default water level. Two of 83 games were played with the
  `map_waterlevel` lobby option changed; they are left out of the
  measurements.

wind
: 0 to 10

metal
: 138 spots: 136 worth 1.0, 2.0 or 3.0 and two worth 10.1, one in front of
  `P4` and `P12`, 1,560 units towards the middle

geothermal vents
: 10, five per side; the nearest is 660 to 1,530 units from where a position
  starts

reclaim
: the map file places 132 moon rocks

## Positions

The map metadata recommends eight start positions per side for 8v8, sixteen
positions in all: `P1` to `P8` for the west side and `P9` to `P16` for the
east side. The two sides list the same roles in the same order, so the
positions come in pairs that are each other's image on the map; they are
described together here but measured apart. Percentages are given for the
first and the second position of a pair. What each position orders is in
[What sets each position apart](#what-sets-each-position-apart); how far
players start from the recommended point is in
[Starts and recommended positions](#starts-and-recommended-positions).

`P1` and `P9`, front
: *Where:* the end of the front line at the map edge
: *Opens with:* a bot lab (98% and 96%)

`P2` and `P10`, front/tech
: *Where:* back row, behind `P1` and `P9`
: *Community name:* tech spot
: *Opens with:* a bot lab (99% and 95%), a geothermal plant before two minutes
  (96% and 96%) and an advanced bot lab soon after four minutes (92% and 91%)

`P3` and `P11`, front
: *Where:* front line, between the end and the middle
: *Opens with:* a bot lab (76% and 78%) or a vehicle plant

`P4` and `P12`, front
: *Where:* the middle of the front line. The metadata adds a "base center"
  1,560 units further forward, at the 10.1 metal spot: "Move your Commander
  here shortly after spawning. Build your first factory in this area."
: *Opens with:* a bot lab (87% and 85%); the least settled build order of the
  map

`P5` and `P13`, air
: *Where:* back row, behind the middle
: *Community name:* air
: *Opens with:* an aircraft plant (79% and 86% as first factory, 100% within 8
  minutes)

`P6` and `P14`, front
: *Where:* front line, between the middle and the other end
: *Opens with:* a bot lab (68% and 82%) or a vehicle plant

`P7` and `P15`, front/tech
: *Where:* back row, behind `P8` and `P16`
: *Community name:* tech spot
: *Opens with:* a bot lab (94% and 98%), a geothermal plant before two minutes
  (100% and 99%) and an advanced bot lab soon after four minutes (90% and 88%)

`P8` and `P16`, front
: *Where:* the other end of the front line
: *Opens with:* a bot lab (96% and 100%) and a geothermal plant around three
  and a half minutes (91% and 99%)

**Community names are labels here, not keys.** For the ten front positions we
found none we could place: "hill" and "speedbump" (or "speed bump") come from
video titles and descriptions, and no source we read says which start
positions they are.

## Sources

[maps-metadata `map_list.yaml`](https://github.com/beyond-all-reason/maps-metadata/blob/main/map_list.yaml)
: *What:* BAR's own map list, the source of the positions: 16 recommended
  start positions for this map with a role each (per side: 5 front, 2
  front/tech, 1 air), a base centre for the middle front position, and the
  default start boxes.
: *Read:* the file itself at the pinned commit; the same positions are in the
  `mapmetadata_startpos` lobby option of all our replays

[Official map page](https://www.beyondallreason.info/map/rosetta)
: *What:* size, wind 0 to 10, tidal 20, terrain "asteroid, flat, hills"
: *Read:* the page; size, wind and tidal checked against the map file

[BetterStrategy, "T3 Rush and Juggernaut Follow-Up | 8v8 Rosetta | Tech Spot | Beyond All Reason"](https://www.youtube.com/watch?v=GgApS_8pdc0)
: *What:* a game from a tech spot
: *Read:* title only; nobody watched it

[simplygraceful\_, "This Position Is Hell on BAR | Beyond All Reason | Rosetta | Hill"](https://www.youtube.com/watch?v=ntb2R2TBIJI)
: *What:* a game from the position called "hill"; other videos of the channel
  name a position "speedbump"
: *Read:* title only

We found no written guide for Rosetta.

## Start setup

| games with                      | games | openings | on a spot |
| ------------------------------- | ----- | -------- | --------- |
| recommended positions shown     | 81    | 1296     | 97.1%     |
| recommended positions not shown | 0     | 0        | -         |
| default start boxes             | 81    | 1296     | 97.1%     |
| changed start boxes             | 0     | 0        | -         |
| start boxes not comparable      | 0     | 0        | -         |

- **Positions shown.** All games showed the recommended positions.
- **Start boxes.** All games used the map's default boxes, the left and the
  right fifth of the map: 34 of the 83 parsed games by their own lobby option,
  49 older ones by the pinned map list. Which team gets which edge changes
  from game to game.

### Starts and recommended positions

From `python -m reason8.positions`, on all 83 parsed games (the two with a
changed water level included): the starts nearest to each position, how many
are "on the spot" (nearer than half the way to the next recommended position),
and their distance from the recommended point in map units.

| position | role       | nearest starts | on the spot | median | 90% within |
| -------- | ---------- | -------------- | ----------- | ------ | ---------- |
| P1       | front      | 87             | 94.3%       | 47     | 110        |
| P2       | front/tech | 83             | 97.6%       | 67     | 118        |
| P3       | front      | 84             | 95.2%       | 24     | 63         |
| P4       | front      | 83             | 95.2%       | 76     | 279        |
| P5       | air        | 83             | 100.0%      | 47     | 96         |
| P6       | front      | 80             | 93.8%       | 50     | 270        |
| P7       | front/tech | 82             | 98.8%       | 58     | 97         |
| P8       | front      | 82             | 97.6%       | 57     | 79         |
| P9       | front      | 84             | 100.0%      | 64     | 105        |
| P10      | front/tech | 81             | 100.0%      | 81     | 141        |
| P11      | front      | 82             | 97.6%       | 29     | 52         |
| P12      | front      | 85             | 98.8%       | 80     | 285        |
| P13      | air        | 80             | 100.0%      | 74     | 119        |
| P14      | front      | 85             | 92.9%       | 52     | 249        |
| P15      | front/tech | 84             | 97.6%       | 76     | 112        |
| P16      | front      | 83             | 95.2%       | 111    | 122        |

## The two sides

The spawn points of the two sides are different positions. Whether the two
sides nevertheless open alike is checked here: each opening is given its place
in its side's list (`P1` and `P9` are both first), and the first side is
compared with the second by the total variation distance of a feature per
place, next to the same distance after shuffling whole teams between the sides
1,000 times.

First side against second side, 81 teams against 81:

| feature                 | distance | shuffled mean | shuffled 95% | p     |
| ----------------------- | -------- | ------------- | ------------ | ----- |
| first factory per place | 0.046    | 0.042         | 0.061        | 0.347 |
| opening shape per place | 0.289    | 0.286         | 0.313        | 0.419 |
| faction per place       | 0.093    | 0.104         | 0.133        | 0.717 |

Share of the most common first factory at the same place of the two lists:

| first side    | second side    | first factory  | first side | second side |
| ------------- | -------------- | -------------- | ---------- | ----------- |
| P1 front      | P9 front       | bot lab        | 98% of 80  | 96% of 82   |
| P2 front/tech | P10 front/tech | bot lab        | 99% of 79  | 95% of 79   |
| P3 front      | P11 front      | bot lab        | 76% of 78  | 78% of 78   |
| P4 front      | P12 front      | bot lab        | 87% of 77  | 85% of 82   |
| P5 air        | P13 air        | aircraft plant | 79% of 81  | 86% of 78   |
| P6 front      | P14 front      | bot lab        | 68% of 73  | 82% of 78   |
| P7 front/tech | P15 front/tech | bot lab        | 94% of 79  | 98% of 80   |
| P8 front      | P16 front      | bot lab        | 96% of 78  | 100% of 77  |

No distance stands clear of its shuffled values: the two sides open alike. The
largest gap in the table below is 14 points, at `P6` and `P14`.

## Measurements

81 games, 1296 openings, 1259 of 1296 (97.1%) on a spot, 940 of those by
players with mu >= 30.

124 of 162 (76.5%) teams fill all 8 spots; 8 teams have two players on one
spot.

### Consistency per position, all players

| position       | openings | first factory  | share | entropy | agree |
| -------------- | -------- | -------------- | ----- | ------- | ----- |
| P1 front       | 80       | bot lab        | 98%   | 0.17    | 95%   |
| P2 front/tech  | 79       | bot lab        | 99%   | 0.10    | 97%   |
| P3 front       | 78       | bot lab        | 76%   | 0.80    | 63%   |
| P4 front       | 77       | bot lab        | 87%   | 0.56    | 77%   |
| P5 air         | 81       | aircraft plant | 79%   | 0.81    | 66%   |
| P6 front       | 73       | bot lab        | 68%   | 0.90    | 56%   |
| P7 front/tech  | 79       | bot lab        | 94%   | 0.34    | 88%   |
| P8 front       | 78       | bot lab        | 96%   | 0.24    | 93%   |
| P9 front       | 82       | bot lab        | 96%   | 0.23    | 93%   |
| P10 front/tech | 79       | bot lab        | 95%   | 0.29    | 90%   |
| P11 front      | 78       | bot lab        | 78%   | 0.76    | 65%   |
| P12 front      | 82       | bot lab        | 85%   | 0.66    | 74%   |
| P13 air        | 78       | aircraft plant | 86%   | 0.59    | 75%   |
| P14 front      | 78       | bot lab        | 82%   | 0.68    | 70%   |
| P15 front/tech | 80       | bot lab        | 98%   | 0.19    | 95%   |
| P16 front      | 77       | bot lab        | 100%  | 0.00    | 100%  |

| position       | openings | opening shape: distinct | top share | entropy | agree | first 6 orders: distinct | top share | entropy | agree |
| -------------- | -------- | ----------------------- | --------- | ------- | ----- | ------------------------ | --------- | ------- | ----- |
| P1 front       | 80       | 24                      | 38%       | 3.45    | 17%   | 33                       | 39%       | 3.75    | 17%   |
| P2 front/tech  | 79       | 19                      | 28%       | 3.07    | 17%   | 25                       | 33%       | 3.58    | 14%   |
| P3 front       | 78       | 18                      | 32%       | 3.10    | 17%   | 15                       | 53%       | 2.45    | 31%   |
| P4 front       | 77       | 32                      | 22%       | 4.28    | 8%    | 53                       | 8%        | 5.47    | 2%    |
| P5 air         | 81       | 27                      | 26%       | 3.97    | 9%    | 28                       | 23%       | 3.89    | 10%   |
| P6 front       | 73       | 17                      | 33%       | 3.26    | 15%   | 16                       | 36%       | 3.00    | 18%   |
| P7 front/tech  | 79       | 12                      | 48%       | 2.19    | 32%   | 15                       | 42%       | 2.98    | 20%   |
| P8 front       | 78       | 18                      | 44%       | 2.63    | 27%   | 20                       | 59%       | 2.61    | 35%   |
| P9 front       | 82       | 25                      | 34%       | 3.65    | 14%   | 33                       | 38%       | 3.76    | 16%   |
| P10 front/tech | 79       | 14                      | 37%       | 2.64    | 22%   | 18                       | 30%       | 3.08    | 17%   |
| P11 front      | 78       | 19                      | 41%       | 2.99    | 21%   | 19                       | 45%       | 2.83    | 24%   |
| P12 front      | 82       | 36                      | 22%       | 4.27    | 8%    | 58                       | 6%        | 5.66    | 1%    |
| P13 air        | 78       | 29                      | 23%       | 4.17    | 8%    | 29                       | 22%       | 3.87    | 11%   |
| P14 front      | 78       | 21                      | 31%       | 3.45    | 14%   | 26                       | 41%       | 3.51    | 18%   |
| P15 front/tech | 80       | 12                      | 41%       | 2.25    | 28%   | 13                       | 31%       | 2.99    | 16%   |
| P16 front      | 77       | 12                      | 47%       | 2.40    | 28%   | 16                       | 68%       | 2.08    | 46%   |

Most common opening shape:

- P1 front: `mex solar lab solar` 38%; `mex solar lab ck` 14%;
  `mex solar mex lab` 6%
- P2 front/tech: `mex solar lab solar` 28%; `mex solar mex solar` 25%;
  `mex solar lab ck` 15%
- P3 front: `mex solar lab solar` 32%; `mex solar lab ck` 23%;
  `mex solar vp cv` 9%
- P4 front: `mex solar lab solar` 22%; `mex solar lab ck` 14%;
  `mex lab solar ck` 5%
- P5 air: `mex solar ap solar` 26%; `mex solar estor solar` 9%;
  `mex solar mex solar` 9%
- P6 front: `mex solar lab solar` 33%; `mex solar vp solar` 15%;
  `mex solar lab ck` 11%
- P7 front/tech: `mex solar lab solar` 48%; `mex solar mex solar` 29%;
  `mex solar lab ck` 8%
- P8 front: `mex solar lab solar` 44%; `mex solar lab ck` 28%;
  `mex solar mex solar` 5%
- P9 front: `mex solar lab solar` 34%; `mex solar lab ck` 10%;
  `mex solar mex lab` 7%
- P10 front/tech: `mex solar mex solar` 37%; `mex solar lab solar` 25%;
  `mex solar lab ck` 13%
- P11 front: `mex solar lab solar` 41%; `mex solar lab ck` 17%;
  `mex solar vp solar` 12%
- P12 front: `mex solar lab solar` 22%; `mex llt mex solar` 13%;
  `mex solar lab ck` 12%
- P13 air: `mex solar ap solar` 23%; `mex solar mex solar` 12%;
  `mex solar ap fink` 8%
- P14 front: `mex solar lab solar` 31%; `mex solar lab ck` 19%;
  `mex solar vp cv` 6%
- P15 front/tech: `mex solar mex solar` 41%; `mex solar lab solar` 32%;
  `mex solar lab ck` 12%
- P16 front: `mex solar lab solar` 47%; `mex solar lab ck` 22%;
  `mex solar mex solar` 10%

Most common first 6 orders:

- P1 front: `mex mex mex solar solar lab` 39%; `mex mex mex solar solar solar`
  12%; `mex mex mex win win win` 5%
- P2 front/tech: `mex mex mex solar solar lab` 33%;
  `mex mex mex solar mex solar` 16%; `mex mex mex mex solar solar` 8%
- P3 front: `mex mex mex solar solar lab` 53%; `mex mex mex solar solar vp`
  17%; `mex mex mex solar solar solar` 9%
- P4 front: `mex mex solar solar lab solar` 8%; `mex mex solar solar lab ck`
  6%; `mex mex solar lab solar solar` 6%
- P5 air: `mex mex mex solar solar ap` 23%; `mex mex mex solar solar solar`
  19%; `mex mex mex solar solar lab` 10%
- P6 front: `mex mex mex solar solar lab` 36%; `mex mex mex solar solar vp`
  19%; `mex mex mex solar solar solar` 11%
- P7 front/tech: `mex mex mex solar solar lab` 42%;
  `mex mex mex solar mex solar` 13%; `mex mex mex solar mex mex` 11%
- P8 front: `mex mex mex solar solar lab` 59%; `mex mex mex solar solar solar`
  6%; `mex mex mex solar mex solar` 5%
- P9 front: `mex mex mex solar solar lab` 38%; `mex mex mex solar solar solar`
  15%; `mex mex mex mex solar lab` 4%
- P10 front/tech: `mex mex mex solar mex solar` 30%;
  `mex mex mex solar solar lab` 27%; `mex mex mex mex solar solar` 10%
- P11 front: `mex mex mex solar solar lab` 45%;
  `mex mex mex solar solar solar` 14%; `mex mex mex solar solar vp` 14%
- P12 front: `mex mex solar solar lab solar` 6%; `mex mex solar solar lab ck`
  5%; `mex mex solar lab solar solar` 5%
- P13 air: `mex mex mex solar solar solar` 22%; `mex mex mex solar solar ap`
  22%; `mex mex mex mex solar solar` 10%
- P14 front: `mex mex mex solar solar lab` 41%; `mex mex mex solar solar vp`
  9%; `mex mex mex solar solar solar` 8%
- P15 front/tech: `mex mex mex solar solar lab` 31%;
  `mex mex mex solar mex mex` 21%; `mex mex mex solar mex solar` 10%
- P16 front: `mex mex mex solar solar lab` 68%;
  `mex mex mex solar solar solar` 6%; `mex mex mex solar mex solar` 5%

### Consistency per position, mu ≥ 30

| position       | openings | first factory  | share | entropy | agree |
| -------------- | -------- | -------------- | ----- | ------- | ----- |
| P1 front       | 42       | bot lab        | 100%  | 0.00    | 100%  |
| P2 front/tech  | 55       | bot lab        | 100%  | 0.00    | 100%  |
| P3 front       | 44       | bot lab        | 75%   | 0.81    | 62%   |
| P4 front       | 57       | bot lab        | 84%   | 0.63    | 73%   |
| P5 air         | 52       | aircraft plant | 71%   | 0.97    | 57%   |
| P6 front       | 66       | bot lab        | 68%   | 0.90    | 56%   |
| P7 front/tech  | 77       | bot lab        | 94%   | 0.35    | 88%   |
| P8 front       | 66       | bot lab        | 98%   | 0.11    | 97%   |
| P9 front       | 52       | bot lab        | 96%   | 0.24    | 92%   |
| P10 front/tech | 65       | bot lab        | 97%   | 0.20    | 94%   |
| P11 front      | 40       | bot lab        | 80%   | 0.72    | 67%   |
| P12 front      | 61       | bot lab        | 87%   | 0.63    | 76%   |
| P13 air        | 48       | aircraft plant | 81%   | 0.70    | 69%   |
| P14 front      | 71       | bot lab        | 82%   | 0.69    | 70%   |
| P15 front/tech | 77       | bot lab        | 97%   | 0.20    | 95%   |
| P16 front      | 67       | bot lab        | 100%  | 0.00    | 100%  |

| position       | openings | opening shape: distinct | top share | entropy | agree | first 6 orders: distinct | top share | entropy | agree |
| -------------- | -------- | ----------------------- | --------- | ------- | ----- | ------------------------ | --------- | ------- | ----- |
| P1 front       | 42       | 11                      | 57%       | 2.36    | 33%   | 17                       | 48%       | 2.96    | 23%   |
| P2 front/tech  | 55       | 11                      | 33%       | 2.60    | 21%   | 17                       | 31%       | 3.24    | 15%   |
| P3 front       | 44       | 10                      | 34%       | 2.68    | 19%   | 8                        | 57%       | 1.98    | 36%   |
| P4 front       | 57       | 27                      | 23%       | 4.17    | 7%    | 44                       | 11%       | 5.27    | 2%    |
| P5 air         | 52       | 21                      | 17%       | 3.89    | 7%    | 21                       | 19%       | 3.89    | 7%    |
| P6 front       | 66       | 17                      | 35%       | 3.17    | 16%   | 14                       | 39%       | 2.81    | 20%   |
| P7 front/tech  | 77       | 12                      | 48%       | 2.18    | 32%   | 15                       | 40%       | 3.02    | 19%   |
| P8 front       | 66       | 16                      | 45%       | 2.58    | 27%   | 17                       | 58%       | 2.59    | 34%   |
| P9 front       | 52       | 18                      | 38%       | 3.28    | 17%   | 19                       | 37%       | 3.15    | 18%   |
| P10 front/tech | 65       | 10                      | 42%       | 2.31    | 26%   | 12                       | 34%       | 2.75    | 19%   |
| P11 front      | 40       | 11                      | 42%       | 2.59    | 22%   | 12                       | 48%       | 2.62    | 25%   |
| P12 front      | 61       | 30                      | 23%       | 4.18    | 8%    | 47                       | 7%        | 5.41    | 1%    |
| P13 air        | 48       | 20                      | 21%       | 3.84    | 8%    | 21                       | 25%       | 3.68    | 10%   |
| P14 front      | 71       | 20                      | 30%       | 3.45    | 13%   | 24                       | 42%       | 3.41    | 19%   |
| P15 front/tech | 77       | 12                      | 43%       | 2.25    | 29%   | 13                       | 29%       | 3.04    | 15%   |
| P16 front      | 67       | 10                      | 45%       | 2.36    | 26%   | 16                       | 67%       | 2.14    | 45%   |

Most common opening shape:

- P1 front: `mex solar lab solar` 57%; `mex solar lab ck` 7%;
  `mex solar mex solar` 7%
- P2 front/tech: `mex solar lab solar` 33%; `mex solar mex solar` 29%;
  `mex solar lab ck` 15%
- P3 front: `mex solar lab solar` 34%; `mex solar lab ck` 25%;
  `mex solar vp solar` 9%
- P4 front: `mex solar lab solar` 23%; `mex solar lab ck` 12%;
  `mex lab solar ck` 5%
- P5 air: `mex solar ap solar` 17%; `mex solar mex solar` 13%;
  `mex solar lab solar` 10%
- P6 front: `mex solar lab solar` 35%; `mex solar vp solar` 15%;
  `mex solar lab ck` 12%
- P7 front/tech: `mex solar lab solar` 48%; `mex solar mex solar` 30%;
  `mex solar lab ck` 6%
- P8 front: `mex solar lab solar` 45%; `mex solar lab ck` 26%;
  `mex solar mex solar` 6%
- P9 front: `mex solar lab solar` 38%; `mex solar lab ck` 10%;
  `mex solar lab ak` 10%
- P10 front/tech: `mex solar mex solar` 42%; `mex solar lab solar` 28%;
  `mex solar lab ck` 12%
- P11 front: `mex solar lab solar` 42%; `mex solar lab ck` 18%;
  `mex solar vp solar` 15%
- P12 front: `mex solar lab solar` 23%; `mex solar lab ck` 13%;
  `mex llt mex solar` 10%
- P13 air: `mex solar ap solar` 21%; `mex solar mex solar` 15%;
  `mex solar lab solar` 8%
- P14 front: `mex solar lab solar` 30%; `mex solar lab ck` 20%;
  `mex solar vp cv` 7%
- P15 front/tech: `mex solar mex solar` 43%; `mex solar lab solar` 31%;
  `mex solar lab ck` 12%
- P16 front: `mex solar lab solar` 45%; `mex solar lab ck` 22%;
  `mex solar mex solar` 12%

Most common first 6 orders:

- P1 front: `mex mex mex solar solar lab` 48%; `mex mex mex solar solar solar`
  12%; `mex mex mex lab solar solar` 5%
- P2 front/tech: `mex mex mex solar solar lab` 31%;
  `mex mex mex solar mex solar` 22%; `mex mex mex mex solar solar` 9%
- P3 front: `mex mex mex solar solar lab` 57%; `mex mex mex solar solar vp`
  16%; `mex mex mex solar solar solar` 14%
- P4 front: `mex mex solar solar lab solar` 11%;
  `mex mex solar lab solar solar` 5%; `mex lht mex solar solar solar` 4%
- P5 air: `mex mex mex solar solar ap` 19%; `mex mex mex solar solar lab` 13%;
  `mex mex mex solar solar solar` 10%
- P6 front: `mex mex mex solar solar lab` 39%; `mex mex mex solar solar vp`
  18%; `mex mex mex solar solar solar` 12%
- P7 front/tech: `mex mex mex solar solar lab` 40%;
  `mex mex mex solar mex solar` 13%; `mex mex mex solar mex mex` 12%
- P8 front: `mex mex mex solar solar lab` 58%; `mex mex mex solar mex solar`
  6%; `mex mex mex solar solar solar` 6%
- P9 front: `mex mex mex solar solar lab` 37%; `mex mex mex solar solar solar`
  23%; `mex mex mex mex solar lab` 6%
- P10 front/tech: `mex mex mex solar mex solar` 34%;
  `mex mex mex solar solar lab` 25%; `mex mex mex mex solar solar` 12%
- P11 front: `mex mex mex solar solar lab` 48%;
  `mex mex mex solar solar solar` 12%; `mex mex mex solar solar vp` 12%
- P12 front: `mex mex solar solar lab ck` 7%; `mex mex solar solar lab solar`
  5%; `mex mex solar lab solar solar` 5%
- P13 air: `mex mex mex solar solar solar` 25%; `mex mex mex solar solar ap`
  17%; `mex mex mex mex solar solar` 10%
- P14 front: `mex mex mex solar solar lab` 42%; `mex mex mex solar solar vp`
  10%; `mex mex mex solar solar solar` 6%
- P15 front/tech: `mex mex mex solar solar lab` 29%;
  `mex mex mex solar mex mex` 22%; `mex mex mex solar mex solar` 10%
- P16 front: `mex mex mex solar solar lab` 67%; `mex mex mex solar mex solar`
  6%; `mex mex mex solar solar solar` 3%

### Consistency per position and faction, all players

| position, faction      | openings | first factory  | share | entropy | agree |
| ---------------------- | -------- | -------------- | ----- | ------- | ----- |
| P1 front, Armada       | 31       | bot lab        | 100%  | 0.00    | 100%  |
| P1 front, Cortex       | 38       | bot lab        | 95%   | 0.30    | 90%   |
| P2 front/tech, Armada  | 32       | bot lab        | 97%   | 0.20    | 94%   |
| P2 front/tech, Cortex  | 29       | bot lab        | 100%  | 0.00    | 100%  |
| P3 front, Armada       | 35       | bot lab        | 69%   | 0.90    | 56%   |
| P3 front, Cortex       | 23       | bot lab        | 74%   | 0.83    | 60%   |
| P4 front, Armada       | 36       | bot lab        | 86%   | 0.58    | 75%   |
| P4 front, Legion       | 24       | bot lab        | 88%   | 0.54    | 77%   |
| P5 air, Cortex         | 51       | aircraft plant | 80%   | 0.71    | 68%   |
| P6 front, Armada       | 32       | bot lab        | 72%   | 0.86    | 58%   |
| P6 front, Cortex       | 30       | bot lab        | 67%   | 0.92    | 54%   |
| P7 front/tech, Armada  | 38       | bot lab        | 92%   | 0.40    | 85%   |
| P7 front/tech, Cortex  | 28       | bot lab        | 100%  | 0.00    | 100%  |
| P8 front, Armada       | 21       | bot lab        | 90%   | 0.45    | 82%   |
| P8 front, Cortex       | 36       | bot lab        | 97%   | 0.18    | 94%   |
| P9 front, Armada       | 35       | bot lab        | 94%   | 0.32    | 89%   |
| P9 front, Cortex       | 33       | bot lab        | 100%  | 0.00    | 100%  |
| P10 front/tech, Armada | 35       | bot lab        | 91%   | 0.42    | 84%   |
| P10 front/tech, Cortex | 30       | bot lab        | 97%   | 0.21    | 93%   |
| P11 front, Armada      | 33       | bot lab        | 82%   | 0.68    | 69%   |
| P11 front, Cortex      | 25       | bot lab        | 76%   | 0.80    | 62%   |
| P12 front, Armada      | 25       | bot lab        | 76%   | 0.95    | 60%   |
| P12 front, Cortex      | 32       | bot lab        | 97%   | 0.20    | 94%   |
| P12 front, Legion      | 21       | bot lab        | 81%   | 0.70    | 68%   |
| P13 air, Cortex        | 53       | aircraft plant | 89%   | 0.51    | 80%   |
| P14 front, Armada      | 32       | bot lab        | 81%   | 0.70    | 69%   |
| P14 front, Cortex      | 22       | bot lab        | 91%   | 0.44    | 83%   |
| P15 front/tech, Armada | 31       | bot lab        | 100%  | 0.00    | 100%  |
| P15 front/tech, Cortex | 31       | bot lab        | 97%   | 0.21    | 94%   |
| P16 front, Armada      | 21       | bot lab        | 100%  | 0.00    | 100%  |
| P16 front, Cortex      | 34       | bot lab        | 100%  | 0.00    | 100%  |

| position, faction      | openings | opening shape: distinct | top share | entropy | agree | first 6 orders: distinct | top share | entropy | agree |
| ---------------------- | -------- | ----------------------- | --------- | ------- | ----- | ------------------------ | --------- | ------- | ----- |
| P1 front, Armada       | 31       | 10                      | 39%       | 2.73    | 18%   | 11                       | 45%       | 2.54    | 24%   |
| P1 front, Cortex       | 38       | 14                      | 45%       | 2.88    | 21%   | 20                       | 42%       | 3.39    | 18%   |
| P2 front/tech, Armada  | 32       | 8                       | 34%       | 2.37    | 22%   | 10                       | 38%       | 2.77    | 18%   |
| P2 front/tech, Cortex  | 29       | 9                       | 31%       | 2.66    | 17%   | 11                       | 45%       | 2.60    | 23%   |
| P3 front, Armada       | 35       | 9                       | 26%       | 2.74    | 15%   | 5                        | 66%       | 1.46    | 47%   |
| P3 front, Cortex       | 23       | 8                       | 35%       | 2.51    | 19%   | 7                        | 48%       | 2.16    | 27%   |
| P4 front, Armada       | 36       | 18                      | 28%       | 3.65    | 10%   | 27                       | 11%       | 4.56    | 2%    |
| P4 front, Legion       | 24       | 15                      | 12%       | 3.71    | 5%    | 21                       | 8%        | 4.33    | 1%    |
| P5 air, Cortex         | 51       | 20                      | 24%       | 3.81    | 8%    | 15                       | 25%       | 3.22    | 13%   |
| P6 front, Armada       | 32       | 11                      | 31%       | 3.03    | 13%   | 11                       | 34%       | 2.89    | 16%   |
| P6 front, Cortex       | 30       | 10                      | 37%       | 2.81    | 17%   | 8                        | 43%       | 2.36    | 24%   |
| P7 front/tech, Armada  | 38       | 6                       | 39%       | 1.94    | 29%   | 10                       | 37%       | 2.75    | 18%   |
| P7 front/tech, Cortex  | 28       | 3                       | 68%       | 1.07    | 53%   | 6                        | 61%       | 1.77    | 39%   |
| P8 front, Armada       | 21       | 10                      | 43%       | 2.71    | 19%   | 8                        | 57%       | 2.15    | 32%   |
| P8 front, Cortex       | 36       | 5                       | 50%       | 1.55    | 39%   | 8                        | 75%       | 1.49    | 56%   |
| P9 front, Armada       | 35       | 16                      | 26%       | 3.47    | 10%   | 18                       | 40%       | 3.27    | 17%   |
| P9 front, Cortex       | 33       | 7                       | 45%       | 2.24    | 25%   | 15                       | 39%       | 3.06    | 18%   |
| P10 front/tech, Armada | 35       | 10                      | 34%       | 2.56    | 21%   | 13                       | 34%       | 2.86    | 18%   |
| P10 front/tech, Cortex | 30       | 6                       | 37%       | 2.23    | 22%   | 8                        | 30%       | 2.51    | 19%   |
| P11 front, Armada      | 33       | 12                      | 36%       | 2.86    | 18%   | 11                       | 55%       | 2.41    | 30%   |
| P11 front, Cortex      | 25       | 8                       | 48%       | 2.36    | 25%   | 7                        | 48%       | 2.11    | 28%   |
| P12 front, Armada      | 25       | 13                      | 32%       | 3.14    | 13%   | 22                       | 8%        | 4.40    | 1%    |
| P12 front, Cortex      | 32       | 13                      | 22%       | 3.26    | 10%   | 25                       | 9%        | 4.54    | 2%    |
| P12 front, Legion      | 21       | 16                      | 14%       | 3.84    | 3%    | 20                       | 10%       | 4.30    | 0%    |
| P13 air, Cortex        | 53       | 20                      | 25%       | 3.69    | 10%   | 18                       | 28%       | 3.25    | 15%   |
| P14 front, Armada      | 32       | 13                      | 28%       | 3.19    | 12%   | 10                       | 56%       | 2.26    | 33%   |
| P14 front, Cortex      | 22       | 6                       | 55%       | 1.92    | 32%   | 9                        | 55%       | 2.32    | 29%   |
| P15 front/tech, Armada | 31       | 6                       | 52%       | 1.75    | 36%   | 8                        | 29%       | 2.63    | 17%   |
| P15 front/tech, Cortex | 31       | 5                       | 35%       | 1.97    | 26%   | 7                        | 52%       | 2.10    | 30%   |
| P16 front, Armada      | 21       | 5                       | 52%       | 1.88    | 31%   | 4                        | 76%       | 1.15    | 58%   |
| P16 front, Cortex      | 34       | 6                       | 41%       | 2.06    | 27%   | 6                        | 68%       | 1.59    | 47%   |

Left out (fewer than 20 openings): P1 front, Legion 8, P2 front/tech, Legion
15, P3 front, Legion 14, P4 front, Cortex 17, P5 air, Armada 9, P5 air, Legion
18, P6 front, Legion 5, P7 front/tech, Legion 12, P8 front, Legion 13, P9
front, Legion 9, P10 front/tech, Legion 12, P11 front, Legion 16, P13 air,
Armada 4, P13 air, Legion 19, P14 front, Legion 15, P15 front/tech, Legion 15,
P16 front, Legion 11

### What sets each position apart

Kinds of unit ordered in the first 8 minutes by a larger share of the
position's players than of everyone else's: share here (share elsewhere),
median time of the first such order.

- P1 front: `rad` 96% (57%) at 2:50; `llt` 88% (55%) at 2:45; `rock` 36% (16%)
  at 2:12; `geo` 75% (56%) at 4:12; `ak` 48% (29%) at 1:04
- P2 front/tech: `ack` 91% (19%) at 5:18; `alab` 92% (22%) at 4:27; `ageo` 75%
  (25%) at 6:05; `moho` 94% (44%) at 6:11; `geo` 96% (54%) at 1:47
- P3 front: `rad` 85% (58%) at 3:00; `llt` 79% (56%) at 2:05; `vp` 36% (14%)
  at 0:35; `advsol` 56% (42%) at 5:07; `flea` 32% (25%) at 0:48
- P4 front: `rad` 91% (58%) at 2:28; `advsol` 73% (41%) at 4:23; `rock` 34%
  (16%) at 3:03; `flea` 34% (25%) at 1:23; `ck` 88% (81%) at 1:25
- P5 air: `ap` 100% (10%) at 0:42; `ca` 77% (6%) at 1:20; `veng` 65% (5%) at
  1:51; `valk` 64% (5%) at 4:26; `bw` 58% (4%) at 2:26
- P6 front: `vp` 52% (13%) at 0:38; `llt` 90% (55%) at 2:57; `advsol` 70%
  (41%) at 4:56; `rad` 85% (58%) at 3:23; `cv` 34% (9%) at 0:58
- P7 front/tech: `ack` 89% (19%) at 5:02; `alab` 90% (22%) at 4:13; `ageo` 89%
  (24%) at 5:44; `moho` 97% (44%) at 5:47; `geo` 100% (54%) at 1:35
- P8 front: `rad` 99% (57%) at 2:37; `geo` 91% (55%) at 3:34; `llt` 81% (56%)
  at 1:44; `drag` 38% (17%) at 4:34; `storm` 36% (16%) at 2:01
- P9 front: `rad` 90% (57%) at 3:02; `drag` 48% (17%) at 3:53; `llt` 85% (55%)
  at 2:39; `thud` 34% (14%) at 2:30; `pw` 40% (20%) at 1:40
- P10 front/tech: `ack` 89% (19%) at 5:23; `alab` 91% (22%) at 4:15; `moho`
  94% (44%) at 6:09; `ageo` 68% (25%) at 6:25; `geo` 96% (54%) at 1:46
- P11 front: `rad` 85% (58%) at 2:52; `llt` 77% (56%) at 2:19; `vp` 31% (15%)
  at 0:25; `rock` 32% (16%) at 1:26; `pw` 32% (21%) at 1:04
- P12 front: `rad` 89% (58%) at 2:42; `advsol` 66% (41%) at 4:07; `thud` 34%
  (14%) at 2:32; `llt` 70% (56%) at 2:23; `necro` 35% (29%) at 1:38
- P13 air: `ap` 100% (10%) at 0:32; `ca` 86% (6%) at 1:26; `veng` 69% (5%) at
  1:25; `valk` 68% (5%) at 4:27; `bw` 60% (4%) at 2:19
- P14 front: `rad` 92% (57%) at 3:44; `llt` 77% (56%) at 2:57; `advsol` 60%
  (42%) at 5:44; `pw` 36% (20%) at 1:41; `flea` 33% (25%) at 0:57
- P15 front/tech: `ack` 86% (19%) at 5:13; `alab` 88% (22%) at 4:13; `ageo`
  88% (24%) at 5:49; `moho` 99% (44%) at 5:54; `geo` 99% (54%) at 1:43
- P16 front: `geo` 99% (54%) at 3:19; `rad` 96% (57%) at 2:49; `storm` 43%
  (15%) at 3:08; `llt` 81% (56%) at 2:08; `ak` 52% (28%) at 0:55

### Factions per position

| position       | openings | Armada | Cortex | Legion | other |
| -------------- | -------- | ------ | ------ | ------ | ----- |
| P1 front       | 80       | 39%    | 48%    | 10%    | 4%    |
| P2 front/tech  | 79       | 41%    | 37%    | 19%    | 4%    |
| P3 front       | 78       | 45%    | 29%    | 18%    | 8%    |
| P4 front       | 77       | 47%    | 22%    | 31%    | 0%    |
| P5 air         | 81       | 11%    | 63%    | 22%    | 4%    |
| P6 front       | 73       | 44%    | 41%    | 7%     | 8%    |
| P7 front/tech  | 79       | 48%    | 35%    | 15%    | 1%    |
| P8 front       | 78       | 27%    | 46%    | 17%    | 10%   |
| P9 front       | 82       | 43%    | 40%    | 11%    | 6%    |
| P10 front/tech | 79       | 44%    | 38%    | 15%    | 3%    |
| P11 front      | 78       | 42%    | 32%    | 21%    | 5%    |
| P12 front      | 82       | 30%    | 39%    | 26%    | 5%    |
| P13 air        | 78       | 5%     | 68%    | 24%    | 3%    |
| P14 front      | 78       | 41%    | 28%    | 19%    | 12%   |
| P15 front/tech | 80       | 39%    | 39%    | 19%    | 4%    |
| P16 front      | 77       | 27%    | 44%    | 14%    | 14%   |
| all            | 1259     | 36%    | 41%    | 18%    | 6%    |

### First factory per position and faction

| position, faction      | openings | bot lab | aircraft plant | vehicle plant |
| ---------------------- | -------- | ------- | -------------- | ------------- |
| P1 front, Armada       | 31       | 100%    | 0%             | 0%            |
| P1 front, Cortex       | 38       | 95%     | 0%             | 5%            |
| P2 front/tech, Armada  | 32       | 97%     | 0%             | 3%            |
| P2 front/tech, Cortex  | 29       | 100%    | 0%             | 0%            |
| P3 front, Armada       | 35       | 69%     | 0%             | 31%           |
| P3 front, Cortex       | 23       | 74%     | 0%             | 26%           |
| P4 front, Armada       | 36       | 86%     | 0%             | 14%           |
| P4 front, Legion       | 24       | 88%     | 0%             | 12%           |
| P5 air, Cortex         | 51       | 20%     | 80%            | 0%            |
| P6 front, Armada       | 32       | 72%     | 0%             | 28%           |
| P6 front, Cortex       | 30       | 67%     | 0%             | 33%           |
| P7 front/tech, Armada  | 38       | 92%     | 0%             | 8%            |
| P7 front/tech, Cortex  | 28       | 100%    | 0%             | 0%            |
| P8 front, Armada       | 21       | 90%     | 0%             | 10%           |
| P8 front, Cortex       | 36       | 97%     | 0%             | 3%            |
| P9 front, Armada       | 35       | 94%     | 0%             | 6%            |
| P9 front, Cortex       | 33       | 100%    | 0%             | 0%            |
| P10 front/tech, Armada | 35       | 91%     | 0%             | 9%            |
| P10 front/tech, Cortex | 30       | 97%     | 0%             | 3%            |
| P11 front, Armada      | 33       | 82%     | 0%             | 18%           |
| P11 front, Cortex      | 25       | 76%     | 0%             | 24%           |
| P12 front, Armada      | 25       | 76%     | 4%             | 20%           |
| P12 front, Cortex      | 32       | 97%     | 0%             | 3%            |
| P12 front, Legion      | 21       | 81%     | 0%             | 19%           |
| P13 air, Cortex        | 53       | 11%     | 89%            | 0%            |
| P14 front, Armada      | 32       | 81%     | 0%             | 19%           |
| P14 front, Cortex      | 22       | 91%     | 0%             | 9%            |
| P15 front/tech, Armada | 31       | 100%    | 0%             | 0%            |
| P15 front/tech, Cortex | 31       | 97%     | 3%             | 0%            |
| P16 front, Armada      | 21       | 100%    | 0%             | 0%            |
| P16 front, Cortex      | 34       | 100%    | 0%             | 0%            |

### Next-unit accuracy, first 30 orders, held-out games

| position       | orders | faction only | faction and role | faction and position |
| -------------- | ------ | ------------ | ---------------- | -------------------- |
| P1 front       | 2400   | 0.524        | 0.532            | 0.517                |
| P2 front/tech  | 2370   | 0.575        | 0.568            | 0.553                |
| P3 front       | 2340   | 0.519        | 0.518            | 0.489                |
| P4 front       | 2310   | 0.519        | 0.525            | 0.509                |
| P5 air         | 2430   | 0.506        | 0.512            | 0.501                |
| P6 front       | 2190   | 0.557        | 0.557            | 0.523                |
| P7 front/tech  | 2370   | 0.563        | 0.563            | 0.550                |
| P8 front       | 2340   | 0.584        | 0.593            | 0.560                |
| P9 front       | 2460   | 0.524        | 0.527            | 0.491                |
| P10 front/tech | 2370   | 0.569        | 0.553            | 0.553                |
| P11 front      | 2340   | 0.560        | 0.562            | 0.536                |
| P12 front      | 2460   | 0.513        | 0.510            | 0.497                |
| P13 air        | 2340   | 0.515        | 0.518            | 0.505                |
| P14 front      | 2340   | 0.528        | 0.527            | 0.504                |
| P15 front/tech | 2400   | 0.570        | 0.562            | 0.564                |
| P16 front      | 2310   | 0.570        | 0.579            | 0.554                |
| all            | 37770  | 0.543        | 0.544            | 0.525                |

### Recognising the position from the orders

| minutes | kinds of unit (median) | position right | role right |
| ------- | ---------------------- | -------------- | ---------- |
| 1       | 4                      | 0.198          | 0.770      |
| 2       | 7                      | 0.207          | 0.895      |
| 4       | 10                     | 0.252          | 0.959      |
| 8       | 15                     | 0.272          | 0.979      |

Guessing: 0.062 for the position, 0.622 for the role (always the commonest).

#### Per position after 8 minutes

| position       | role       | openings | recognised | guessed as                                               |
| -------------- | ---------- | -------- | ---------- | -------------------------------------------------------- |
| P1 front       | front      | 80       | 48%        | P1 front 48%, P9 front 20%, P8 front 14%                 |
| P2 front/tech  | front/tech | 79       | 32%        | P2 front/tech 32%, P10 front/tech 30%, P7 front/tech 23% |
| P3 front       | front      | 78       | 1%         | P6 front 28%, P1 front 28%, P4 front 18%                 |
| P4 front       | front      | 77       | 31%        | P4 front 31%, P1 front 29%, P12 front 10%                |
| P5 air         | air        | 81       | 38%        | P13 air 62%, P5 air 38%                                  |
| P6 front       | front      | 73       | 41%        | P6 front 41%, P1 front 18%, P16 front 10%                |
| P7 front/tech  | front/tech | 79       | 37%        | P7 front/tech 37%, P2 front/tech 25%, P10 front/tech 20% |
| P8 front       | front      | 78       | 22%        | P16 front 36%, P8 front 22%, P1 front 21%                |
| P9 front       | front      | 82       | 20%        | P1 front 45%, P8 front 20%, P9 front 20%                 |
| P10 front/tech | front/tech | 79       | 22%        | P2 front/tech 37%, P7 front/tech 28%, P10 front/tech 22% |
| P11 front      | front      | 78       | 4%         | P1 front 26%, P6 front 21%, P9 front 15%                 |
| P12 front      | front      | 82       | 18%        | P4 front 26%, P1 front 21%, P12 front 18%                |
| P13 air        | air        | 78       | 65%        | P13 air 65%, P5 air 33%, P15 front/tech 1%               |
| P14 front      | front      | 78       | 8%         | P4 front 21%, P6 front 19%, P12 front 15%                |
| P15 front/tech | front/tech | 80       | 20%        | P7 front/tech 34%, P2 front/tech 28%, P15 front/tech 20% |
| P16 front      | front      | 77       | 31%        | P16 front 31%, P8 front 25%, P1 front 17%                |

### Openings that do not fit their position, after 8 minutes

An opening is flagged when the classifier gives the player's own position (or
role: all positions with that role together) less than 0.05.

| own      | flagged             | mu < 30           | mu >= 30           | planted, flagged     |
| -------- | ------------------- | ----------------- | ------------------ | -------------------- |
| position | 313 of 1259 (24.9%) | 94 of 319 (29.5%) | 219 of 940 (23.3%) | 1069 of 1259 (84.9%) |
| role     | 18 of 1259 (1.4%)   | 7 of 319 (2.2%)   | 11 of 940 (1.2%)   | 1225 of 1259 (97.3%) |

Flagged by position:

| position       | openings | flagged | share | of those, another first factory |
| -------------- | -------- | ------- | ----- | ------------------------------- |
| P1 front       | 80       | 12      | 15%   | 1                               |
| P2 front/tech  | 79       | 11      | 14%   | 1                               |
| P3 front       | 78       | 46      | 59%   | 4                               |
| P4 front       | 77       | 28      | 36%   | 8                               |
| P5 air         | 81       | 1       | 1%    | 1                               |
| P6 front       | 73       | 26      | 36%   | 3                               |
| P7 front/tech  | 79       | 8       | 10%   | 0                               |
| P8 front       | 78       | 15      | 19%   | 3                               |
| P9 front       | 82       | 10      | 12%   | 2                               |
| P10 front/tech | 79       | 10      | 13%   | 4                               |
| P11 front      | 78       | 37      | 47%   | 11                              |
| P12 front      | 82       | 37      | 45%   | 7                               |
| P13 air        | 78       | 5       | 6%    | 3                               |
| P14 front      | 78       | 37      | 47%   | 11                              |
| P15 front/tech | 80       | 13      | 16%   | 2                               |
| P16 front      | 77       | 17      | 22%   | 0                               |

## What drives the meta

- **Weak wind makes solar the opener.** With wind from 0 to 10 the most common
  start at 12 of the 16 positions is `mex mex mex solar solar` and then the
  factory (23 to 68% of openings).
- **The ends of the line play bots, the inner positions sometimes vehicles.**
  `P1`, `P8`, `P9` and `P16` order a bot lab first in 96 to 100% of openings,
  `P3`, `P6`, `P11` and `P14` in 68 to 82%.
- **The rich metal spot unsettles the middle.** `P4` and `P12` are told to
  walk their commander to the 10.1 spot. Two of their players agree on the
  first six orders in 1 to 2% of pairs, against 16 to 46% at the other front
  positions.
- **Vents make the tech positions.** Geothermal plants are ordered by 96 to
  100% of the players of `P2`, `P7`, `P10` and `P15` before two minutes, then
  an advanced bot lab. Half of everyone else orders one too, later.
- **Four tech positions, one meta.** For an opening of one of them the
  classifier names one of the four in 82 to 87% of cases, and the right one in
  20 to 37%.
- **Legion is played here.** 18% of the openings are Legion, against 2 to 3%
  on the other maps, and 22 to 24% at the air positions. Armada hardly ever
  plays air (11% and 5%).
