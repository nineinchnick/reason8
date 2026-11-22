# All That Glitters v2.2.3

The second most played map of the slice: a dry desert, two teams of 8 on the
short edges, six front players each. Its meta is the simplest of the three
maps: front, tech and air. Method, sample and the terms used in the tables are
in [`README.md`](README.md).

## The map

From the map file (`mapinfo.lua`, height and metal maps) and the
[official map page](https://www.beyondallreason.info/map/all-that-glitters):

size
: 12 × 20, that is 6,144 × 10,240 map units; by Nikuksis; 16 players

layout
: a half turn for the start positions, less so for the metal: only 84 of the
  152 metal spots have their image within 100 units

water
: none; tidal strength 0

wind
: 0 to 16

metal
: 152 spots; 4 to 9 within 1,000 units of where each position starts

geothermal vents
: 2, one per side, 1,300 units in front of `P5` and `P13`

height
: hills between the bases narrow the ways across; the official page lists
  "chokepoints" among the terrain

reclaim
: the map file places 158 rocks

## Positions

The map metadata recommends eight start positions per side for 8v8, sixteen
positions in all: `P1` to `P8` for the north side and `P9` to `P16` for the
south side. The two sides list the same roles in the same order, so the
positions come in pairs that are each other's image on the map; they are
described together here but measured apart. Percentages are given for the
first and the second position of a pair. What each position orders is in
[What sets each position apart](#what-sets-each-position-apart); how far
players start from the recommended point is in
[Starts and recommended positions](#starts-and-recommended-positions).

`P1` and `P9`, front
: *Where:* back row, in the corner behind `P5` and `P13`
: *Opens with:* a bot lab (70% and 61%) or a vehicle plant

`P2` and `P10`, air
: *Where:* back row
: *Community name:* air spot
: *Opens with:* an aircraft plant (94% and 93%)

`P3` and `P11`, tech
: *Where:* back row
: *Community name:* tech spot, eco spot
: *Opens with:* a bot lab (93% and 89%) and an advanced bot lab around four
  minutes (87% and 86%)

`P4` and `P12`, front
: *Where:* back row, in the corner behind `P8` and `P16`
: *Opens with:* a bot lab (52% and 53%) or a vehicle plant: the most vehicles
  of the map

`P5` and `P13`, front
: *Where:* front row, nearest to the side's geothermal vent
: *Opens with:* a bot lab (82% and 72%) or a vehicle plant; 67% and 66% order
  a geothermal plant soon after three minutes, against 5% of everyone else

`P6` and `P14`, front
: *Where:* front row, next to `P5` and `P13`
: *Opens with:* a bot lab (72% and 61%) or a vehicle plant

`P7` and `P15`, front
: *Where:* front row, between the two above and the far end
: *Opens with:* a bot lab (79% and 73%) or a vehicle plant

`P8` and `P16`, front
: *Where:* front row, at the far end from the vent
: *Opens with:* a bot lab (74% and 73%) or a vehicle plant

**Community names are labels here, not keys.** For the twelve positions with
the role front we found none we could place: "canyon", "anti-canyon" and
"rainbow lane" (the front line beside the canyon) come from MasterBel2's
guide, "mid-front" and "front right" from video titles. They are lanes of the
front; no source we read ties them to start positions.

## Sources

[maps-metadata `map_list.yaml`](https://github.com/beyond-all-reason/maps-metadata/blob/main/map_list.yaml)
: *What:* BAR's own map list, the source of the positions: 16 recommended
  start positions for this map with a role each (per side: 6 front, 1 tech, 1
  air), and the default start boxes.
: *Read:* the file itself at the pinned commit; the same positions are in the
  `mapmetadata_startpos` lobby option of 82 of our 84 replays

[Official map page](https://www.beyondallreason.info/map/all-that-glitters)
: *What:* size, wind 0 to 16, tidal 0, terrain "desert, chokepoints, flat,
  hills"
: *Read:* the page; size, wind and tidal checked against the map file

[MasterBel2, "The Best Units to Pick for All That Glitters 8v8 Front Line, and How To Use Them"](https://masterbel2.wordpress.com/the-best-units-to-pick-for-all-that-glitters-8v8-front-line-and-how-to-use-them/)
: *What:* the only written guide we found. Six commanders close the front
  line; whatever the factory, start with about five light scouts; the
  commander leaves the base around 2:00 and reaches the front around 4:00;
  tech can send second-tier units from 5:00, more often from 7:00. Names the
  lanes canyon, anti-canyon and rainbow lane. Does not say bots or vehicles
  per lane.
: *Read:* the page, through a summarising tool, so we paraphrase

[Drongo, "How To Actually Tech on All That Glitters (Guide)"](https://www.youtube.com/watch?v=81QISY1OxMk)
: *What:* a video guide for the tech position
: *Read:* title only; nobody watched it

[BetterStrategy, "The High Ground is Strong | 8v8 All That Glitters | Canyon | Beyond All Reason"](https://www.youtube.com/watch?v=MtTGtUsjqro)
: *What:* a game from the canyon position; the same channel titles games
  "Mid-Front", "Front Right (Rainbow Lane)", "Air Spot", "Tech Spot" and "Eco
  Spot"
: *Read:* title only

## Start setup

| games with                      | games | openings | on a spot |
| ------------------------------- | ----- | -------- | --------- |
| recommended positions shown     | 82    | 1312     | 98.7%     |
| recommended positions not shown | 2     | 32       | 93.8%     |
| default start boxes             | 84    | 1344     | 98.6%     |
| changed start boxes             | 0     | 0        | -         |
| start boxes not comparable      | 0     | 0        | -         |

- **Positions shown.** 82 of the 84 games showed the recommended positions. In
  the 2 that did not, 30 of 32 players still started on them.
- **Start boxes.** All 84 games used the map's default boxes, the top and the
  bottom fifth of the map: 32 by their own lobby option, 52 older ones by the
  pinned map list. Which team gets which edge changes from game to game.

### Starts and recommended positions

From `python -m reason8.positions`, on all 84 games: the starts nearest to
each position, how many are "on the spot" (nearer than half the way to the
next recommended position), and their distance from the recommended point in
map units.

| position | role  | nearest starts | on the spot | median | 90% within |
| -------- | ----- | -------------- | ----------- | ------ | ---------- |
| P1       | front | 82             | 100.0%      | 21     | 37         |
| P2       | air   | 87             | 98.9%       | 358    | 492        |
| P3       | tech  | 82             | 100.0%      | 34     | 429        |
| P4       | front | 85             | 100.0%      | 14     | 74         |
| P5       | front | 87             | 95.4%       | 37     | 63         |
| P6       | front | 81             | 96.3%       | 29     | 55         |
| P7       | front | 83             | 97.6%       | 12     | 31         |
| P8       | front | 85             | 98.8%       | 14     | 36         |
| P9       | front | 84             | 98.8%       | 29     | 66         |
| P10      | air   | 81             | 100.0%      | 67     | 250        |
| P11      | tech  | 83             | 100.0%      | 184    | 408        |
| P12      | front | 83             | 100.0%      | 39     | 89         |
| P13      | front | 86             | 96.5%       | 28     | 67         |
| P14      | front | 85             | 97.6%       | 22     | 53         |
| P15      | front | 88             | 97.7%       | 19     | 44         |
| P16      | front | 82             | 100.0%      | 30     | 48         |

## The two sides

The spawn points of the two sides are different positions. Whether the two
sides nevertheless open alike is checked here: each opening is given its place
in its side's list (`P1` and `P9` are both first), and the first side is
compared with the second by the total variation distance of a feature per
place, next to the same distance after shuffling whole teams between the sides
1,000 times.

First side against second side, 84 teams against 84:

| feature                 | distance | shuffled mean | shuffled 95% | p     |
| ----------------------- | -------- | ------------- | ------------ | ----- |
| first factory per place | 0.057    | 0.058         | 0.081        | 0.502 |
| opening shape per place | 0.363    | 0.360         | 0.386        | 0.410 |
| faction per place       | 0.076    | 0.080         | 0.106        | 0.586 |

Share of the most common first factory at the same place of the two lists:

| first side | second side | first factory  | first side | second side |
| ---------- | ----------- | -------------- | ---------- | ----------- |
| P1 front   | P9 front    | bot lab        | 70% of 82  | 61% of 83   |
| P2 air     | P10 air     | aircraft plant | 94% of 86  | 93% of 81   |
| P3 tech    | P11 tech    | bot lab        | 93% of 82  | 89% of 83   |
| P4 front   | P12 front   | bot lab        | 52% of 85  | 53% of 83   |
| P5 front   | P13 front   | bot lab        | 82% of 83  | 72% of 83   |
| P6 front   | P14 front   | bot lab        | 72% of 78  | 61% of 83   |
| P7 front   | P15 front   | bot lab        | 79% of 81  | 73% of 86   |
| P8 front   | P16 front   | bot lab        | 74% of 84  | 73% of 82   |

No distance stands clear of its shuffled values: the two sides open alike. The
gaps of about ten points in the table below (`P1`, `P5`, `P6` and their
counterparts) are what 80 openings per position leave open.

## Measurements

84 games, 1344 openings, 1325 of 1344 (98.6%) on a spot, 335 of those by
players with mu >= 30.

141 of 168 (83.9%) teams fill all 8 spots; 11 teams have two players on one
spot.

### Consistency per position, all players

| position  | openings | first factory  | share | entropy | agree |
| --------- | -------- | -------------- | ----- | ------- | ----- |
| P1 front  | 82       | bot lab        | 70%   | 0.89    | 57%   |
| P2 air    | 86       | aircraft plant | 94%   | 0.38    | 89%   |
| P3 tech   | 82       | bot lab        | 93%   | 0.43    | 86%   |
| P4 front  | 85       | bot lab        | 52%   | 1.08    | 48%   |
| P5 front  | 83       | bot lab        | 82%   | 0.68    | 70%   |
| P6 front  | 78       | bot lab        | 72%   | 0.86    | 59%   |
| P7 front  | 81       | bot lab        | 79%   | 0.74    | 66%   |
| P8 front  | 84       | bot lab        | 74%   | 0.83    | 61%   |
| P9 front  | 83       | bot lab        | 61%   | 0.96    | 52%   |
| P10 air   | 81       | aircraft plant | 93%   | 0.43    | 86%   |
| P11 tech  | 83       | bot lab        | 89%   | 0.55    | 80%   |
| P12 front | 83       | bot lab        | 53%   | 1.08    | 48%   |
| P13 front | 83       | bot lab        | 72%   | 0.99    | 58%   |
| P14 front | 83       | bot lab        | 61%   | 0.96    | 52%   |
| P15 front | 86       | bot lab        | 73%   | 0.91    | 60%   |
| P16 front | 82       | bot lab        | 73%   | 0.84    | 60%   |

| position  | openings | opening shape: distinct | top share | entropy | agree | first 6 orders: distinct | top share | entropy | agree |
| --------- | -------- | ----------------------- | --------- | ------- | ----- | ------------------------ | --------- | ------- | ----- |
| P1 front  | 82       | 35                      | 13%       | 4.59    | 5%    | 32                       | 23%       | 4.16    | 9%    |
| P2 air    | 86       | 31                      | 13%       | 4.48    | 5%    | 34                       | 19%       | 4.46    | 6%    |
| P3 tech   | 82       | 29                      | 13%       | 4.26    | 6%    | 35                       | 17%       | 4.45    | 6%    |
| P4 front  | 85       | 29                      | 12%       | 4.46    | 5%    | 31                       | 18%       | 3.97    | 9%    |
| P5 front  | 83       | 35                      | 16%       | 4.53    | 5%    | 29                       | 35%       | 3.58    | 16%   |
| P6 front  | 78       | 27                      | 19%       | 3.93    | 9%    | 23                       | 36%       | 3.33    | 17%   |
| P7 front  | 81       | 22                      | 28%       | 3.65    | 11%   | 17                       | 32%       | 2.95    | 20%   |
| P8 front  | 84       | 24                      | 20%       | 3.82    | 9%    | 26                       | 31%       | 3.72    | 12%   |
| P9 front  | 83       | 34                      | 12%       | 4.63    | 4%    | 30                       | 20%       | 4.00    | 9%    |
| P10 air   | 81       | 33                      | 15%       | 4.62    | 4%    | 32                       | 19%       | 4.18    | 8%    |
| P11 tech  | 83       | 26                      | 20%       | 4.05    | 8%    | 31                       | 14%       | 4.25    | 7%    |
| P12 front | 83       | 31                      | 11%       | 4.46    | 5%    | 33                       | 20%       | 4.18    | 8%    |
| P13 front | 83       | 38                      | 13%       | 4.70    | 4%    | 33                       | 25%       | 3.92    | 12%   |
| P14 front | 83       | 30                      | 14%       | 4.39    | 5%    | 29                       | 25%       | 3.80    | 11%   |
| P15 front | 86       | 27                      | 17%       | 4.06    | 8%    | 28                       | 37%       | 3.46    | 17%   |
| P16 front | 82       | 26                      | 16%       | 4.15    | 7%    | 22                       | 27%       | 3.44    | 13%   |

Most common opening shape:

- P1 front: `mex solar lab win` 13%; `mex win mex win` 12%; `mex solar win vp`
  7%
- P2 air: `mex solar win ap` 13%; `mex solar mex solar` 9%; `mex solar ap win`
  8%
- P3 tech: `mex solar win lab` 13%; `mex solar lab win` 12%;
  `mex solar mex solar` 10%
- P4 front: `mex solar lab win` 12%; `mex solar win vp` 9%; `mex solar vp win`
  9%
- P5 front: `mex solar lab solar` 16%; `mex solar lab win` 11%;
  `mex solar win lab` 10%
- P6 front: `mex solar lab win` 19%; `mex solar win lab` 18%;
  `mex solar lab solar` 13%
- P7 front: `mex solar win lab` 28%; `mex solar lab solar` 12%;
  `mex solar lab win` 10%
- P8 front: `mex solar lab solar` 20%; `mex solar lab win` 13%;
  `mex win mex win` 12%
- P9 front: `mex solar win lab` 12%; `mex solar lab win` 8%;
  `mex solar lab solar` 8%
- P10 air: `mex solar win ap` 15%; `mex solar win estor` 9%;
  `mex solar ap solar` 9%
- P11 tech: `mex solar win lab` 20%; `mex win mex win` 11%;
  `mex solar lab win` 8%
- P12 front: `mex solar lab solar` 11%; `mex solar vp win` 10%;
  `mex solar win vp` 8%
- P13 front: `mex solar lab solar` 13%; `mex solar win lab` 10%;
  `mex solar lab win` 7%
- P14 front: `mex solar lab win` 14%; `mex solar win lab` 13%;
  `mex solar win vp` 6%
- P15 front: `mex solar lab win` 17%; `mex solar lab solar` 14%;
  `mex solar win lab` 13%
- P16 front: `mex solar win lab` 16%; `mex solar lab win` 13%;
  `mex solar lab solar` 10%

Most common first 6 orders:

- P1 front: `mex mex mex solar solar lab` 23%; `mex mex mex win win win` 16%;
  `mex mex mex solar win win` 7%
- P2 air: `mex mex mex win win win` 19%; `mex mex mex solar solar solar` 9%;
  `mex mex mex mex solar solar` 7%
- P3 tech: `mex mex mex solar solar lab` 17%; `mex mex mex win win win` 16%;
  `mex mex mex solar solar win` 6%
- P4 front: `mex mex mex solar solar lab` 18%; `mex mex mex solar win win`
  16%; `mex mex mex solar solar vp` 14%
- P5 front: `mex mex mex solar solar lab` 35%; `mex mex mex win win win` 17%;
  `mex mex mex solar win win` 8%
- P6 front: `mex mex mex solar solar lab` 36%; `mex mex mex solar win win`
  19%; `mex mex mex solar solar vp` 8%
- P7 front: `mex mex mex solar win win` 32%; `mex mex mex solar solar lab`
  30%; `mex mex mex solar solar vp` 6%
- P8 front: `mex mex mex solar solar lab` 31%; `mex mex mex solar win win`
  12%; `mex mex mex solar solar vp` 8%
- P9 front: `mex mex mex win win win` 20%; `mex mex mex solar solar lab` 17%;
  `mex mex mex solar win win` 13%
- P10 air: `mex mex mex win win win` 19%; `mex mex mex solar win win` 16%;
  `mex mex mex solar solar ap` 11%
- P11 tech: `mex mex mex solar win win` 14%; `mex mex mex mex solar solar`
  14%; `mex mex mex win win win` 12%
- P12 front: `mex mex mex solar solar lab` 20%; `mex mex mex solar solar vp`
  14%; `mex mex mex solar win win` 11%
- P13 front: `mex mex mex solar solar lab` 25%; `mex mex mex win win win` 22%;
  `mex mex mex solar win win` 10%
- P14 front: `mex mex mex solar solar lab` 25%; `mex mex mex solar win win`
  17%; `mex mex mex win win win` 11%
- P15 front: `mex mex mex solar solar lab` 37%; `mex mex mex solar win win`
  16%; `mex mex mex win win win` 9%
- P16 front: `mex mex mex solar solar lab` 27%; `mex mex mex solar win win`
  17%; `mex mex mex win win win` 16%

### Consistency per position, mu ≥ 30

Eight of the sixteen positions have fewer than 20 openings by players with mu
≥ 30 and are left out.

| position  | openings | first factory | share | entropy | agree |
| --------- | -------- | ------------- | ----- | ------- | ----- |
| P6 front  | 21       | bot lab       | 81%   | 0.70    | 68%   |
| P7 front  | 36       | bot lab       | 81%   | 0.71    | 68%   |
| P8 front  | 40       | bot lab       | 70%   | 0.88    | 57%   |
| P11 tech  | 26       | bot lab       | 77%   | 0.93    | 62%   |
| P12 front | 23       | bot lab       | 52%   | 1.21    | 44%   |
| P14 front | 21       | bot lab       | 67%   | 0.92    | 53%   |
| P15 front | 40       | bot lab       | 78%   | 0.88    | 63%   |
| P16 front | 31       | bot lab       | 68%   | 0.91    | 55%   |

| position  | openings | opening shape: distinct | top share | entropy | agree | first 6 orders: distinct | top share | entropy | agree |
| --------- | -------- | ----------------------- | --------- | ------- | ----- | ------------------------ | --------- | ------- | ----- |
| P6 front  | 21       | 9                       | 33%       | 2.71    | 16%   | 7                        | 43%       | 2.20    | 25%   |
| P7 front  | 36       | 12                      | 42%       | 2.85    | 19%   | 9                        | 47%       | 2.21    | 29%   |
| P8 front  | 40       | 13                      | 18%       | 3.41    | 8%    | 15                       | 28%       | 3.37    | 11%   |
| P11 tech  | 26       | 11                      | 23%       | 3.12    | 10%   | 12                       | 19%       | 3.32    | 8%    |
| P12 front | 23       | 13                      | 17%       | 3.45    | 7%    | 11                       | 22%       | 3.17    | 9%    |
| P14 front | 21       | 11                      | 24%       | 3.23    | 8%    | 12                       | 29%       | 3.24    | 10%   |
| P15 front | 40       | 14                      | 20%       | 3.36    | 10%   | 12                       | 42%       | 2.62    | 23%   |
| P16 front | 31       | 14                      | 19%       | 3.54    | 7%    | 11                       | 29%       | 2.87    | 15%   |

Most common opening shape:

- P6 front: `mex solar lab win` 33%; `mex solar win lab` 24%;
  `mex solar lab solar` 10%
- P7 front: `mex solar win lab` 42%; `mex solar lab solar` 11%;
  `mex solar win vp` 11%
- P8 front: `mex solar lab solar` 18%; `mex win mex win` 15%;
  `mex solar lab win` 12%
- P11 tech: `mex solar win lab` 23%; `mex solar lab win` 19%;
  `mex win mex win` 15%
- P12 front: `mex solar vp win` 17%; `mex solar win lab` 17%;
  `mex solar win vp` 13%
- P14 front: `mex solar lab win` 24%; `mex solar win lab` 14%;
  `mex solar win vp` 10%
- P15 front: `mex solar lab win` 20%; `mex solar lab solar` 18%;
  `mex solar win vp` 12%
- P16 front: `mex solar win lab` 19%; `mex solar lab ck` 13%;
  `mex solar win vp` 10%

Most common first 6 orders:

- P6 front: `mex mex mex solar solar lab` 43%; `mex mex mex solar win win`
  29%; `mex mex mex solar solar vp` 10%
- P7 front: `mex mex mex solar win win` 47%; `mex mex mex solar solar lab`
  28%; `mex mex mex solar solar vp` 6%
- P8 front: `mex mex mex solar solar lab` 28%; `mex mex mex solar win win`
  12%; `mex mex mex solar solar vp` 12%
- P11 tech: `mex mex mex solar win win` 19%; `mex mex mex mex solar solar`
  15%; `mex mex mex win win win` 12%
- P12 front: `mex mex mex solar solar vp` 22%; `mex mex mex solar solar lab`
  17%; `mex mex mex solar win win` 13%
- P14 front: `mex mex mex solar solar lab` 29%; `mex mex mex solar win win`
  14%; `mex mex mex solar solar vp` 10%
- P15 front: `mex mex mex solar solar lab` 42%; `mex mex mex solar win win`
  22%; `mex mex mex win win win` 10%
- P16 front: `mex mex mex solar win win` 29%; `mex mex mex solar solar lab`
  23%; `mex mex mex solar solar vp` 16%

### Consistency per position and faction, all players

| position, faction | openings | first factory  | share | entropy | agree |
| ----------------- | -------- | -------------- | ----- | ------- | ----- |
| P1 front, Armada  | 43       | bot lab        | 63%   | 0.95    | 52%   |
| P1 front, Cortex  | 33       | bot lab        | 79%   | 0.75    | 66%   |
| P2 air, Armada    | 20       | aircraft plant | 80%   | 0.92    | 64%   |
| P2 air, Cortex    | 62       | aircraft plant | 98%   | 0.12    | 97%   |
| P3 tech, Armada   | 62       | bot lab        | 98%   | 0.12    | 97%   |
| P4 front, Armada  | 53       | bot lab        | 55%   | 1.11    | 48%   |
| P4 front, Cortex  | 30       | vehicle plant  | 57%   | 0.99    | 49%   |
| P5 front, Armada  | 38       | bot lab        | 79%   | 0.74    | 66%   |
| P5 front, Cortex  | 43       | bot lab        | 84%   | 0.64    | 72%   |
| P6 front, Armada  | 42       | bot lab        | 64%   | 0.94    | 53%   |
| P6 front, Cortex  | 34       | bot lab        | 85%   | 0.60    | 74%   |
| P7 front, Armada  | 39       | bot lab        | 77%   | 0.78    | 64%   |
| P7 front, Cortex  | 38       | bot lab        | 84%   | 0.63    | 73%   |
| P8 front, Armada  | 39       | bot lab        | 59%   | 0.98    | 50%   |
| P8 front, Cortex  | 42       | bot lab        | 86%   | 0.59    | 75%   |
| P9 front, Armada  | 43       | bot lab        | 65%   | 0.93    | 53%   |
| P9 front, Cortex  | 36       | bot lab        | 58%   | 0.98    | 50%   |
| P10 air, Cortex   | 67       | aircraft plant | 94%   | 0.33    | 89%   |
| P11 tech, Armada  | 66       | bot lab        | 94%   | 0.33    | 88%   |
| P12 front, Armada | 43       | vehicle plant  | 58%   | 1.11    | 48%   |
| P12 front, Cortex | 38       | bot lab        | 66%   | 0.93    | 54%   |
| P13 front, Armada | 33       | bot lab        | 70%   | 0.88    | 56%   |
| P13 front, Cortex | 44       | bot lab        | 73%   | 1.07    | 57%   |
| P14 front, Armada | 47       | vehicle plant  | 53%   | 1.00    | 49%   |
| P14 front, Cortex | 30       | bot lab        | 80%   | 0.72    | 67%   |
| P15 front, Armada | 48       | bot lab        | 73%   | 0.84    | 60%   |
| P15 front, Cortex | 38       | bot lab        | 74%   | 0.95    | 59%   |
| P16 front, Armada | 37       | bot lab        | 62%   | 0.96    | 52%   |
| P16 front, Cortex | 39       | bot lab        | 85%   | 0.62    | 73%   |

| position, faction | openings | opening shape: distinct | top share | entropy | agree | first 6 orders: distinct | top share | entropy | agree |
| ----------------- | -------- | ----------------------- | --------- | ------- | ----- | ------------------------ | --------- | ------- | ----- |
| P1 front, Armada  | 43       | 23                      | 14%       | 4.20    | 5%    | 22                       | 23%       | 3.85    | 9%    |
| P1 front, Cortex  | 33       | 19                      | 12%       | 4.01    | 4%    | 17                       | 18%       | 3.75    | 6%    |
| P2 air, Armada    | 20       | 13                      | 20%       | 3.48    | 6%    | 10                       | 25%       | 3.00    | 11%   |
| P2 air, Cortex    | 62       | 26                      | 13%       | 4.34    | 5%    | 28                       | 16%       | 4.30    | 5%    |
| P3 tech, Armada   | 62       | 24                      | 16%       | 4.04    | 7%    | 26                       | 18%       | 4.18    | 6%    |
| P4 front, Armada  | 53       | 26                      | 13%       | 4.33    | 5%    | 18                       | 19%       | 3.49    | 10%   |
| P4 front, Cortex  | 30       | 18                      | 13%       | 3.95    | 4%    | 18                       | 17%       | 3.83    | 6%    |
| P5 front, Armada  | 38       | 24                      | 11%       | 4.38    | 3%    | 17                       | 24%       | 3.44    | 11%   |
| P5 front, Cortex  | 43       | 19                      | 21%       | 3.83    | 7%    | 17                       | 44%       | 3.05    | 21%   |
| P6 front, Armada  | 42       | 17                      | 21%       | 3.61    | 9%    | 13                       | 29%       | 2.99    | 16%   |
| P6 front, Cortex  | 34       | 15                      | 24%       | 3.28    | 12%   | 13                       | 47%       | 2.79    | 23%   |
| P7 front, Armada  | 39       | 16                      | 23%       | 3.56    | 9%    | 13                       | 36%       | 2.86    | 19%   |
| P7 front, Cortex  | 38       | 13                      | 34%       | 2.95    | 17%   | 11                       | 34%       | 2.70    | 20%   |
| P8 front, Armada  | 39       | 17                      | 18%       | 3.77    | 7%    | 17                       | 18%       | 3.60    | 9%    |
| P8 front, Cortex  | 42       | 12                      | 31%       | 2.92    | 15%   | 15                       | 45%       | 2.98    | 21%   |
| P9 front, Armada  | 43       | 23                      | 16%       | 4.16    | 5%    | 19                       | 19%       | 3.78    | 8%    |
| P9 front, Cortex  | 36       | 21                      | 14%       | 4.16    | 4%    | 15                       | 22%       | 3.40    | 10%   |
| P10 air, Cortex   | 67       | 30                      | 16%       | 4.50    | 5%    | 27                       | 18%       | 4.00    | 8%    |
| P11 tech, Armada  | 66       | 23                      | 20%       | 3.95    | 8%    | 29                       | 15%       | 4.25    | 6%    |
| P12 front, Armada | 43       | 22                      | 14%       | 4.16    | 5%    | 20                       | 19%       | 3.72    | 9%    |
| P12 front, Cortex | 38       | 21                      | 16%       | 4.06    | 5%    | 19                       | 24%       | 3.80    | 8%    |
| P13 front, Armada | 33       | 21                      | 12%       | 4.19    | 3%    | 20                       | 24%       | 3.89    | 7%    |
| P13 front, Cortex | 44       | 22                      | 20%       | 4.01    | 6%    | 15                       | 43%       | 2.88    | 22%   |
| P14 front, Armada | 47       | 24                      | 13%       | 4.26    | 4%    | 17                       | 26%       | 3.41    | 11%   |
| P14 front, Cortex | 30       | 16                      | 23%       | 3.57    | 8%    | 14                       | 23%       | 3.38    | 10%   |
| P15 front, Armada | 48       | 18                      | 19%       | 3.81    | 7%    | 19                       | 33%       | 3.32    | 15%   |
| P15 front, Cortex | 38       | 16                      | 24%       | 3.47    | 10%   | 15                       | 42%       | 3.03    | 19%   |
| P16 front, Armada | 37       | 17                      | 16%       | 3.77    | 6%    | 11                       | 27%       | 3.00    | 13%   |
| P16 front, Cortex | 39       | 17                      | 23%       | 3.70    | 8%    | 16                       | 26%       | 3.32    | 12%   |

Left out (fewer than 20 openings): P1 front, Legion 4, P2 air, Legion 3, P3
tech, Cortex 18, P3 tech, Legion 0, P4 front, Legion 1, P5 front, Legion 0, P6
front, Legion 1, P7 front, Legion 1, P8 front, Legion 3, P9 front, Legion 1,
P10 air, Armada 11, P10 air, Legion 2, P11 tech, Cortex 14, P11 tech, Legion
0, P12 front, Legion 1, P13 front, Legion 4, P14 front, Legion 2, P15 front,
Legion 0, P16 front, Legion 2

### What sets each position apart

Kinds of unit ordered in the first 8 minutes by a larger share of the
position's players than of everyone else's: share here (share elsewhere),
median time of the first such order.

- P1 front: `llt` 87% (68%) at 3:59; `drag` 44% (26%) at 4:58; `makr` 70%
  (58%) at 3:32; `lab` 74% (65%) at 0:12; `hlt` 34% (26%) at 5:39
- P2 air: `ap` 94% (7%) at 0:34; `ca` 81% (5%) at 1:36; `veng` 72% (6%) at
  1:32; `bw` 64% (4%) at 1:45; `valk` 57% (4%) at 5:24
- P3 tech: `ack` 84% (7%) at 5:03; `alab` 87% (12%) at 4:02; `moho` 88% (20%)
  at 5:48; `rectr` 72% (23%) at 1:07; `ck` 91% (61%) at 1:05
- P4 front: `vp` 55% (31%) at 0:00; `cv` 49% (26%) at 0:57; `llt` 79% (68%) at
  4:10; `makr` 68% (58%) at 3:42; `hlt` 35% (26%) at 6:14
- P5 front: `geo` 67% (5%) at 3:11; `rad` 78% (54%) at 3:29; `llt` 92% (68%)
  at 2:10; `thud` 42% (21%) at 1:07; `hlt` 46% (25%) at 5:27
- P6 front: `rad` 79% (54%) at 3:31; `llt` 90% (68%) at 2:58; `beamer` 37%
  (22%) at 4:48; `ak` 37% (24%) at 0:52; `drag` 38% (27%) at 3:25
- P7 front: `rad` 83% (54%) at 3:28; `llt` 95% (67%) at 2:43; `jamt` 40% (18%)
  at 6:15; `ck` 80% (62%) at 0:51; `flea` 35% (17%) at 0:53
- P8 front: `rad` 81% (54%) at 3:40; `llt` 92% (68%) at 3:08; `thud` 39% (21%)
  at 0:58; `ak` 37% (24%) at 0:51; `lab` 76% (64%) at 0:00
- P9 front: `llt` 90% (68%) at 3:43; `makr` 75% (58%) at 3:06; `cv` 40% (26%)
  at 1:00; `drag` 40% (27%) at 4:54; `pw` 31% (20%) at 1:08
- P10 air: `ap` 99% (7%) at 0:35; `veng` 83% (5%) at 1:27; `ca` 75% (6%) at
  1:49; `valk` 63% (4%) at 5:13; `bw` 60% (5%) at 1:58
- P11 tech: `ack` 86% (7%) at 5:17; `alab` 86% (12%) at 3:49; `moho` 90% (20%)
  at 5:59; `rectr` 70% (23%) at 1:10; `ck` 90% (61%) at 1:07
- P12 front: `vp` 58% (31%) at 0:28; `cv` 51% (26%) at 0:57; `flash` 30% (13%)
  at 1:20; `makr` 73% (58%) at 3:18; `jamt` 30% (19%) at 6:35
- P13 front: `geo` 66% (5%) at 3:26; `rad` 81% (54%) at 3:52; `llt` 92% (68%)
  at 2:44; `drag` 45% (26%) at 4:21; `ak` 37% (24%) at 0:50
- P14 front: `llt` 95% (67%) at 2:50; `rad` 78% (54%) at 3:19; `cv` 42% (26%)
  at 1:00; `beamer` 37% (22%) at 5:00; `drag` 41% (26%) at 3:59
- P15 front: `rad` 85% (53%) at 3:15; `llt` 93% (67%) at 3:11; `beamer` 44%
  (21%) at 4:41; `flea` 38% (16%) at 0:52; `rock` 36% (19%) at 0:59
- P16 front: `rad` 90% (53%) at 3:53; `llt` 91% (68%) at 3:15; `ak` 40% (23%)
  at 0:59; `thud` 35% (22%) at 1:59; `necro` 32% (18%) at 1:55

### Factions per position

| position  | openings | Armada | Cortex | Legion | other |
| --------- | -------- | ------ | ------ | ------ | ----- |
| P1 front  | 82       | 52%    | 40%    | 5%     | 2%    |
| P2 air    | 86       | 23%    | 72%    | 3%     | 1%    |
| P3 tech   | 82       | 76%    | 22%    | 0%     | 2%    |
| P4 front  | 85       | 62%    | 35%    | 1%     | 1%    |
| P5 front  | 83       | 46%    | 52%    | 0%     | 2%    |
| P6 front  | 78       | 54%    | 44%    | 1%     | 1%    |
| P7 front  | 81       | 48%    | 47%    | 1%     | 4%    |
| P8 front  | 84       | 46%    | 50%    | 4%     | 0%    |
| P9 front  | 83       | 52%    | 43%    | 1%     | 4%    |
| P10 air   | 81       | 14%    | 83%    | 2%     | 1%    |
| P11 tech  | 83       | 80%    | 17%    | 0%     | 4%    |
| P12 front | 83       | 52%    | 46%    | 1%     | 1%    |
| P13 front | 83       | 40%    | 53%    | 5%     | 2%    |
| P14 front | 83       | 57%    | 36%    | 2%     | 5%    |
| P15 front | 86       | 56%    | 44%    | 0%     | 0%    |
| P16 front | 82       | 45%    | 48%    | 2%     | 5%    |
| all       | 1325     | 50%    | 46%    | 2%     | 2%    |

### First factory per position and faction

| position, faction | openings | bot lab | vehicle plant | aircraft plant | none | hovercraft platform |
| ----------------- | -------- | ------- | ------------- | -------------- | ---- | ------------------- |
| P1 front, Armada  | 43       | 63%     | 37%           | 0%             | 0%   | 0%                  |
| P1 front, Cortex  | 33       | 79%     | 21%           | 0%             | 0%   | 0%                  |
| P2 air, Armada    | 20       | 10%     | 10%           | 80%            | 0%   | 0%                  |
| P2 air, Cortex    | 62       | 0%      | 2%            | 98%            | 0%   | 0%                  |
| P3 tech, Armada   | 62       | 98%     | 2%            | 0%             | 0%   | 0%                  |
| P4 front, Armada  | 53       | 55%     | 43%           | 0%             | 2%   | 0%                  |
| P4 front, Cortex  | 30       | 43%     | 57%           | 0%             | 0%   | 0%                  |
| P5 front, Armada  | 38       | 79%     | 21%           | 0%             | 0%   | 0%                  |
| P5 front, Cortex  | 43       | 84%     | 16%           | 0%             | 0%   | 0%                  |
| P6 front, Armada  | 42       | 64%     | 36%           | 0%             | 0%   | 0%                  |
| P6 front, Cortex  | 34       | 85%     | 15%           | 0%             | 0%   | 0%                  |
| P7 front, Armada  | 39       | 77%     | 23%           | 0%             | 0%   | 0%                  |
| P7 front, Cortex  | 38       | 84%     | 16%           | 0%             | 0%   | 0%                  |
| P8 front, Armada  | 39       | 59%     | 41%           | 0%             | 0%   | 0%                  |
| P8 front, Cortex  | 42       | 86%     | 14%           | 0%             | 0%   | 0%                  |
| P9 front, Armada  | 43       | 65%     | 35%           | 0%             | 0%   | 0%                  |
| P9 front, Cortex  | 36       | 58%     | 42%           | 0%             | 0%   | 0%                  |
| P10 air, Cortex   | 67       | 6%      | 0%            | 94%            | 0%   | 0%                  |
| P11 tech, Armada  | 66       | 94%     | 6%            | 0%             | 0%   | 0%                  |
| P12 front, Armada | 43       | 40%     | 58%           | 0%             | 0%   | 2%                  |
| P12 front, Cortex | 38       | 66%     | 34%           | 0%             | 0%   | 0%                  |
| P13 front, Armada | 33       | 70%     | 30%           | 0%             | 0%   | 0%                  |
| P13 front, Cortex | 44       | 73%     | 23%           | 2%             | 2%   | 0%                  |
| P14 front, Armada | 47       | 47%     | 53%           | 0%             | 0%   | 0%                  |
| P14 front, Cortex | 30       | 80%     | 20%           | 0%             | 0%   | 0%                  |
| P15 front, Armada | 48       | 73%     | 27%           | 0%             | 0%   | 0%                  |
| P15 front, Cortex | 38       | 74%     | 24%           | 3%             | 0%   | 0%                  |
| P16 front, Armada | 37       | 62%     | 38%           | 0%             | 0%   | 0%                  |
| P16 front, Cortex | 39       | 85%     | 15%           | 0%             | 0%   | 0%                  |

### Next-unit accuracy, first 30 orders, held-out games

| position  | orders | faction only | faction and role | faction and position |
| --------- | ------ | ------------ | ---------------- | -------------------- |
| P1 front  | 2460   | 0.602        | 0.598            | 0.555                |
| P2 air    | 2580   | 0.615        | 0.613            | 0.610                |
| P3 tech   | 2460   | 0.661        | 0.652            | 0.648                |
| P4 front  | 2550   | 0.619        | 0.619            | 0.574                |
| P5 front  | 2490   | 0.547        | 0.547            | 0.513                |
| P6 front  | 2340   | 0.600        | 0.601            | 0.582                |
| P7 front  | 2430   | 0.574        | 0.578            | 0.549                |
| P8 front  | 2520   | 0.575        | 0.571            | 0.567                |
| P9 front  | 2490   | 0.616        | 0.610            | 0.587                |
| P10 air   | 2425   | 0.624        | 0.617            | 0.619                |
| P11 tech  | 2490   | 0.649        | 0.637            | 0.632                |
| P12 front | 2490   | 0.629        | 0.618            | 0.602                |
| P13 front | 2472   | 0.565        | 0.557            | 0.517                |
| P14 front | 2490   | 0.590        | 0.592            | 0.578                |
| P15 front | 2580   | 0.598        | 0.597            | 0.562                |
| P16 front | 2460   | 0.597        | 0.596            | 0.572                |
| all       | 39727  | 0.604        | 0.600            | 0.579                |

### Recognising the position from the orders

| minutes | kinds of unit (median) | position right | role right |
| ------- | ---------------------- | -------------- | ---------- |
| 1       | 5                      | 0.168          | 0.868      |
| 2       | 8                      | 0.187          | 0.927      |
| 4       | 11                     | 0.206          | 0.958      |
| 8       | 14                     | 0.239          | 0.976      |

Guessing: 0.062 for the position, 0.749 for the role (always the commonest).

#### Per position after 8 minutes

| position  | role  | openings | recognised | guessed as                                 |
| --------- | ----- | -------- | ---------- | ------------------------------------------ |
| P1 front  | front | 82       | 6%         | P5 front 22%, P15 front 16%, P12 front 13% |
| P2 air    | air   | 86       | 44%        | P10 air 50%, P2 air 44%, P4 front 2%       |
| P3 tech   | tech  | 82       | 55%        | P3 tech 55%, P11 tech 37%, P4 front 4%     |
| P4 front  | front | 85       | 18%        | P12 front 24%, P4 front 18%, P15 front 15% |
| P5 front  | front | 83       | 58%        | P5 front 58%, P13 front 12%, P4 front 8%   |
| P6 front  | front | 78       | 6%         | P5 front 24%, P15 front 22%, P4 front 12%  |
| P7 front  | front | 81       | 10%        | P15 front 22%, P5 front 12%, P12 front 11% |
| P8 front  | front | 84       | 14%        | P5 front 18%, P4 front 17%, P8 front 14%   |
| P9 front  | front | 83       | 10%        | P5 front 23%, P4 front 22%, P15 front 13%  |
| P10 air   | air   | 81       | 67%        | P10 air 67%, P2 air 31%, P12 front 1%      |
| P11 tech  | tech  | 83       | 37%        | P3 tech 55%, P11 tech 37%, P4 front 4%     |
| P12 front | front | 83       | 16%        | P4 front 30%, P12 front 16%, P15 front 12% |
| P13 front | front | 83       | 6%         | P5 front 54%, P9 front 11%, P13 front 6%   |
| P14 front | front | 83       | 1%         | P15 front 22%, P4 front 20%, P5 front 20%  |
| P15 front | front | 86       | 29%        | P15 front 29%, P5 front 14%, P6 front 10%  |
| P16 front | front | 82       | 5%         | P5 front 27%, P15 front 18%, P4 front 13%  |

### Openings that do not fit their position, after 8 minutes

An opening is flagged when the classifier gives the player's own position (or
role: all positions with that role together) less than 0.05.

| own      | flagged             | mu < 30            | mu >= 30           | planted, flagged     |
| -------- | ------------------- | ------------------ | ------------------ | -------------------- |
| position | 392 of 1325 (29.6%) | 284 of 990 (28.7%) | 108 of 335 (32.2%) | 1028 of 1325 (77.6%) |
| role     | 21 of 1325 (1.6%)   | 13 of 990 (1.3%)   | 8 of 335 (2.4%)    | 1305 of 1325 (98.5%) |

Flagged by position:

| position  | openings | flagged | share | of those, another first factory |
| --------- | -------- | ------- | ----- | ------------------------------- |
| P1 front  | 82       | 27      | 33%   | 19                              |
| P2 air    | 86       | 5       | 6%    | 5                               |
| P3 tech   | 82       | 6       | 7%    | 4                               |
| P4 front  | 85       | 41      | 48%   | 2                               |
| P5 front  | 83       | 16      | 19%   | 13                              |
| P6 front  | 78       | 24      | 31%   | 20                              |
| P7 front  | 81       | 28      | 35%   | 17                              |
| P8 front  | 84       | 44      | 52%   | 19                              |
| P9 front  | 83       | 33      | 40%   | 9                               |
| P10 air   | 81       | 2       | 2%    | 2                               |
| P11 tech  | 83       | 3       | 4%    | 2                               |
| P12 front | 83       | 33      | 40%   | 0                               |
| P13 front | 83       | 20      | 24%   | 10                              |
| P14 front | 83       | 37      | 45%   | 6                               |
| P15 front | 86       | 35      | 41%   | 23                              |
| P16 front | 82       | 38      | 46%   | 20                              |

## What drives the meta

- **No water and one vent per side leave three roles.** Six players a side do
  the same job, one techs, one flies. The role is recognised from the builds
  in 98% of cases, the exact one of the sixteen positions in 24%.
- **Unreliable wind makes solar the opener.** With wind from 0 to 16 the front
  row starts `mex mex mex solar solar lab` (the most common start at seven of
  its eight positions, 25 to 37% of openings), not with wind turbines as on
  Supreme Isthmus.
- **Bots or vehicles is a free choice.** Every front position splits between a
  bot lab and a vehicle plant (52 to 82% bots), which is why two players of a
  front position agree on the first factory in only 48 to 70% of pairs. Armada
  orders vehicles more often than Cortex at most of them (41% against 14% at
  `P8`, 53% against 20% at `P14`).
- **The geothermal vent marks one pair of front positions.** `P5` and `P13`
  are the front positions the classifier recognises as a pair (70% and 60% of
  their openings are taken for one of the two), because two thirds of their
  players order a geothermal plant.
- **Tech is on time.** Advanced construction bots are ordered soon after five
  minutes (median 5:03 and 5:17), in line with the guide's "second-tier units
  from 5:00".
- **Strong players choose their position.** 36 to 40 of the 81 to 86 openings
  at `P7`, `P8` and `P15` are by players with mu ≥ 30, and fewer than 20 at
  `P1`, `P5`, `P9` and `P13`.
