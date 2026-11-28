# Map meta: positions and openings per map

On the popular team maps every start position has a role and an expected
opening: the **meta**. This directory describes it for the three maps of the
first training slice
([ADR 0014](../../decisions/0014-first-training-slice.md)), with numbers from
replays:

- [Supreme Isthmus v2.1](supreme-isthmus.md)
- [All That Glitters v2.2.3](all-that-glitters.md)
- [Rosetta 1.4.4](rosetta.md)

Each document lists the map's positions with the community sources for them,
says how the games were set up, measures how alike the openings of each
position are, and tests whether a position can be recognised from the builds.
How positions are defined is
[ADR 0011](../../decisions/0011-take-positions-from-the-map-metadata.md).
Code: `reason8/game/maps.py` (BAR's map list), `reason8/game/positions.py`
(positions and start setup), `reason8/openings/extract.py` (what an opening
is) and `reason8/analysis/map_meta.py` (the measurement).

## Summary

Every start position has a meta, but it lies in the first factory and the
role, not in an exact build order. Players start where the game recommends (97
to 99%), and the two sides open alike, so a map's sixteen positions are eight
kinds of opening played twice. The specialised positions agree on their first
factory almost completely (air on an aircraft plant, tech on a bot lab), while
two players of one position rarely order the same first six units. Builds tell
seven kinds of opening apart on Supreme Isthmus; on All That Glitters and
Rosetta they tell only the role, and the front positions look alike. The first
orders are extractors and energy wherever a player starts: telling a simple
model the position does not improve its next-unit accuracy, and on the two
smaller maps it loses up to 2.5 points by splitting the games sixteen ways.
The samples are small: 81 to 148 games per map, 73 to 151 openings per
position.

Used in
[ADR 0011](../../decisions/0011-take-positions-from-the-map-metadata.md) (a
player's position is the nearest recommended start position) and
[ADR 0009](../../decisions/0009-start-with-team-game-openings.md) (openings
per start position); the first model takes the position as one input and
shares everything else
([ADR 0019](../../decisions/0019-first-model-trees-asked-by-every-builder.md)).
The detail is in [Findings](#findings) and in the three map documents.

Replays parsed on 2026-11-22. To reproduce the tables:

```sh
uv run reason8 maps fetch          # once: fetch the pinned map list
uv run reason8 maps check          # start setup, starts and recommended positions
uv run reason8 analysis map-meta   # every other table of the three documents
```

Both read the Parquet tables of the parsed replays
([`replay-format.md`](../../reference/replay-format.md#tables)), and take
`--since` and `--until`. On the two weeks of the tables sample (2,830
replays), `maps check` takes 4.2 s instead of 986 s from the JSON documents,
and `map-meta` 311 s instead of 1,536 s, nearly all of it the measurement; the
reports are the same.

How the maps were chosen is in [`dataset.md`](../../reference/dataset.md); how
openings on Supreme Isthmus moved across balance patches is in
[`game-versions.md`](../game-versions.md).

## Positions

BAR defines the start positions itself. Its
[maps-metadata](https://github.com/beyond-all-reason/maps-metadata) repository
(`map_list.yaml`) recommends start positions per map, named `P1`, `P2`, …,
each with a role, for a number of teams and a team size. The lobby sends them
to every game in the `mapmetadata_startpos` lobby option, and the game draws
them before the start, so a replay carries the positions its players saw. The
game explains the roles like this
([`language/en/interface.json`](https://github.com/beyond-all-reason/Beyond-All-Reason/blob/master/language/en/interface.json)):

Front
: "Build ground units and bring your Commander forward to secure a strong
  central position, taking metal spots along the way."

Tech
: "Focus on economy to support building a Tier 2 factory, then distribute Tier
  2 constructors to the team, and attack with high tier units."

Air
: "Scout enemy players, distribute transports to allies, fight for air
  dominance, bomb enemy bases, and help defend against raids."

Sea
: "Build navy units and secure a strong position on the map. Later, build
  amphibious or air units to invade enemies on land."

A player's position is the nearest recommended start position of their team's
side. It is the spawn point, with its role: `P2`, tech. An 8v8 map has sixteen
positions, `P1` to `P8` for one side and `P9` to `P16` for the other. On the
three maps the two sides list the same roles in the same order, and the
positions at the same place of the two lists are each other's image on the
map, but they are kept apart: `P10` is not `P2`. A start is "on the spot" when
it is nearer to its position than half the way to the next one; the
measurements use only those.

The map list is fetched at a pinned commit into the data directory and read
from there, which keeps it current and every run reproducible.

The community has its own names on top (pond, geo, canyon, …). They are labels
in the map documents, given only where the terrain and the orders identify the
position; the documents say which names we could not place.

## Sample

| map                      | games | openings | on a spot     | by players with mu ≥ 30 |
| ------------------------ | ----- | -------- | ------------- | ----------------------- |
| Supreme Isthmus v2.1     | 148   | 2,368    | 2,309 (97.5%) | 619                     |
| All That Glitters v2.2.3 | 84    | 1,344    | 1,325 (98.6%) | 335                     |
| Rosetta 1.4.4            | 81    | 1,296    | 1,259 (97.1%) | 940                     |

- All are 8v8 games between humans. 310 of the 313 pass the slice filters of
  [`dataset.md`](../../reference/dataset.md): ranked, at least 10 minutes,
  nobody leaving early, lobby average skill at or above the map's median
  (22.1, 21.2 and 34.3). Three Isthmus games parsed for other work fail one of
  them and are kept.
- 248 come from the first 250 replays of the slice's download order (84
  Glitters, 83 Isthmus, 83 Rosetta; 2026-05-23 to 2026-11-20). The other 65
  Isthmus games were parsed earlier, most of them for
  [`game-versions.md`](../game-versions.md), and reach back to December 2025.
- Two Rosetta games were played with a changed water level (the
  `map_waterlevel` lobby option) and are left out.
- "Players with mu ≥ 30" are about the top quarter of Large Team players.
  Rosetta lobbies are much stronger than the others, so most of its players
  qualify.

Each position has 73 to 151 openings, about half of what it would have if the
two sides were merged, and at most 77 by strong players (often fewer than 20).
That is enough for shares of a first factory when they are far from each other
(a share near 50% of 80 openings has a standard error of 6 points) and too
little for anything rare. Legion has 5 to about 25 openings per position on
Rosetta and at most 7 elsewhere.

## How the games started

A lobby can leave the recommended positions out and can change the start
boxes. `reason8.game.positions.start_setup()` records both per game, so that
the dataset can filter or flag such games. In the 315 parsed games (the two
flooded Rosetta games included):

|                                     | Isthmus | Glitters | Rosetta |
| ----------------------------------- | ------- | -------- | ------- |
| games                               | 148     | 84       | 83      |
| recommended positions shown         | 145     | 82       | 83      |
| recommended positions not shown     | 3       | 2        | 0       |
| default start boxes                 | 65      | 84       | 83      |
| changed start boxes                 | 1       | 0        | 0       |
| start boxes that cannot be compared | 82      | 0        | 0       |

- **Positions shown** means the game's `mapmetadata_startpos` option holds a
  layout for its number of teams and team size, which is when the game draws
  them. A player can still switch the display off; a replay does not record
  that. In the 5 games without them, 75 of 80 players started on a recommended
  position anyway (93.8%, against 97 to 99% otherwise).
- **Default start boxes** means every team's box in the replay is the bounding
  box of a default box for that number of teams, and no
  `mapmetadata_startbox_override` changes them. The default is the one the
  game itself records in `mapmetadata_startboxes_set`. Games from before 25
  August 2026 do not record it and are compared with the pinned map list.
- **Cannot be compared**: the default boxes of Supreme Isthmus changed between
  5 and 8 November 2026, so for the 82 older Isthmus games the pinned list
  holds a default they never used. 81 of them used the corner rectangles that
  later games record as the default of their time; 1 used a slightly narrower
  box. With the changed game that makes 1 certain and 1 likely case of
  modified boxes in 315 games.
- Which team gets which box changes from game to game on every map.

## What is measured

An **opening** is the list of units a player ordered in the first 8 minutes
(orders, not finished units; see
[`replay-format.md`](../../reference/replay-format.md)). Unit names are
compared without their faction prefix (`armlab` and `corlab` are both `lab`),
so factions can be pooled. Only openings from a start on the spot count.

Per position, three features of an opening:

first factory
: the kind of the first factory ordered

opening shape
: the first 4 distinct steps, repeats merged, e.g. `mex win lab win`

first 6 orders
: the exact first six orders, e.g. `mex mex mex win win lab`

and for each feature:

share
: the share of the most common value

entropy
: Shannon entropy of the shares, in bits: 0 when everyone does the same. On
  samples this small it reads too low when many values are possible (it cannot
  exceed log₂ of the sample size, 7.3 bits for 160 openings).

agree
: the chance that two different players of the position have the same value.
  Unlike entropy it has no small-sample bias, so it is the number to compare
  between groups of different size.

Three tests, always on games the model has not seen (the games are split into
10 parts; players of one game are never on both sides):

next-unit accuracy
: the frequency baseline of [`game-versions.md`](../game-versions.md) predicts
  each of the first 30 orders from the faction and the two orders before. It
  is compared with the same model told the role, or the position.

recognition
: a naive Bayes classifier reads which kinds of unit a player ordered in the
  first 1, 2, 4 or 8 minutes, and the kind of the first factory, and names the
  position. It sees no coordinates.

off-meta
: an opening is flagged when that classifier gives the player's own position
  less than 5%. As a check, every opening is also planted under the position
  of a random teammate; those should be flagged.

## Unit kinds in the tables

Unit names appear without the faction prefix. The ones that come up most:

economy
: `mex` metal extractor, `moho` advanced metal extractor, `win` wind turbine,
  `solar` and `advsol` solar collectors, `tide` tidal generator, `geo` and
  `ageo` geothermal plants, `estor` energy storage, `makr` energy converter

factories and builders
: `lab` bot lab, `vp` vehicle plant, `ap` aircraft plant, `sy` shipyard,
  `alab` advanced bot lab, `avp` advanced vehicle plant, `ck`, `cv`, `ca`,
  `cs` construction bot, vehicle, aircraft and ship, `ack` advanced
  construction bot, `rectr` and `necro` resurrection bots, `fark` assist bot

defence and scouting
: `llt`, `hlt` and `beamer` laser towers, `rad` radar, `frad` floating radar,
  `jamt` jammer, `drag` dragon's teeth

combat units
: `pw`, `ak`, `rock`, `storm`, `thud`, `war` first-tier bots, `flea` scout
  bot, `fav` scout vehicle, `fink` scout plane, `veng` fighter, `bw` light
  gunship, `valk` air transport, `pt` patrol boat, `pship` frigate, `roy`
  destroyer

## Findings

|                                                 | Isthmus | Glitters | Rosetta |
| ----------------------------------------------- | ------- | -------- | ------- |
| starts on a recommended position                | 97.5%   | 98.6%    | 97.1%   |
| teams that fill all 8 positions                 | 75.3%   | 83.9%    | 76.5%   |
| sides differ in first factory per place         | 0.038   | 0.057    | 0.046   |
| the same after shuffling teams (mean)           | 0.040   | 0.058    | 0.042   |
| position recognised after 8 minutes (guess: 6%) | 41.8%   | 23.9%    | 27.2%   |
| role recognised after 8 minutes                 | 96.3%   | 97.6%    | 97.9%   |
| role recognised after 2 minutes                 | 85.7%   | 92.7%    | 89.5%   |
| next-unit accuracy, faction only                | 59.2%   | 60.4%    | 54.3%   |
| next-unit accuracy, faction and role            | 59.5%   | 60.0%    | 54.4%   |
| next-unit accuracy, faction and position        | 59.0%   | 57.9%    | 52.5%   |
| real openings flagged against their position    | 7.8%    | 29.6%    | 24.9%   |
| planted openings flagged against the position   | 95.8%   | 77.6%    | 84.9%   |
| real openings flagged against their role        | 2.5%    | 1.6%     | 1.4%    |
| planted openings flagged against the role       | 98.6%   | 98.5%    | 97.3%   |

- **Players start where the game recommends.** 97 to 99% of starts are on a
  recommended position, at a median of 12 to 184 map units from the point at
  45 of the 48 positions. The exceptions are the two pond positions of Supreme
  Isthmus, whose players start at the water about 800 units from the point and
  are still nearest to it, and one air position of All That Glitters (358).
- **The two sides open alike.** At the same place of the two sides' lists the
  first factories differ by 0.04 to 0.06 (total variation), which is what
  shuffling teams between the sides gives (p 0.35 to 0.60); opening shape and
  faction agree as well (p 0.40 to 0.95). So the sixteen positions are eight
  kinds of opening played on two sides, and the classifier cannot tell a
  position from its image: it names the right one of sixteen in 24 to 42% of
  cases, and on Isthmus most of its misses are the image on the other side.
- **The meta is strongest in the first factory, not in a build order.** The
  specialised positions agree on their first factory almost completely (air 93
  to 98% aircraft plant on Isthmus and Glitters, tech 89 to 99% bot lab, the
  ends of Rosetta's front line 96 to 100%). The exact first six orders are far
  less settled. Leaving aside the Isthmus pond, where they are one dragged
  line of tidal generators, two players of the same position agree on them in
  at most 57% of pairs (Isthmus `P2`, tech), and in under 1% at the Isthmus
  front (`P5` and `P13`).
- **Supreme Isthmus has seven kinds of opening, the other two maps have
  three.** On Isthmus a position is mistaken for its image on the other side,
  and the second front line (`P6`, `P14`) for the first (`P5`, `P13`); nothing
  else is confused. On Glitters and Rosetta the front positions can hardly be
  told apart from their builds, while tech and air can (the role is right in
  98%). There the role is the whole meta.
- **The role alone is not enough on Isthmus.** Six of its positions have the
  role front, and the two at the pond open like nothing else; its four sea
  positions open with two different factories. There the position carries what
  the role does not.
- **The first orders are generic.** Telling the frequency model the position
  loses 0.2 points on Isthmus and 1.8 to 2.5 on the other maps, because it
  splits few games sixteen ways; telling it the role changes little (+0.3 to
  −0.4). Most early orders are extractors and energy whatever the position;
  the position decides the factory and what follows. A learned model should
  take the position as an input and share everything else, not be one model
  per position.
- **Factions follow roles.** Air is played as Cortex (80 to 81% on Isthmus, 72
  to 83% on Glitters, 63 to 68% on Rosetta, against 41 to 46% overall) and
  tech as Armada on Isthmus (90 to 96%) and Glitters (76 to 80%), though not
  on Rosetta (39 to 48%). Within a position the factions mostly order the same
  first factory. The gaps of 20 points or more are about vehicles: at the
  Isthmus pond Cortex orders a bot lab first less often (54% and 65% against
  78% and 90%), and at several front positions of Glitters Armada does (59%
  against 86% at `P8`, 47% against 80% at `P14`).
- **Strong players are a little more uniform, not different.** On Isthmus,
  players with mu ≥ 30 all order the usual first factory at the geothermal,
  air and one of the tech positions (100% of 30 to 43 openings each) and are
  flagged less often (6.3% against 8.3%; on Rosetta 23.3% against 29.5%). On
  Glitters there is no such difference (32.2% against 28.7%). Strong players
  are not spread evenly over the positions: on Glitters 36 to 40 of the 81 to
  86 openings at `P7`, `P8` and `P15` are theirs, and fewer than 20 at eight
  other positions.
- **Off-meta openings can be told at the level of the role.** Against the role
  the classifier flags 1.4 to 2.5% of real openings and 97 to 99% of planted
  ones. Against the exact position it flags many real openings too, because a
  position and its image look the same; only on Isthmus is it usable (7.8%
  real, 95.8% planted).

## Recommendation for the first slice

Start with **Supreme Isthmus v2.1**. It has the most games (22k in the slice),
the most distinct positions and the clearest per-position meta, so a model
that has learned positions shows it there: seven kinds of opening to tell
apart, and a classifier on builds alone already names the position or its
image on the other side in most cases. Within it, tech, air, the geothermal
positions and the sea positions are the scripted ones; the front positions are
the least settled and the hardest to imitate.

Keep **All That Glitters** as the second map: no water, three roles, and as
many games. It is the place to check that a model given only the role does as
well as one given the position. **Rosetta** stays the small test of whether
this carries over to a third map and to stronger lobbies.

## Limits

- **Small samples.** 81 to 148 games per map. Shares of rare openings, Legion,
  and anything split by position, faction and skill at once are not
  measurable. Five games without the recommended positions and two with
  modified boxes say nothing about how such games differ.
- **Orders, not builds.** An order can be cancelled or never finished. One
  drag of the mouse orders a whole line of buildings, which is why "first 6
  orders" at the Isthmus pond is six tidal generators for 94% of players.
- **A position is a start.** 1.4 to 2.9% of players start on no recommended
  position, 16 to 25% of teams leave one empty or double one up, and a player
  may play another role than the position's. Players flagged as off-meta
  include these.
- **Sixteen positions halve the sample.** Each position has 73 to 151
  openings. The check that the two sides open alike can only rule out large
  differences: with 80 openings per position, gaps of ten points in a first
  factory share are within the noise.
- **No ground truth for "off-meta".** The planted openings test whether a
  mismatch is noticed, not whether a flagged real opening was a mistake.
- **A simple classifier.** Naive Bayes over the set of unit kinds ordered. It
  ignores the order of the builds, where they were placed, and the fact that a
  team has one player per position, all of which would help.
- **Names.** Community names come from video titles and one written guide; we
  watched no video. The names we could not tie to a position are listed per
  map.
