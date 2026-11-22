# Game versions, balance patches and openings

BAR is rebalanced every few weeks. This document lists the balance patches of
the last 12 months with the game versions they shipped in, measures how much
openings on Supreme Isthmus moved across them, and describes what to do after
a patch. The policy that follows from it is
[ADR 0012](adr/0012-keep-the-time-window-across-balance-patches.md). Code:
`reason8/game_versions.py` (versions, patches, checks) and
`reason8/opening_shift.py` (the measurement).

Dump of 2026-11-21; replays parsed on 2026-11-22.

## How versions work

A game version looks like `Beyond All Reason test-32018-ad135b9`. BAR is
released from the `stable` branch of
[Beyond-All-Reason](https://github.com/beyond-all-reason/Beyond-All-Reason):
each release is a pull request "Release YYYY.MM.DD-N" that merges `master`
into `stable`. The hash is that merge commit and the number is the count of
commits on `stable` at the release (32018 for the newest one, checked against
GitHub). We call the number the **build**. It only grows, so it orders
versions; `reason8.game_versions.build_number()` reads it.

- **376 releases in 12 months**, 8.4 builds a day. A version is in use for 1.4
  days (median).
- **Versions overlap.** Lobbies keep running the version they started with: a
  version is still played 0.7 days (median) and up to 4.6 days after the next
  one appears. In the week after a balance release, 0–3.6% of games still ran
  an older build. So a patch boundary is a build, not a date:
  `select_matches(min_build=...)` cuts by build.
- **Not every version is a release.** 2,488 of 696k games have no version and
  5 ran a pull-request build (`Beyond All Reason pr-9493-…`). They have no
  place in the order.
- **A game's balance is its build plus its lobby options**; see
  [Lobby options](#lobby-options-that-change-balance).

## Balance patches of the last 12 months

Sources: the game's
[`changelog.md`](https://github.com/beyond-all-reason/Beyond-All-Reason/blob/master/changelog.md)
(`changelog.txt` until September 2026), the pull requests that changed it, and
the pull requests labelled "Scheduled Balance Release". The version is the
first release whose history contains the patch's merge commit; the date is
that release. A patch merged without a changelog entry would be missing here.

"Changes openings" marks patches that touch the cost, build time or build
power of what players order in the first minutes: first-tier economy,
factories, constructors, construction turrets and the main first-tier combat
units. It is our reading of the patch notes, not a measurement. The list is
`BALANCE_PATCHES` in `reason8/game_versions.py`.

**Season 3** — `Beyond All Reason test-29241-5b8d492`, 2026-01-08
: *Source:*
  [pull request 6583](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/6583)
: *Changes:* T1 aircraft plants 60 metal cheaper, hovercraft platforms
  cheaper, construction turrets 210 → 230 metal, T2 factories 300 metal
  cheaper with twice the build power, T2 units take about 30% longer to build,
  smaller and cheaper fusions
: *Changes openings:* yes

**Shield rework** — `Beyond All Reason test-29251-74281f6`, 2026-01-10
: *Source:*
  [pull request 6625](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/6625)
: *Changes:* shields block projectiles instead of bouncing them (a lobby
  option before that)
: *Changes openings:* no

**February balance patch** — `Beyond All Reason test-29466-a701d9c`,
2026-02-16 : *Source:*
[pull request 6801](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/6801)
\: *Changes:* radar health, mines, T2 units, idle auto-heal : *Changes
openings:* no

**Brake rate and sight distance** — `Beyond All Reason test-30051-5a2ce0d`,
2026-05-04 : *Source:*
[pull request 7542](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/7542)
\: *Changes:* minimum brake rate and sight distance for vehicles and bots :
*Changes openings:* no

**May balance patch** — `Beyond All Reason test-30236-cdfd0a0`, 2026-05-29
: *Source:*
  [pull request 7620](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/7620)
: *Changes:* T1 bot constructors +70 health, Stout, Brute, Pounder and Rover
  take longer to build, Pawn and Blitz weaker against aircraft
: *Changes openings:* yes

**Commando patch** — `Beyond All Reason test-30299-e09aa5c`, 2026-06-05
: *Source:*
  [pull request 7853](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/7853)
: *Changes:* Commando
: *Changes openings:* no

**July balance patch** — `Beyond All Reason test-30755-148afa8`, 2026-07-23
: *Source:*
  [pull request 8333](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/8333)
: *Changes:* Stout and Brute +10% build time, Rover 1000 → 1100 build time,
  Grunt 42 → 43 metal, stronger anti-air turrets, dearer T2 fighters
: *Changes openings:* yes

**Naval anti-air** — `Beyond All Reason test-30874-203ff94`, 2026-08-05
: *Source:*
  [pull request 8621](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/8621)
: *Changes:* floating anti-air turrets match the land ones
: *Changes openings:* no

**August balance patch** — `Beyond All Reason test-31075-1913fe9`, 2026-08-25
: *Source:*
  [pull request 8726](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/8726)
: *Changes:* T1 and seaplane air constructors 35% cheaper in energy, 35%
  faster to build and 35% slower; stronger nukes; Legion's basic metal
  extractor brought in line with the others and its T1.5 extractor removed
: *Changes openings:* yes

**Air constructors and mobile jammers** —
`Beyond All Reason test-31357-b06bb1a`, 2026-09-19 : *Source:*
[pull request 9218](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/9218)
\: *Changes:* T1 air constructors lose 10 build power; mobile jammer speeds and
costs : *Changes openings:* yes

**Vertical missile launchers** — `Beyond All Reason test-31479-433a460`,
2026-10-01 : *Source:*
[pull request 9415](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/9415),
follow-up
[9489](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/9489) in
`test-31510-18d8f9a` : *Changes:* flight paths, damage and costs of missile
units and buildings : *Changes openings:* no

**Turrets, anti-air and missile flight** —
`Beyond All Reason test-31720-0f97aa5`, 2026-10-23 : *Source:* pull requests
[9752](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/9752),
[9731](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/9731),
[9505](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/9505),
[9496](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/9496) :
*Changes:* light laser turrets aim before the enemy is in range, anti-air
missiles retarget, mobile missile flight reverted, minelayers brake faster :
*Changes openings:* no

**Navy standardisation** — `Beyond All Reason test-31891-0460365`, 2026-11-08
: *Source:*
  [pull request 10016](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/10016)
: *Changes:* naval mines, radars and nuclear submarines match the land ones
: *Changes openings:* no

Two older patches are in the list because the 12 months start under them: the
**July 2025 balance patch** (`test-28407-2b4777c`,
[pull request 5543](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/5543):
T1 factories 150 metal cheaper with 100 → 150 build power, commander 25 → 30
energy) and the **August 2025 balance patch** (`test-28548-1d44e99`,
[pull request 5736](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/5736)).

**Legion** gets its own patches almost every month (pull requests 6408, 6441,
6586, 6754, 6926, 7003, 7276, 7902, 8266, 9258, 9519, 9995). They are not in
`BALANCE_PATCHES`: Legion is 3% of players in the slice, too few to measure,
and the faction is still behind a lobby option.

### Lobby options that change balance

Balance also depends on lobby options, and ranked lobbies switch them on. Of
the 142 sampled ranked games (below), **only 38 had none of them on**:

| option                          | games on, of 142 | what it does                             |
| ------------------------------- | ---------------- | ---------------------------------------- |
| `naval_balance_tweaks`          | 90               | changed naval units and defences         |
| `community_balance_patch`       | 31               | community changes to about ten units     |
| `shieldsrework`                 | 16               | the shield rework before it became base  |
| `experimentallegionfaction`     | 15               | Legion can be picked                     |
| `proposed_unit_reworks`         | 13               | unit reworks proposed for the base game  |
| `tweakdefs*`, `tweakunits*`     | 1                | custom unit stats typed in by the host   |
| `multiplier_*` (anything but 1) | 0                | global multipliers (build power, income) |

Options come and go with releases: `community_balance_patch` was added in
build 29214
([pull request 6550](https://github.com/beyond-all-reason/Beyond-All-Reason/pull/6550))
and is last seen in the sample in build 31001; `shieldsrework` ended when the
shield rework became part of the base game in build 29251. The match dumps
don't have lobby options; the parsed replay does (`modoptions`).
`reason8.game_versions.balance_options()` returns the ones that are on.

## How much do openings shift?

### Sample

142 ranked 8v8 games on Supreme Isthmus v2.1 that pass the slice filters
([`dataset.md`](dataset.md), lobby average skill ≥ 22.1): 2,272 openings.

- 60 games drawn at random for this measurement, 20 from each of three ranges
  of builds: 29034–29213 (December 2025, before Season 3), 30299–30627 (June
  and July 2026, after the May patch) and from 31720 (since 2026-10-23).
- The 82 other slice-quality Isthmus games parsed locally, most of them from
  the first 250 replays downloaded for the slice, spread over its 182 days.

Grouped by the patches that change openings, merging the last two so the
newest group is not tiny:

| group              | builds       | games | openings |
| ------------------ | ------------ | ----- | -------- |
| before Season 3    | 29034..29240 | 20    | 320      |
| May patch          | 30236..30754 | 49    | 784      |
| July patch         | 30755..31074 | 11    | 176      |
| since August patch | 31075..      | 62    | 992      |

No game of the Season 3 era itself (January to May 2026) is in the sample; the
comparison of "before Season 3" with later groups spans it.

[ADR 0012](adr/0012-keep-the-time-window-across-balance-patches.md) quotes the
first run of this measurement, on 94 of these games and with start spots found
by clustering. The numbers here are from the re-run on all 142, with the start
positions of the map metadata; the conclusions are the same.

### Method

An opening is the list of units a player ordered in the first 8 minutes
(`Replay.build_orders()`; orders, not finished units). From it:

first factory
: the kind of the first factory ordered (bot lab, vehicle plant, …)

opening shape
: the first 4 distinct steps without the faction prefix, repeats merged, e.g.
  `mex win lab ck`

first 6 orders
: the exact first six unit names

start position
: the recommended start position of the map metadata the player started on
  (`reason8.positions`,
  [ADR 0015](adr/0015-take-positions-from-the-map-metadata.md),
  [`maps/supreme-isthmus.md`](maps/supreme-isthmus.md)): sixteen on this map,
  `P1` to `P8` for one side and `P9` to `P16` for the other. 2,216 of the
  2,272 openings are on one.

Two measures:

- **Distance between two groups**: total variation distance between the shares
  of a feature (0 = same shares, 1 = nothing in common). Two samples of one
  population are never at distance 0, so each distance comes with its **noise
  floor**: the same distance after shuffling whole games between the two
  groups 1,000 times (mean, 95th percentile, and *p*, the share of shuffles at
  or above the measured distance).
- **Next-unit accuracy**: a frequency model predicts each of a player's first
  30 orders from the faction and the previous two orders (the baseline a real
  model has to beat). Train it on one group, test it on the newest group, and
  compare with the same model trained on equally many *other* games of the
  newest group. Intervals are 95% bootstrap intervals over test games.

### Results

**Shares barely move.** First factory, all factions:

|                     | before Season 3 | May patch | July patch | since August patch |
| ------------------- | --------------- | --------- | ---------- | ------------------ |
| openings            | 320             | 784       | 176        | 992                |
| bot lab             | 64%             | 67%       | 69%        | 67%                |
| aircraft plant      | 12%             | 13%       | 12%        | 13%                |
| shipyard            | 12%             | 9%        | 10%        | 10%                |
| vehicle plant       | 10%             | 8%        | 7%         | 7%                 |
| hovercraft platform | 2%              | 4%        | 1%         | 2%                 |

The most common opening shapes (`mex win lab win` 8% → 10%,
`mex win lab rectr` 8% → 5%, `mex win mex win` 8% → 4%) move by a few points,
within what 300–1,000 openings can show. Armada opens with a bot lab in 77–81%
of openings in every group, Cortex in 47–55% (aircraft plant 24–25%).

**The start position decides the opening, the patch does not.** Share of the
most common first factory per position (the July group, with 10 to 12 openings
per position, is left out):

| position | first factory  | before Season 3 | May patch  | since August patch |
| -------- | -------------- | --------------- | ---------- | ------------------ |
| P1       | bot lab        | 90% of 20       | 89% of 47  | 88% of 56          |
| P2       | bot lab        | 100% of 19      | 100% of 46 | 98% of 58          |
| P3       | aircraft plant | 95% of 20       | 98% of 49  | 98% of 61          |
| P4       | bot lab        | 70% of 20       | 69% of 48  | 71% of 65          |
| P5       | bot lab        | 75% of 20       | 89% of 47  | 89% of 61          |
| P6       | bot lab        | 65% of 20       | 82% of 45  | 75% of 59          |
| P7       | bot lab        | 95% of 20       | 88% of 50  | 92% of 65          |
| P8       | shipyard       | 75% of 20       | 71% of 48  | 81% of 57          |
| P9       | bot lab        | 79% of 19       | 89% of 46  | 92% of 61          |
| P10      | bot lab        | 100% of 20      | 98% of 48  | 94% of 62          |
| P11      | aircraft plant | 100% of 20      | 98% of 46  | 95% of 61          |
| P12      | bot lab        | 65% of 20       | 81% of 48  | 88% of 59          |
| P13      | bot lab        | 84% of 19       | 87% of 47  | 95% of 59          |
| P14      | bot lab        | 73% of 22       | 77% of 48  | 69% of 61          |
| P15      | bot lab        | 95% of 19       | 92% of 49  | 97% of 62          |
| P16      | shipyard       | 79% of 19       | 69% of 48  | 76% of 58          |

Between two start positions the first-factory distance is 0.24 (median; 0.01
to 0.98). Between patch groups it is 0.04 to 0.08, which is the noise floor:

| comparison                       | games    | feature                    | distance | shuffled mean | shuffled p95 | p    |
| -------------------------------- | -------- | -------------------------- | -------- | ------------- | ------------ | ---- |
| before Season 3 vs since August  | 20 vs 62 | first factory              | 0.078    | 0.069         | 0.099        | 0.26 |
| before Season 3 vs since August  | 20 vs 62 | first factory per position | 0.182    | 0.185         | 0.211        | 0.56 |
| before Season 3 vs since August  | 20 vs 62 | opening shape              | 0.485    | 0.453         | 0.479        | 0.03 |
| before Season 3 vs since August  | 20 vs 62 | first 6 orders             | 0.419    | 0.397         | 0.421        | 0.07 |
| May patch vs since August        | 49 vs 62 | first factory              | 0.043    | 0.052         | 0.075        | 0.75 |
| May patch vs since August        | 49 vs 62 | first factory per position | 0.157    | 0.139         | 0.161        | 0.08 |
| May patch vs since August        | 49 vs 62 | opening shape              | 0.385    | 0.377         | 0.398        | 0.25 |
| May patch vs since August        | 49 vs 62 | first 6 orders             | 0.330    | 0.338         | 0.358        | 0.77 |
| July patch vs since August       | 11 vs 62 | first factory              | 0.065    | 0.086         | 0.126        | 0.82 |
| July patch vs since August       | 11 vs 62 | first factory per position | 0.254    | 0.221         | 0.255        | 0.06 |
| July patch vs since August       | 11 vs 62 | opening shape              | 0.514    | 0.518         | 0.554        | 0.55 |
| July patch vs since August       | 11 vs 62 | first 6 orders             | 0.447    | 0.429         | 0.467        | 0.17 |
| builds 31075–31719 vs from 31720 | 31 vs 31 | first factory              | 0.069    | 0.065         | 0.093        | 0.41 |
| builds 31075–31719 vs from 31720 | 31 vs 31 | first factory per position | 0.183    | 0.172         | 0.202        | 0.25 |
| builds 31075–31719 vs from 31720 | 31 vs 31 | opening shape              | 0.421    | 0.427         | 0.456        | 0.64 |
| builds 31075–31719 vs from 31720 | 31 vs 31 | first 6 orders             | 0.379    | 0.381         | 0.403        | 0.57 |

None of the distances stands clear of its noise floor. Opening shape between
the oldest and the newest group comes closest (p 0.03, and 0.64 inside the
newest group), which fits a slow drift in the finer order of steps, but with
sixteen tests in the table one p of 0.05 or less is expected by chance.

**Lobby options show no effect either.** `naval_balance_tweaks` on (90 games)
against off (52): first factory 0.049 (noise 0.047), opening shape 0.363
(noise 0.364). `community_balance_patch`, `proposed_unit_reworks` and
`shieldsrework`: every p above 0.05, with 13–31 games on one side (the lowest
are `shieldsrework` on first factory, 0.060, and `proposed_unit_reworks` on
the first 6 orders, 0.061; both options exist only in the oldest group).
Legion-enabled games do differ (first factory 0.28, p 0.001), because they
contain Legion players, whose units are a different vocabulary.

**An old model predicts today's openings as well as a new one**, and old games
help more than they hurt:

| trained on      | games | accuracy on "since August patch" | equally many newest games | difference (95%)        |
| --------------- | ----- | -------------------------------- | ------------------------- | ----------------------- |
| before Season 3 | 20    | 0.568                            | 0.564                     | +0.003 (−0.003..+0.013) |
| May patch       | 49    | 0.580                            | 0.580                     | +0.000 (−0.004..+0.004) |
| July patch      | 11    | 0.555                            | 0.551                     | +0.004 (−0.004..+0.014) |

| training data for "since August patch" | games | accuracy | difference (95%)        |
| -------------------------------------- | ----- | -------- | ----------------------- |
| since August patch only                | 61    | 0.587    |                         |
| + July patch                           | 72    | 0.586    | −0.001 (−0.003..+0.002) |
| + May patch                            | 121   | 0.593    | +0.007 (+0.004..+0.010) |
| + before Season 3                      | 141   | 0.593    | +0.006 (+0.003..+0.009) |

Games from before a patch cost nothing that can be measured compared with the
same number of current games (the differences are within half a point of zero,
their intervals within a point and a half); adding them to the current games
gains about two thirds of a point. More games is what the model is short of:

| training games (all groups pooled) | openings | accuracy |
| ---------------------------------- | -------- | -------- |
| 1                                  | 16       | 0.472    |
| 2                                  | 32       | 0.502    |
| 5                                  | 80       | 0.533    |
| 10                                 | 160      | 0.550    |
| 20                                 | 320      | 0.565    |
| 40                                 | 640      | 0.579    |
| 80                                 | 1,280    | 0.587    |
| 141                                | 2,256    | 0.592    |

### Limits

- **Small sample, one map.** 142 games; groups of 11 to 62. A shift in
  first-factory shares below a distance of about 0.08 to 0.10 (the shuffled
  95th percentile) would not be seen, nor would a shift of under a point of
  accuracy. Per start position there are 19 to 65 openings per group, and 10
  to 12 in the July group.
- **Time and patch are not separated.** "Before Season 3" differs from the
  newest group by ten months and by four patches that change openings. Lobby
  options are tied to time too: `shieldsrework` exists only in the oldest
  group.
- **The Season 3 era itself is not sampled**, and the July group has 11 games.
- **Orders, not builds.** We see what was ordered and in which order. A patch
  that makes the same opening finish sooner is invisible here.
- **A frequency model on little data.** The accuracy curve is still rising at
  141 games, so more data of any age helps. With thousands of games the curve
  flattens and the small cost of old games may then outweigh the gain. Repeat
  the measurement on the full dataset: `python -m reason8.opening_shift` reads
  whatever is parsed.
- **Legion** has 62 openings in the sample: nothing can be said about it.
- "Changes openings" in the patch list is a reading of patch notes.

## Unit names across versions

Every parsed replay carries the game's unit names (`unitdefs`). Compared over
the 93 builds in `data/parsed` (29036 to 32018; all maps), separately for
games without Legion (78 builds) and with it (25 builds; about 240 more
names):

- **No unit was renamed.** 580 → 593 names without Legion, 818 → 837 with.
- **Added:** hats and other cosmetics (16), decoy-commander levels (12, or 18
  with Legion), three test or helper units, one Legion building
  (`legavantinuke`). None is ordered in an opening.
- **Removed:** 14 factory and constructor variants (`armsaap`, `corsalab`, …;
  never ordered in the sample), `chip`, three hats, and **`legmext15`**,
  Legion's T1.5 metal extractor (removed by the August patch according to the
  changelog; its definition disappears between builds 31368 and 31691). It is
  the only changed name that appears in openings: 7 of the 45 Legion openings
  ordered it, 0.5% of all openings.
- **Build command ids are not stable.** A unit's command id is its index in
  `unitdefs`, and that index differs between the first and the last build for
  562 of the 580 names. Unit identity is the name; the parser already resolves
  ids with each replay's own table.

`reason8.game_versions` has the helpers: `unit_name_changes()` (added and
removed names between two versions), `UNIT_RENAMES` and `current_unit_name()`
(empty today), and `playable_units()` (an opening in today's names, or `None`
if it uses a unit that is gone).

## What a cutoff would cost

Slice-quality games (182-day slice, 2026-05-23 to 11-22) left by a hard cutoff
at each patch that changes openings, and how fast games come back after a
patch (Supreme Isthmus):

| cut at                         | Isthmus | Glitters | Rosetta | Isthmus games after 1 / 3 / 7 / 14 / 28 days |
| ------------------------------ | ------- | -------- | ------- | -------------------------------------------- |
| no cut                         | 22,200  | 19,793   | 1,138   |                                              |
| May patch (30236)              | 21,044  | 18,976   | 1,108   | 140 / 504 / 1,142 / 2,033 / 3,942            |
| July patch (30755)             | 13,457  | 12,364   | 657     | 100 / 353 / 801 / 1,574 / 3,204              |
| August patch (31075)           | 9,624   | 8,538    | 370     | 109 / 341 / 805 / 1,587 / 3,209              |
| air constructors patch (31357) | 6,754   | 5,892    | 257     | 83 / 320 / 763 / 1,549 / 3,139               |

(The slice counts differ slightly from [`dataset.md`](dataset.md), which takes
the median skill of its own window.) Cutting at the last patch that changes
openings keeps 30% of the Isthmus slice and 23% of Rosetta. Isthmus and
Glitters each regain about 100 games a day (1,600 openings, 100 per start
position), Rosetta 2 to 4.

## Routine after a patch

The decisions behind this routine are in
[ADR 0012](adr/0012-keep-the-time-window-across-balance-patches.md).

1. **Register the patch.** When `changelog.md` gets balance entries, add the
   patch to `BALANCE_PATCHES`: its first build is the first "Release …" pull
   request into `stable` that contains the patch's merge commit. Mark whether
   it changes openings.
2. **Check unit names.** Parse one replay from before and one from after the
   patch with the same factions enabled and run `unit_name_changes()` on their
   `unitdefs`. Add renames to `UNIT_RENAMES`. Removed units need nothing:
   openings that use them are dropped when the dataset is built.
3. **Wait three days, then measure.** By then Isthmus has 320 to 560 new
   slice-quality games (5,000 to 9,000 openings). Download and parse them and
   compare the current model's next-unit accuracy on games after the patch
   with its accuracy on held-out games from before it. On 62 test games the
   interval of such a difference was ±0.4 to ±0.9 points; on 300 it should be
   about half of that.
4. **If accuracy on the new games is lower by 2 points or more** (interval
   clear of zero), the patch moved openings. Keep the old model in use (it
   warns, see below), and retrain with `select_matches(min_build=<patch>)`
   once a week of games is in: about 800 to 1,100 games per big map, as many
   openings per start position. Rosetta gets 12 to 71 games in a week, so it
   keeps its older games and gets the patch era as a feature instead.
5. **Otherwise retrain on schedule.** Rebuild the dataset on the moved 182-day
   window and retrain once a month, whether or not there was a patch. This is
   what happened across every patch measured here.

The 2-point threshold is a first choice, well above anything a year of patches
cost in the measurement above; revise it when the first real model exists.

## The version a model was trained on

A model is saved with a `TrainedOn` record: the first and last build of its
training games and every unit name it can output
(`TrainedOn.from_training_data()`, `to_json()`). Before the model is used in a
game, `check_game_version()` compares the record with the running game's
version and unit names, and `ensure_compatible()` turns the result into a
warning or an error:

refuse
: the model can order a unit that the game (with the factions it has loaded)
  does not have; or the game is more than 3,000 builds from the training
  games, further than the 12 months measured here

warn
: a patch that changes openings was released after the last training game; or
  the game is more than 260 builds (about a month) newer than the last
  training game; or the game is older than the training games; or its version
  is not a release

ok
: everything else

## Reproducing

```sh
uv run python -m reason8.opening_shift --list   # the sample's replay files
uv run python -m reason8.opening_shift          # every table above
```

Both read the match dumps and `data/parsed/`. The replay files of the sample
are the slice-quality Isthmus games that are parsed locally; with more parsed
replays the same command measures a bigger sample. The cutoff counts are
`select_matches(maps=[…], since=…, until=…, min_avg_skill=…, min_build=…)`.
