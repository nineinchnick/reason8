# Supreme Isthmus v2.1

The most played map of the slice: two teams of 8 in opposite corners, a land
bridge between them and a sea on either side. It has the most varied meta of
the three maps: seven of its eight positions open in a way of their own.
Method, sample and the terms used in the tables are in
[`README.md`](README.md).

## Summary

Supreme Isthmus has the most varied meta of the three maps: builds tell seven
of its eight places apart, and a position is mistaken mostly for its image on
the other side. Water, geothermal vents and the distance from the middle make
the difference: two players per team go to sea, the pond player builds tidal
generators first, the players near a vent build a geothermal plant within
about three minutes, and the front players at the land bridge order combat
units in the first minute. Before the first factory most players start the
same way (37 to 76% of a position order exactly three extractors and three
wind turbines). The role alone does not describe a position here: six
positions are front, and the two at the pond play nothing like the other four.
148 games, 140 to 151 openings per position.

This is why the [findings of the three maps](README.md#findings) give a model
the position, not only the role, and why the slice
[starts with this map](README.md#recommendation-for-the-first-slice).

## The map

From the map file (`mapinfo.lua`, height and metal maps) and the
[official map page](https://www.beyondallreason.info/map/supreme-isthmus):

size
: 24 × 24, that is 12,288 × 12,288 map units; by Nikuksis; 16 players

layout
: a half turn: the north-east side is the south-west side rotated 180° about
  the middle. All 90 metal spots have their image.

water
: 46% of the map is below sea level: a sea north-west and a sea south-east of
  the land bridge, and a pond inside each base. Tidal strength 21.

wind
: 1 to 19

metal
: 90 spots; 3 or 4 within 1,000 units of where each position starts

geothermal vents
: 4, two per side: one beside `P7` and `P15`, one on the hill above the cove
  of the north-west sea (south-east for the other team)

height
: the tech and air positions lie on a plateau in the corner, about 200 units
  above the rest of the base and 6,900 units from the middle

reclaim
: the map file places trees and plants (energy), and nothing that yields
  metal. We could not confirm a metal reclaim field in the middle.

## Positions

The map metadata recommends eight start positions per side for 8v8, sixteen
positions in all: `P1` to `P8` for the south-west side and `P9` to `P16` for
the north-east side. The two sides list the same roles in the same order, so
the positions come in pairs that are each other's image on the map; they are
described together here but measured apart. Percentages are given for the
first and the second position of a pair. What each position orders is in
[What sets each position apart](#what-sets-each-position-apart); how far
players start from the recommended point is in
[Starts and recommended positions](#starts-and-recommended-positions).

`P1` and `P9`, sea
: *Where:* on the map edge, beside the hill that carries the second vent
: *Community name:* geo sea (our reading, see below)
: *Opens with:* a bot lab (89% and 89%), a shipyard in the cove about two and
  a half minutes in (93% and 94%) and a geothermal plant on the hill around
  the third minute (85% and 83%)

`P2` and `P10`, tech
: *Where:* on the plateau in the corner
: *Community name:* tech; eco in some video descriptions
: *Opens with:* a bot lab (99% and 97%) and an advanced bot lab soon after
  three minutes (100% and 97%)

`P3` and `P11`, air
: *Where:* on the plateau in the corner
: *Community name:* air
: *Opens with:* an aircraft plant (98% and 97%), ordered in the first seconds

`P4` and `P12`, front
: *Where:* the recommended point is beside the pond inside the base; players
  start about 800 units from it (median 802 and 777), on the pond's shore
: *Community name:* pond
: *Opens with:* tidal generators in the pond (95% and 99%, the first order),
  then a bot lab (71% and 82%)

`P5` and `P13`, front
: *Where:* at the neck of the land bridge, the positions nearest the middle
: *Community name:* front, frontline
: *Opens with:* a bot lab (87% and 91%), combat bots within the first minute
  and a light laser tower soon after the first minute

`P6` and `P14`, front
: *Where:* 1,200 units behind `P5` and `P13`
: *Community name:* none found; the guides speak of "front" for both
: *Opens with:* a bot lab (74% and 75%) or a vehicle plant, then the same
  units as `P5` and `P13` about a minute later

`P7` and `P15`, front/tech
: *Where:* beside a geothermal vent
: *Community name:* geo, geo spot
: *Opens with:* a bot lab (92% and 94%), a geothermal plant soon after two
  minutes (97% and 99%), then a second-tier economy

`P8` and `P16`, sea
: *Where:* on the shore of the other sea, away from the land bridge
: *Community name:* beach sea, long beach (our reading, see below)
: *Opens with:* a shipyard (77% and 72% as first factory, 99% and 92% within 8
  minutes, in the first minute), or a hovercraft platform

Each sea has one beach-sea and one geo-sea player, from opposite teams: the
south-west team's `P8` faces the north-east team's `P9` across the south-east
sea.

**Community names are labels here, not keys.** No source we read says which
sea position is "geo sea" and which is "beach sea" or "long beach". We matched
them from the orders: one sea player orders a shipyard first, on an open
shore; the other orders bots, then a shipyard in a cove, and a geothermal
plant. The BAR Build Atlas, seen only in search snippets, describes a
"standard beach sea" as a shipyard at 1:47 and a "standard geo sea" as a bot
lab, then a "shipyard in the cove" at 3:17. Treat the two names as likely, not
certain. Names we could not place: "suicide front" or "suicide spawn"
(probably `P5` and `P13`), "backline".

## Sources

[maps-metadata `map_list.yaml`](https://github.com/beyond-all-reason/maps-metadata/blob/main/map_list.yaml)
: *What:* BAR's own map list, the source of the positions: 16 recommended
  start positions for this map with a role each (per side: 3 front, 1
  front/tech, 2 sea, 1 tech, 1 air), and the default start boxes.
: *Read:* the file itself at the pinned commit; the same positions are in the
  `mapmetadata_startpos` lobby option of 145 of our 148 replays

[Official map page](https://www.beyondallreason.info/map/supreme-isthmus)
: *What:* size, wind 1 to 19, tidal 21, "Battle on the land, sea and air"
: *Read:* the page; size, wind and tidal checked against the map file

[RogueL1ke Gaming, "Top 10 High Level Tips for Supreme Isthmus"](https://roguel1kegaming.com/bar-supreme-isthmus-tips/)
: *What:* names the roles frontline, navy, air and tech, and mentions geo and
  the backline. Front should push early with light bots and build a turret
  before 4 minutes; sea should build destroyers quickly; tech or air can
  fortify the hill behind the land bridge with a second-tier constructor.
  Gives no build orders.
: *Read:* the page, through a summarising tool, so we paraphrase

[Drongo, "Beyond All Reason Guide For Beginners - Supreme Isthmus - Build orders for every position"](https://www.youtube.com/watch?v=WQtIkB1X_dw)
: *What:* a video guide with a build order per position
: *Read:* title only; nobody watched it

[BetterStrategy, "Guide | Standard Pond Opener | Supreme Isthmus | Beyond All Reason"](https://www.youtube.com/watch?v=4WKFej0JERc)
: *What:* a video guide for the pond position; the source of the name
: *Read:* title only

[BetterStrategy, "Guide | How to Play Long Beach: The Opener | Supreme Isthmus | Beyond All Reason"](https://www.youtube.com/watch?v=I9wSVeS0Vks)
: *What:* a video guide for "long beach"; the same channel titles games "Geo
  Sea", "Geo Spot", "Pond" and "Long Beach"
: *Read:* title only

[BARCastTV, "Supreme Isthmus Navy Build Order 2024 - Beyond all Reason"](https://www.youtube.com/watch?v=hg4tPwJ-K5E)
: *What:* a navy build order; a second video covers the frontline
: *Read:* title only

[BAR Build Atlas](https://barbuildatlas.com/)
: *What:* a fan site of builds observed in games, by role: front, geo, geo
  sea, beach sea, pond, air, tech
: *Read:* search snippets only; the site answered with an error

## Start setup

| games with                      | games | openings | on a spot |
| ------------------------------- | ----- | -------- | --------- |
| recommended positions shown     | 145   | 2320     | 97.6%     |
| recommended positions not shown | 3     | 48       | 93.8%     |
| default start boxes             | 65    | 1040     | 97.2%     |
| changed start boxes             | 1     | 16       | 100.0%    |
| start boxes not comparable      | 82    | 1312     | 97.7%     |

- **Positions shown.** 145 of the 148 games showed the recommended positions.
  In the 3 that did not, players still started on them (45 of 48 starts).
- **Start boxes.** 65 games used the default boxes their own lobby option
  records, and 1 used boxes of its own. The other 82 were played before 25
  August 2026, when games did not record the default yet, so they can only be
  compared with the pinned map list, whose default for this map changed since:
  81 of them used the corner rectangles that 50 later games record as the
  default of their time, and 1 used a box half a percent narrower.
- The default changed between 5 and 8 November 2026, from a rectangle of 40%
  of the map per corner to a curved area whose bounding box is 56.5% by 63.5%.
  The 15 games since then use the new one.

### Starts and recommended positions

From `reason8 maps check`, on all 148 games: the starts nearest to each
position, how many are "on the spot" (nearer than half the way to the next
recommended position), and their distance from the recommended point in map
units.

| position | role       | nearest starts | on the spot | median | 90% within |
| -------- | ---------- | -------------- | ----------- | ------ | ---------- |
| P1       | sea        | 146            | 96.6%       | 166    | 190        |
| P2       | tech       | 142            | 98.6%       | 134    | 174        |
| P3       | air        | 147            | 99.3%       | 101    | 158        |
| P4       | front      | 154            | 98.1%       | 802    | 878        |
| P5       | front      | 152            | 94.7%       | 96     | 327        |
| P6       | front      | 146            | 97.3%       | 110    | 186        |
| P7       | front/tech | 152            | 99.3%       | 56     | 146        |
| P8       | sea        | 145            | 97.2%       | 105    | 158        |
| P9       | sea        | 144            | 98.6%       | 156    | 181        |
| P10      | tech       | 149            | 98.7%       | 146    | 204        |
| P11      | air        | 146            | 98.6%       | 94     | 159        |
| P12      | front      | 151            | 94.7%       | 777    | 895        |
| P13      | front      | 149            | 94.6%       | 128    | 364        |
| P14      | front      | 151            | 98.0%       | 111    | 165        |
| P15      | front/tech | 148            | 99.3%       | 69     | 500        |
| P16      | sea        | 146            | 96.6%       | 117    | 164        |

## The two sides

The spawn points of the two sides are different positions. Whether the two
sides nevertheless open alike is checked here: each opening is given its place
in its side's list (`P1` and `P9` are both first), and the first side is
compared with the second by the total variation distance of a feature per
place, next to the same distance after shuffling whole teams between the sides
1,000 times.

First side against second side, 148 teams against 148:

| feature                 | distance | shuffled mean | shuffled 95% | p     |
| ----------------------- | -------- | ------------- | ------------ | ----- |
| first factory per place | 0.038    | 0.040         | 0.053        | 0.602 |
| opening shape per place | 0.380    | 0.377         | 0.396        | 0.399 |
| faction per place       | 0.039    | 0.054         | 0.074        | 0.950 |

Share of the most common first factory at the same place of the two lists:

| first side    | second side    | first factory  | first side | second side |
| ------------- | -------------- | -------------- | ---------- | ----------- |
| P1 sea        | P9 sea         | bot lab        | 89% of 141 | 89% of 142  |
| P2 tech       | P10 tech       | bot lab        | 99% of 140 | 97% of 147  |
| P3 air        | P11 air        | aircraft plant | 98% of 146 | 97% of 144  |
| P4 front      | P12 front      | bot lab        | 71% of 151 | 82% of 143  |
| P5 front      | P13 front      | bot lab        | 87% of 144 | 91% of 141  |
| P6 front      | P14 front      | bot lab        | 74% of 142 | 75% of 148  |
| P7 front/tech | P15 front/tech | bot lab        | 92% of 151 | 94% of 147  |
| P8 sea        | P16 sea        | shipyard       | 77% of 141 | 72% of 141  |

No distance stands clear of its shuffled values: the two sides open alike. The
largest gap in the table below is at the pond (71% against 82% bot lab first),
where the rest order a vehicle plant.

## Measurements

148 games, 2368 openings, 2309 of 2368 (97.5%) on a spot, 619 of those by
players with mu >= 30.

223 of 296 (75.3%) teams fill all 8 spots; 24 teams have two players on one
spot.

### Consistency per position, all players

| position       | openings | first factory  | share | entropy | agree |
| -------------- | -------- | -------------- | ----- | ------- | ----- |
| P1 sea         | 141      | bot lab        | 89%   | 0.68    | 80%   |
| P2 tech        | 140      | bot lab        | 99%   | 0.06    | 99%   |
| P3 air         | 146      | aircraft plant | 98%   | 0.14    | 96%   |
| P4 front       | 151      | bot lab        | 71%   | 1.24    | 55%   |
| P5 front       | 144      | bot lab        | 87%   | 0.60    | 77%   |
| P6 front       | 142      | bot lab        | 74%   | 0.83    | 61%   |
| P7 front/tech  | 151      | bot lab        | 92%   | 0.49    | 85%   |
| P8 sea         | 141      | shipyard       | 77%   | 1.11    | 61%   |
| P9 sea         | 142      | bot lab        | 89%   | 0.68    | 79%   |
| P10 tech       | 147      | bot lab        | 97%   | 0.21    | 93%   |
| P11 air        | 144      | aircraft plant | 97%   | 0.24    | 93%   |
| P12 front      | 143      | bot lab        | 82%   | 0.91    | 69%   |
| P13 front      | 141      | bot lab        | 91%   | 0.44    | 83%   |
| P14 front      | 148      | bot lab        | 75%   | 0.86    | 62%   |
| P15 front/tech | 147      | bot lab        | 94%   | 0.33    | 88%   |
| P16 sea        | 141      | shipyard       | 72%   | 1.20    | 56%   |

| position       | openings | opening shape: distinct | top share | entropy | agree | first 6 orders: distinct | top share | entropy | agree |
| -------------- | -------- | ----------------------- | --------- | ------- | ----- | ------------------------ | --------- | ------- | ----- |
| P1 sea         | 141      | 36                      | 21%       | 4.22    | 8%    | 33                       | 57%       | 2.97    | 33%   |
| P2 tech        | 140      | 21                      | 26%       | 3.23    | 15%   | 23                       | 76%       | 1.84    | 57%   |
| P3 air         | 146      | 36                      | 21%       | 4.08    | 10%   | 30                       | 69%       | 2.32    | 48%   |
| P4 front       | 151      | 80                      | 9%        | 5.78    | 2%    | 12                       | 91%       | 0.71    | 83%   |
| P5 front       | 144      | 89                      | 4%        | 6.23    | 1%    | 125                      | 3%        | 6.88    | 0%    |
| P6 front       | 142      | 83                      | 4%        | 6.11    | 1%    | 105                      | 4%        | 6.51    | 1%    |
| P7 front/tech  | 151      | 40                      | 20%       | 4.11    | 10%   | 42                       | 38%       | 3.59    | 19%   |
| P8 sea         | 141      | 62                      | 11%       | 5.33    | 3%    | 49                       | 46%       | 3.83    | 22%   |
| P9 sea         | 142      | 36                      | 24%       | 4.28    | 8%    | 30                       | 65%       | 2.56    | 42%   |
| P10 tech       | 147      | 21                      | 25%       | 3.34    | 13%   | 25                       | 71%       | 2.14    | 50%   |
| P11 air        | 144      | 38                      | 19%       | 4.25    | 8%    | 34                       | 62%       | 2.77    | 39%   |
| P12 front      | 143      | 72                      | 8%        | 5.66    | 2%    | 7                        | 96%       | 0.36    | 92%   |
| P13 front      | 141      | 74                      | 6%        | 5.84    | 2%    | 120                      | 4%        | 6.80    | 0%    |
| P14 front      | 148      | 81                      | 7%        | 5.95    | 2%    | 106                      | 3%        | 6.52    | 1%    |
| P15 front/tech | 147      | 34                      | 20%       | 4.03    | 9%    | 41                       | 37%       | 3.47    | 19%   |
| P16 sea        | 141      | 58                      | 13%       | 5.17    | 4%    | 43                       | 52%       | 3.39    | 27%   |

Most common opening shape:

- P1 sea: `mex win lab win` 21%; `mex win mex win` 12%; `mex win lab necro` 8%
- P2 tech: `mex win lab win` 26%; `mex win lab rectr` 19%; `mex win estor lab`
  16%
- P3 air: `mex win estor ap` 21%; `mex win ap win` 20%; `mex win ap fink` 8%
- P4 front: `tide mex win estor` 9%; `tide mex win lab` 8%;
  `tide mex lab rectr` 5%
- P5 front: `mex lab win mex` 4%; `mex lab ak necro` 3%; `mex lab mex llt` 3%
- P6 front: `mex win lab ak` 4%; `mex win vp fav` 4%; `mex win lab mex` 4%
- P7 front/tech: `mex win lab win` 20%; `mex win lab rectr` 19%;
  `mex win lab ck` 13%
- P8 sea: `mex win mex win` 11%; `mex win estor sy` 11%; `mex win sy tide` 6%
- P9 sea: `mex win lab win` 24%; `mex win mex win` 9%; `mex win lab necro` 6%
- P10 tech: `mex win lab win` 25%; `mex win estor lab` 18%; `mex win lab ck`
  14%
- P11 air: `mex win estor ap` 19%; `mex win ap win` 13%; `mex win ap fink` 10%
- P12 front: `tide mex win lab` 8%; `tide mex win estor` 8%; `tide mex lab ck`
  5%
- P13 front: `lab mex win mex` 6%; `mex lab flea rectr` 4%; `mex win lab flea`
  4%
- P14 front: `mex win vp fav` 7%; `mex win lab win` 6%; `mex win lab flea` 4%
- P15 front/tech: `mex win lab win` 20%; `mex win lab rectr` 18%;
  `mex win lab necro` 10%
- P16 sea: `mex win mex win` 13%; `mex win estor sy` 11%; `mex win estor win`
  7%

Most common first 6 orders:

- P1 sea: `mex mex mex win win win` 57%; `mex mex win mex win win` 5%;
  `mex mex mex win win lab` 3%
- P2 tech: `mex mex mex win win win` 76%; `mex mex win win win win` 3%;
  `mex mex mex solar win win` 2%
- P3 air: `mex mex mex win win win` 69%; `mex mex win win win win` 3%;
  `mex mex mex ap win win` 2%
- P4 front: `tide tide tide tide tide tide` 91%; `mex mex mex win win win` 2%;
  `mex mex tide tide tide tide` 1%
- P5 front: `mex mex mex win win win` 3%; `mex mex mex lab win win` 2%;
  `mex mex lab ak ak ak` 2%
- P6 front: `mex mex mex win win win` 4%; `mex mex mex lab win win` 4%;
  `mex mex mex win win lab` 3%
- P7 front/tech: `mex mex mex win win win` 38%; `mex mex win win win win` 20%;
  `mex mex win win win lab` 5%
- P8 sea: `mex mex mex win win win` 46%; `mex mex win win win win` 4%;
  `mex mex mex tide tide sy` 4%
- P9 sea: `mex mex mex win win win` 65%; `mex mex mex win win lab` 4%;
  `mex mex win win mex win` 2%
- P10 tech: `mex mex mex win win win` 71%; `mex mex win win win lab` 4%;
  `mex mex win mex win win` 3%
- P11 air: `mex mex mex win win win` 62%; `mex mex win win win win` 3%;
  `mex mex win win mex win` 2%
- P12 front: `tide tide tide tide tide tide` 96%; `mex mex win win sy cs` 1%;
  `tide tide tide mex mex mex` 1%
- P13 front: `mex mex mex lab flea flea` 4%; `mex mex mex lab win win` 3%;
  `mex mex lab win win mex` 2%
- P14 front: `mex mex mex win win lab` 3%; `mex mex mex vp fav fav` 3%;
  `mex mex mex lab pw pw` 3%
- P15 front/tech: `mex mex mex win win win` 37%; `mex mex win win win win`
  23%; `mex mex win win win lab` 9%
- P16 sea: `mex mex mex win win win` 52%; `mex mex win mex win win` 5%;
  `mex mex mex tide tide sy` 4%

### Consistency per position, mu ≥ 30

| position       | openings | first factory  | share | entropy | agree |
| -------------- | -------- | -------------- | ----- | ------- | ----- |
| P1 sea         | 45       | bot lab        | 98%   | 0.15    | 96%   |
| P2 tech        | 35       | bot lab        | 100%  | 0.00    | 100%  |
| P3 air         | 36       | aircraft plant | 100%  | 0.00    | 100%  |
| P4 front       | 31       | bot lab        | 52%   | 1.60    | 38%   |
| P5 front       | 48       | bot lab        | 92%   | 0.48    | 84%   |
| P6 front       | 42       | bot lab        | 64%   | 0.94    | 53%   |
| P7 front/tech  | 43       | bot lab        | 100%  | 0.00    | 100%  |
| P8 sea         | 30       | shipyard       | 83%   | 0.88    | 70%   |
| P9 sea         | 52       | bot lab        | 98%   | 0.14    | 96%   |
| P10 tech       | 35       | bot lab        | 94%   | 0.32    | 89%   |
| P11 air        | 30       | aircraft plant | 100%  | 0.00    | 100%  |
| P12 front      | 29       | bot lab        | 79%   | 0.99    | 64%   |
| P13 front      | 56       | bot lab        | 93%   | 0.37    | 86%   |
| P14 front      | 37       | bot lab        | 65%   | 0.94    | 53%   |
| P15 front/tech | 38       | bot lab        | 100%  | 0.00    | 100%  |
| P16 sea        | 32       | shipyard       | 81%   | 0.88    | 67%   |

| position       | openings | opening shape: distinct | top share | entropy | agree | first 6 orders: distinct | top share | entropy | agree |
| -------------- | -------- | ----------------------- | --------- | ------- | ----- | ------------------------ | --------- | ------- | ----- |
| P1 sea         | 45       | 15                      | 24%       | 3.41    | 10%   | 10                       | 69%       | 1.78    | 48%   |
| P2 tech        | 35       | 9                       | 26%       | 2.69    | 16%   | 6                        | 83%       | 1.05    | 68%   |
| P3 air         | 36       | 13                      | 19%       | 3.26    | 10%   | 11                       | 67%       | 2.00    | 44%   |
| P4 front       | 31       | 23                      | 26%       | 4.12    | 6%    | 7                        | 81%       | 1.21    | 65%   |
| P5 front       | 48       | 37                      | 6%        | 5.11    | 1%    | 42                       | 4%        | 5.33    | 1%    |
| P6 front       | 42       | 35                      | 7%        | 5.04    | 1%    | 39                       | 7%        | 5.23    | 0%    |
| P7 front/tech  | 43       | 13                      | 35%       | 2.90    | 18%   | 13                       | 49%       | 2.52    | 27%   |
| P8 sea         | 30       | 19                      | 13%       | 4.02    | 4%    | 9                        | 60%       | 2.07    | 37%   |
| P9 sea         | 52       | 17                      | 38%       | 3.23    | 17%   | 11                       | 71%       | 1.76    | 51%   |
| P10 tech       | 35       | 10                      | 34%       | 2.66    | 19%   | 4                        | 89%       | 0.68    | 78%   |
| P11 air        | 30       | 14                      | 23%       | 3.33    | 10%   | 8                        | 73%       | 1.57    | 53%   |
| P12 front      | 29       | 20                      | 17%       | 4.09    | 4%    | 1                        | 100%      | 0.00    | 100%  |
| P13 front      | 56       | 33                      | 12%       | 4.74    | 3%    | 53                       | 4%        | 5.70    | 0%    |
| P14 front      | 37       | 22                      | 11%       | 4.20    | 4%    | 31                       | 5%        | 4.89    | 1%    |
| P15 front/tech | 38       | 14                      | 26%       | 3.31    | 11%   | 12                       | 37%       | 2.69    | 20%   |
| P16 sea        | 32       | 16                      | 22%       | 3.65    | 7%    | 8                        | 66%       | 1.81    | 44%   |

Most common opening shape:

- P1 sea: `mex win lab win` 24%; `mex win mex win` 16%; `mex win lab necro`
  11%
- P2 tech: `mex win lab win` 26%; `mex win estor lab` 23%; `mex win lab ck`
  17%
- P3 air: `mex win estor ap` 19%; `mex win ap win` 19%; `mex win ap fink` 17%
- P4 front: `tide mex win estor` 26%; `tide mex nanotc win` 6%;
  `tide win estor mex` 3%
- P5 front: `lab mex win mex` 6%; `mex lab rectr ck` 4%; `mex win lab rectr`
  4%
- P6 front: `mex win vp fav` 7%; `mex win lab flea` 5%; `mex vp win fav` 5%
- P7 front/tech: `mex win lab win` 35%; `mex win lab rectr` 23%;
  `mex win lab ck` 9%
- P8 sea: `mex win mex win` 13%; `mex win estor win` 13%; `mex tide sy tide`
  10%
- P9 sea: `mex win lab win` 38%; `mex win lab ck` 12%; `mex win mex win` 8%
- P10 tech: `mex win estor lab` 34%; `mex win lab win` 23%;
  `mex win lab rectr` 17%
- P11 air: `mex win ap fink` 23%; `mex win estor win` 20%; `mex win estor ap`
  13%
- P12 front: `tide win mex win` 17%; `tide mex win lab` 10%;
  `tide fmkr mex win` 7%
- P13 front: `lab mex win mex` 12%; `mex lab flea rectr` 9%; `mex llt mex lab`
  7%
- P14 front: `mex win lab flea` 11%; `mex win vp fav` 11%; `lab mex win mex`
  11%
- P15 front/tech: `mex win lab rectr` 26%; `mex win lab win` 18%;
  `mex win lab necro` 11%
- P16 sea: `mex win estor win` 22%; `mex tide sy win` 12%; `mex win mex win`
  9%

Most common first 6 orders:

- P1 sea: `mex mex mex win win win` 69%; `mex mex win mex win win` 11%;
  `mex mex mex win win lab` 4%
- P2 tech: `mex mex mex win win win` 83%; `mex mex win win win win` 6%;
  `mex mex win win mex win` 3%
- P3 air: `mex mex mex win win win` 67%; `mex mex mex mex win win` 6%;
  `mex mex win mex win win` 6%
- P4 front: `tide tide tide tide tide tide` 81%; `win win win win win win` 3%;
  `mex mex mex solar win win` 3%
- P5 front: `mex mex mex lab llt necro` 4%; `mex mex llt mex lab ak` 4%;
  `lab mex win win mex mex` 4%
- P6 front: `mex mex mex win win lab` 7%; `mex mex mex lab win win` 5%;
  `mex mex mex vp gator gator` 2%
- P7 front/tech: `mex mex mex win win win` 49%; `mex mex win win win win` 21%;
  `mex mex mex win win lab` 5%
- P8 sea: `mex mex mex win win win` 60%; `mex mex mex tide tide sy` 13%;
  `mex mex win mex win win` 7%
- P9 sea: `mex mex mex win win win` 71%; `mex mex mex win win lab` 8%;
  `mex solar lab mex win win` 4%
- P10 tech: `mex mex mex win win win` 89%; `mex mex win mex win win` 6%;
  `mex mex mex solar win lab` 3%
- P11 air: `mex mex mex win win win` 73%; `mex mex win win ap fink` 7%;
  `mex mex solar solar mex win` 3%
- P12 front: `tide tide tide tide tide tide` 100%
- P13 front: `mex mex lab flea flea flea` 4%; `lab mex mex win win mex` 4%;
  `lab mex win win mex mex` 4%
- P14 front: `mex mex lab ak ak ak` 5%; `mex mex mex win win lab` 5%;
  `lab mex win win mex mex` 5%
- P15 front/tech: `mex mex mex win win win` 37%; `mex mex win win win win`
  24%; `mex mex win win win lab` 16%
- P16 sea: `mex mex mex win win win` 66%; `mex mex mex tide tide sy` 12%;
  `mex mex win mex win win` 6%

### Consistency per position and faction, all players

| position, faction      | openings | first factory  | share | entropy | agree |
| ---------------------- | -------- | -------------- | ----- | ------- | ----- |
| P1 sea, Armada         | 58       | bot lab        | 90%   | 0.68    | 80%   |
| P1 sea, Cortex         | 77       | bot lab        | 90%   | 0.66    | 80%   |
| P2 tech, Armada        | 134      | bot lab        | 100%  | 0.00    | 100%  |
| P3 air, Armada         | 23       | aircraft plant | 91%   | 0.43    | 83%   |
| P3 air, Cortex         | 117      | aircraft plant | 99%   | 0.07    | 98%   |
| P4 front, Armada       | 105      | bot lab        | 78%   | 1.03    | 63%   |
| P4 front, Cortex       | 39       | bot lab        | 54%   | 1.43    | 41%   |
| P5 front, Armada       | 74       | bot lab        | 91%   | 0.45    | 83%   |
| P5 front, Cortex       | 61       | bot lab        | 90%   | 0.53    | 82%   |
| P6 front, Armada       | 87       | bot lab        | 68%   | 0.91    | 56%   |
| P6 front, Cortex       | 52       | bot lab        | 85%   | 0.62    | 73%   |
| P7 front/tech, Armada  | 95       | bot lab        | 97%   | 0.23    | 94%   |
| P7 front/tech, Cortex  | 49       | bot lab        | 84%   | 0.77    | 71%   |
| P8 sea, Armada         | 50       | shipyard       | 68%   | 1.31    | 50%   |
| P8 sea, Cortex         | 88       | shipyard       | 82%   | 0.96    | 68%   |
| P9 sea, Armada         | 61       | bot lab        | 84%   | 0.90    | 70%   |
| P9 sea, Cortex         | 77       | bot lab        | 94%   | 0.41    | 87%   |
| P10 tech, Armada       | 132      | bot lab        | 99%   | 0.06    | 98%   |
| P11 air, Armada        | 21       | aircraft plant | 100%  | 0.00    | 100%  |
| P11 air, Cortex        | 116      | aircraft plant | 97%   | 0.24    | 93%   |
| P12 front, Armada      | 106      | bot lab        | 90%   | 0.67    | 80%   |
| P12 front, Cortex      | 31       | bot lab        | 65%   | 0.94    | 53%   |
| P13 front, Armada      | 80       | bot lab        | 92%   | 0.38    | 86%   |
| P13 front, Cortex      | 58       | bot lab        | 91%   | 0.42    | 84%   |
| P14 front, Armada      | 96       | bot lab        | 72%   | 0.86    | 59%   |
| P14 front, Cortex      | 48       | bot lab        | 81%   | 0.79    | 68%   |
| P15 front/tech, Armada | 96       | bot lab        | 94%   | 0.34    | 88%   |
| P15 front/tech, Cortex | 47       | bot lab        | 94%   | 0.34    | 88%   |
| P16 sea, Armada        | 58       | shipyard       | 71%   | 1.32    | 53%   |
| P16 sea, Cortex        | 79       | shipyard       | 73%   | 1.06    | 58%   |

| position, faction      | openings | opening shape: distinct | top share | entropy | agree | first 6 orders: distinct | top share | entropy | agree |
| ---------------------- | -------- | ----------------------- | --------- | ------- | ----- | ------------------------ | --------- | ------- | ----- |
| P1 sea, Armada         | 58       | 21                      | 21%       | 3.79    | 9%    | 18                       | 60%       | 2.53    | 36%   |
| P1 sea, Cortex         | 77       | 24                      | 22%       | 3.75    | 10%   | 19                       | 56%       | 2.70    | 32%   |
| P2 tech, Armada        | 134      | 20                      | 25%       | 3.21    | 15%   | 22                       | 76%       | 1.81    | 58%   |
| P3 air, Armada         | 23       | 14                      | 17%       | 3.62    | 5%    | 9                        | 65%       | 1.98    | 42%   |
| P3 air, Cortex         | 117      | 29                      | 24%       | 3.71    | 12%   | 25                       | 70%       | 2.20    | 49%   |
| P4 front, Armada       | 105      | 59                      | 10%       | 5.40    | 3%    | 9                        | 92%       | 0.62    | 85%   |
| P4 front, Cortex       | 39       | 32                      | 10%       | 4.88    | 1%    | 5                        | 87%       | 0.80    | 76%   |
| P5 front, Armada       | 74       | 49                      | 5%        | 5.40    | 1%    | 70                       | 4%        | 6.09    | 0%    |
| P5 front, Cortex       | 61       | 38                      | 8%        | 5.04    | 2%    | 49                       | 7%        | 5.48    | 1%    |
| P6 front, Armada       | 87       | 50                      | 6%        | 5.42    | 2%    | 70                       | 3%        | 6.02    | 1%    |
| P6 front, Cortex       | 52       | 36                      | 12%       | 4.91    | 2%    | 38                       | 6%        | 5.12    | 1%    |
| P7 front/tech, Armada  | 95       | 24                      | 31%       | 3.49    | 14%   | 26                       | 42%       | 3.20    | 21%   |
| P7 front/tech, Cortex  | 49       | 20                      | 24%       | 3.61    | 10%   | 21                       | 31%       | 3.40    | 15%   |
| P8 sea, Armada         | 50       | 31                      | 12%       | 4.71    | 3%    | 25                       | 40%       | 3.64    | 16%   |
| P8 sea, Cortex         | 88       | 45                      | 14%       | 4.97    | 4%    | 32                       | 50%       | 3.35    | 25%   |
| P9 sea, Armada         | 61       | 25                      | 16%       | 4.18    | 6%    | 18                       | 59%       | 2.58    | 35%   |
| P9 sea, Cortex         | 77       | 20                      | 31%       | 3.55    | 13%   | 18                       | 70%       | 2.07    | 49%   |
| P10 tech, Armada       | 132      | 19                      | 28%       | 3.24    | 14%   | 21                       | 73%       | 1.96    | 53%   |
| P11 air, Armada        | 21       | 12                      | 19%       | 3.44    | 6%    | 8                        | 52%       | 2.29    | 28%   |
| P11 air, Cortex        | 116      | 31                      | 22%       | 3.97    | 9%    | 27                       | 66%       | 2.45    | 44%   |
| P12 front, Armada      | 106      | 54                      | 9%        | 5.31    | 3%    | 6                        | 95%       | 0.38    | 91%   |
| P12 front, Cortex      | 31       | 24                      | 10%       | 4.48    | 2%    | 2                        | 97%       | 0.21    | 94%   |
| P13 front, Armada      | 80       | 41                      | 10%       | 5.03    | 3%    | 70                       | 6%        | 6.03    | 1%    |
| P13 front, Cortex      | 58       | 36                      | 10%       | 4.88    | 3%    | 50                       | 7%        | 5.55    | 1%    |
| P14 front, Armada      | 96       | 52                      | 8%        | 5.33    | 2%    | 69                       | 4%        | 5.93    | 1%    |
| P14 front, Cortex      | 48       | 33                      | 10%       | 4.84    | 2%    | 40                       | 8%        | 5.19    | 1%    |
| P15 front/tech, Armada | 96       | 26                      | 27%       | 3.67    | 13%   | 29                       | 32%       | 3.48    | 17%   |
| P15 front/tech, Cortex | 47       | 15                      | 30%       | 3.17    | 14%   | 13                       | 47%       | 2.49    | 27%   |
| P16 sea, Armada        | 58       | 36                      | 14%       | 4.77    | 4%    | 22                       | 53%       | 2.98    | 29%   |
| P16 sea, Cortex        | 79       | 39                      | 14%       | 4.78    | 4%    | 25                       | 52%       | 3.04    | 28%   |

Left out (fewer than 20 openings): P1 sea, Legion 5, P2 tech, Cortex 5, P2
tech, Legion 1, P3 air, Legion 6, P4 front, Legion 5, P5 front, Legion 7, P6
front, Legion 1, P7 front/tech, Legion 7, P8 sea, Legion 3, P9 sea, Legion 4,
P10 tech, Cortex 13, P10 tech, Legion 2, P11 air, Legion 4, P12 front, Legion
4, P13 front, Legion 3, P14 front, Legion 2, P15 front/tech, Legion 4, P16
sea, Legion 4

### What sets each position apart

Kinds of unit ordered in the first 8 minutes by a larger share of the
position's players than of everyone else's: share here (share elsewhere),
median time of the first such order.

- P1 sea: `sy` 93% (19%) at 2:28; `geo` 85% (19%) at 2:53; `cs` 81% (17%) at
  3:35; `roy` 74% (15%) at 4:29; `pt` 69% (15%) at 3:43
- P2 tech: `ack` 100% (10%) at 4:04; `alab` 100% (12%) at 3:02; `fark` 66%
  (5%) at 6:36; `moho` 99% (40%) at 4:41; `rectr` 94% (37%) at 1:07
- P3 air: `ap` 99% (8%) at 0:03; `ca` 88% (7%) at 1:32; `valk` 79% (6%) at
  1:21; `veng` 79% (6%) at 1:29; `fink` 75% (5%) at 1:15
- P4 front: `tide` 95% (18%) at 0:00; `flea` 30% (13%) at 5:28; `makr` 81%
  (65%) at 3:51; `lab` 73% (69%) at 2:17; `rectr` 44% (41%) at 3:08
- P5 front: `llt` 89% (43%) at 1:02; `rad` 81% (39%) at 1:55; `rock` 42% (10%)
  at 0:34; `thud` 36% (7%) at 0:39; `war` 32% (8%) at 0:27
- P6 front: `llt` 92% (43%) at 2:38; `rock` 35% (10%) at 1:11; `rad` 65% (40%)
  at 3:25; `drag` 32% (11%) at 4:07; `pw` 32% (13%) at 0:34
- P7 front/tech: `geo` 97% (18%) at 2:15; `ageo` 58% (6%) at 6:23; `moho` 89%
  (40%) at 5:38; `vp` 52% (13%) at 5:23; `cv` 46% (11%) at 5:24
- P8 sea: `sy` 99% (19%) at 0:55; `cs` 91% (17%) at 1:49; `frad` 84% (14%) at
  3:08; `pt` 77% (14%) at 2:03; `pship` 74% (14%) at 2:20
- P9 sea: `sy` 94% (19%) at 2:25; `cs` 82% (17%) at 3:31; `geo` 83% (19%) at
  3:03; `roy` 72% (15%) at 4:33; `pt` 65% (15%) at 3:53
- P10 tech: `ack` 97% (10%) at 4:15; `alab` 97% (12%) at 3:14; `moho` 97%
  (40%) at 4:51; `fark` 60% (5%) at 6:33; `rectr` 87% (38%) at 1:08
- P11 air: `ap` 98% (9%) at 0:17; `ca` 88% (7%) at 1:42; `valk` 78% (6%) at
  1:34; `veng` 78% (6%) at 1:43; `fink` 76% (5%) at 1:16
- P12 front: `tide` 99% (18%) at 0:00; `makr` 87% (64%) at 4:04; `flea` 34%
  (13%) at 5:44; `lab` 83% (68%) at 2:24; `estor` 75% (63%) at 2:49
- P13 front: `llt` 92% (43%) at 1:21; `rad` 82% (39%) at 2:05; `rock` 45%
  (10%) at 0:30; `war` 38% (8%) at 0:28; `thud` 34% (7%) at 0:38
- P14 front: `llt` 90% (43%) at 2:29; `rock` 41% (10%) at 0:54; `drag` 39%
  (10%) at 4:54; `rad` 67% (40%) at 3:00; `pw` 30% (13%) at 0:49
- P15 front/tech: `geo` 99% (18%) at 2:08; `ageo` 60% (6%) at 6:14; `vp` 54%
  (13%) at 5:03; `moho` 82% (41%) at 5:39; `avp` 44% (3%) at 6:56
- P16 sea: `sy` 92% (19%) at 0:50; `frad` 87% (14%) at 2:55; `cs` 82% (17%) at
  1:49; `pship` 76% (14%) at 2:18; `pt` 75% (14%) at 1:57

### Factions per position

| position       | openings | Armada | Cortex | Legion | other |
| -------------- | -------- | ------ | ------ | ------ | ----- |
| P1 sea         | 141      | 41%    | 55%    | 4%     | 1%    |
| P2 tech        | 140      | 96%    | 4%     | 1%     | 0%    |
| P3 air         | 146      | 16%    | 80%    | 4%     | 0%    |
| P4 front       | 151      | 70%    | 26%    | 3%     | 1%    |
| P5 front       | 144      | 51%    | 42%    | 5%     | 1%    |
| P6 front       | 142      | 61%    | 37%    | 1%     | 1%    |
| P7 front/tech  | 151      | 63%    | 32%    | 5%     | 0%    |
| P8 sea         | 141      | 35%    | 62%    | 2%     | 0%    |
| P9 sea         | 142      | 43%    | 54%    | 3%     | 0%    |
| P10 tech       | 147      | 90%    | 9%     | 1%     | 0%    |
| P11 air        | 144      | 15%    | 81%    | 3%     | 2%    |
| P12 front      | 143      | 74%    | 22%    | 3%     | 1%    |
| P13 front      | 141      | 57%    | 41%    | 2%     | 0%    |
| P14 front      | 148      | 65%    | 32%    | 1%     | 1%    |
| P15 front/tech | 147      | 65%    | 32%    | 3%     | 0%    |
| P16 sea        | 141      | 41%    | 56%    | 3%     | 0%    |
| all            | 2309     | 55%    | 41%    | 3%     | 1%    |

### First factory per position and faction

| position, faction      | openings | bot lab | aircraft plant | shipyard | vehicle plant | hovercraft platform | none |
| ---------------------- | -------- | ------- | -------------- | -------- | ------------- | ------------------- | ---- |
| P1 sea, Armada         | 58       | 90%     | 2%             | 3%       | 2%            | 3%                  | 0%   |
| P1 sea, Cortex         | 77       | 90%     | 1%             | 3%       | 1%            | 5%                  | 0%   |
| P2 tech, Armada        | 134      | 100%    | 0%             | 0%       | 0%            | 0%                  | 0%   |
| P3 air, Armada         | 23       | 9%      | 91%            | 0%       | 0%            | 0%                  | 0%   |
| P3 air, Cortex         | 117      | 1%      | 99%            | 0%       | 0%            | 0%                  | 0%   |
| P4 front, Armada       | 105      | 78%     | 0%             | 2%       | 16%           | 2%                  | 2%   |
| P4 front, Cortex       | 39       | 54%     | 0%             | 3%       | 36%           | 0%                  | 8%   |
| P5 front, Armada       | 74       | 91%     | 0%             | 0%       | 9%            | 0%                  | 0%   |
| P5 front, Cortex       | 61       | 90%     | 2%             | 0%       | 8%            | 0%                  | 0%   |
| P6 front, Armada       | 87       | 68%     | 0%             | 0%       | 32%           | 0%                  | 0%   |
| P6 front, Cortex       | 52       | 85%     | 0%             | 0%       | 15%           | 0%                  | 0%   |
| P7 front/tech, Armada  | 95       | 97%     | 0%             | 1%       | 2%            | 0%                  | 0%   |
| P7 front/tech, Cortex  | 49       | 84%     | 0%             | 4%       | 12%           | 0%                  | 0%   |
| P8 sea, Armada         | 50       | 14%     | 0%             | 68%      | 2%            | 16%                 | 0%   |
| P8 sea, Cortex         | 88       | 6%      | 1%             | 82%      | 1%            | 10%                 | 0%   |
| P9 sea, Armada         | 61       | 84%     | 0%             | 7%       | 5%            | 5%                  | 0%   |
| P9 sea, Cortex         | 77       | 94%     | 0%             | 0%       | 3%            | 4%                  | 0%   |
| P10 tech, Armada       | 132      | 99%     | 1%             | 0%       | 0%            | 0%                  | 0%   |
| P11 air, Armada        | 21       | 0%      | 100%           | 0%       | 0%            | 0%                  | 0%   |
| P11 air, Cortex        | 116      | 3%      | 97%            | 1%       | 0%            | 0%                  | 0%   |
| P12 front, Armada      | 106      | 90%     | 0%             | 1%       | 5%            | 3%                  | 2%   |
| P12 front, Cortex      | 31       | 65%     | 0%             | 0%       | 35%           | 0%                  | 0%   |
| P13 front, Armada      | 80       | 92%     | 0%             | 0%       | 8%            | 0%                  | 0%   |
| P13 front, Cortex      | 58       | 91%     | 0%             | 0%       | 9%            | 0%                  | 0%   |
| P14 front, Armada      | 96       | 72%     | 0%             | 0%       | 28%           | 0%                  | 0%   |
| P14 front, Cortex      | 48       | 81%     | 0%             | 2%       | 17%           | 0%                  | 0%   |
| P15 front/tech, Armada | 96       | 94%     | 0%             | 0%       | 6%            | 0%                  | 0%   |
| P15 front/tech, Cortex | 47       | 94%     | 0%             | 0%       | 6%            | 0%                  | 0%   |
| P16 sea, Armada        | 58       | 12%     | 2%             | 71%      | 2%            | 14%                 | 0%   |
| P16 sea, Cortex        | 79       | 8%      | 0%             | 73%      | 0%            | 19%                 | 0%   |

### Next-unit accuracy, first 30 orders, held-out games

| position       | orders | faction only | faction and role | faction and position |
| -------------- | ------ | ------------ | ---------------- | -------------------- |
| P1 sea         | 4229   | 0.563        | 0.565            | 0.562                |
| P2 tech        | 4200   | 0.631        | 0.641            | 0.644                |
| P3 air         | 4380   | 0.628        | 0.633            | 0.623                |
| P4 front       | 4530   | 0.710        | 0.707            | 0.736                |
| P5 front       | 4284   | 0.499        | 0.498            | 0.476                |
| P6 front       | 4247   | 0.556        | 0.555            | 0.535                |
| P7 front/tech  | 4530   | 0.562        | 0.574            | 0.575                |
| P8 sea         | 4230   | 0.579        | 0.577            | 0.570                |
| P9 sea         | 4260   | 0.587        | 0.586            | 0.586                |
| P10 tech       | 4410   | 0.647        | 0.662            | 0.665                |
| P11 air        | 4320   | 0.611        | 0.615            | 0.600                |
| P12 front      | 4275   | 0.713        | 0.707            | 0.735                |
| P13 front      | 4211   | 0.498        | 0.499            | 0.478                |
| P14 front      | 4440   | 0.540        | 0.539            | 0.523                |
| P15 front/tech | 4410   | 0.567        | 0.581            | 0.578                |
| P16 sea        | 4226   | 0.568        | 0.568            | 0.549                |
| all            | 69182  | 0.592        | 0.595            | 0.590                |

### Recognising the position from the orders

| minutes | kinds of unit (median) | position right | role right |
| ------- | ---------------------- | -------------- | ---------- |
| 1       | 4                      | 0.299          | 0.729      |
| 2       | 7                      | 0.380          | 0.857      |
| 4       | 10                     | 0.399          | 0.958      |
| 8       | 14                     | 0.418          | 0.963      |

Guessing: 0.062 for the position, 0.376 for the role (always the commonest).

#### Per position after 8 minutes

| position       | role       | openings | recognised | guessed as                                        |
| -------------- | ---------- | -------- | ---------- | ------------------------------------------------- |
| P1 sea         | sea        | 141      | 38%        | P9 sea 54%, P1 sea 38%, P16 sea 3%                |
| P2 tech        | tech       | 140      | 47%        | P10 tech 52%, P2 tech 47%, P7 front/tech 1%       |
| P3 air         | air        | 146      | 55%        | P3 air 55%, P11 air 44%, P10 tech 1%              |
| P4 front       | front      | 151      | 28%        | P12 front 62%, P4 front 28%, P13 front 2%         |
| P5 front       | front      | 144      | 32%        | P13 front 56%, P5 front 32%, P6 front 9%          |
| P6 front       | front      | 142      | 19%        | P13 front 52%, P5 front 19%, P6 front 19%         |
| P7 front/tech  | front/tech | 151      | 41%        | P15 front/tech 47%, P7 front/tech 41%, P2 tech 5% |
| P8 sea         | sea        | 141      | 62%        | P8 sea 62%, P16 sea 29%, P1 sea 4%                |
| P9 sea         | sea        | 142      | 45%        | P1 sea 46%, P9 sea 45%, P16 sea 2%                |
| P10 tech       | tech       | 147      | 48%        | P10 tech 48%, P2 tech 48%, P3 air 2%              |
| P11 air        | air        | 144      | 34%        | P3 air 64%, P11 air 34%, P16 sea 1%               |
| P12 front      | front      | 143      | 63%        | P12 front 63%, P4 front 29%, P16 sea 3%           |
| P13 front      | front      | 141      | 57%        | P13 front 57%, P5 front 30%, P14 front 7%         |
| P14 front      | front      | 148      | 7%         | P13 front 49%, P5 front 22%, P6 front 20%         |
| P15 front/tech | front/tech | 147      | 58%        | P15 front/tech 58%, P7 front/tech 33%, P2 tech 5% |
| P16 sea        | sea        | 141      | 35%        | P8 sea 52%, P16 sea 35%, P1 sea 6%                |

### Openings that do not fit their position, after 8 minutes

An opening is flagged when the classifier gives the player's own position (or
role: all positions with that role together) less than 0.05.

| own      | flagged            | mu < 30            | mu >= 30         | planted, flagged     |
| -------- | ------------------ | ------------------ | ---------------- | -------------------- |
| position | 179 of 2309 (7.8%) | 140 of 1690 (8.3%) | 39 of 619 (6.3%) | 2211 of 2309 (95.8%) |
| role     | 57 of 2309 (2.5%)  | 45 of 1690 (2.7%)  | 12 of 619 (1.9%) | 2276 of 2309 (98.6%) |

Flagged by position:

| position       | openings | flagged | share | of those, another first factory |
| -------------- | -------- | ------- | ----- | ------------------------------- |
| P1 sea         | 141      | 12      | 9%    | 9                               |
| P2 tech        | 140      | 2       | 1%    | 1                               |
| P3 air         | 146      | 4       | 3%    | 2                               |
| P4 front       | 151      | 18      | 12%   | 9                               |
| P5 front       | 144      | 13      | 9%    | 13                              |
| P6 front       | 142      | 9       | 6%    | 0                               |
| P7 front/tech  | 151      | 14      | 9%    | 3                               |
| P8 sea         | 141      | 13      | 9%    | 12                              |
| P9 sea         | 142      | 13      | 9%    | 8                               |
| P10 tech       | 147      | 8       | 5%    | 5                               |
| P11 air        | 144      | 4       | 3%    | 3                               |
| P12 front      | 143      | 10      | 7%    | 6                               |
| P13 front      | 141      | 14      | 10%   | 13                              |
| P14 front      | 148      | 19      | 13%   | 2                               |
| P15 front/tech | 147      | 12      | 8%    | 2                               |
| P16 sea        | 141      | 14      | 10%   | 13                              |

## What drives the meta

- **Water decides two pairs of positions and a third.** Two of eight players
  go to sea, and the pond player turns the strong tide into energy before
  anything else.
- **Geothermal vents decide two more.** `P7` and `P15` sit on one; `P1` and
  `P9` walk to the other. 83 to 99% of them order a geothermal plant within
  about three minutes, against 18 to 19% of everyone else.
- **Distance from the middle orders the rest.** `P5` and `P13` order combat
  units in the first minute, `P6` and `P14` a minute later. The tech and air
  positions, 6,900 units from the middle on their plateau, spend the first
  minutes on economy, an advanced bot lab and aircraft.
- **Wind is good, so everyone starts the same way.** Outside the pond and the
  front, 37 to 76% of a position's players order exactly
  `mex mex mex win win win` first. The opening only becomes the position's own
  at the first factory.
- **A position is mistaken for its image on the other side.** The classifier
  names the right one of the sixteen positions in 42% of cases, and in most of
  the rest it names the position at the same place of the other side's list
  (`P9` for `P1` in 54%, `P3` for `P11` in 64%). Counting the pair, seven of
  the eight places are told apart.
- **The two front lines are one meta.** 71% of `P6` and of `P14` openings are
  taken for `P5` or `P13`. They differ in timing and in a few more vehicle
  plants.
- **The role does not say it all.** Six positions share the role front, and
  the two at the pond play nothing like the other four; the four sea positions
  open with two different factories.
