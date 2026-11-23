# First contact: where an opening ends

An opening can only be told apart from the rest of the game until the player
meets the enemy. After that, build orders answer raids and losses, and the
replay's commands do not show what they answer. This document measures when
players meet the enemy, per map and start position, on replays played again
headlessly. The decision that follows from it is
[ADR 0012](../decisions/0012-end-openings-at-first-contact.md): an opening
ends at the player's first contact. Code: `reason8/openings/contact.py`,
`reason8 headless batch` and the state export widget
([`state-extraction.md`](state-extraction.md)).

```sh
# play the first 12 game minutes of a list of replays, 4 engines at once
uv run reason8 headless batch --data-dir data/bar --out-dir data/state \
    --jobs 4 --max-frame 21600 --list replays.txt
uv run reason8 contact             # data/state -> data/contact/first_contact.parquet
uv run reason8 contact --report    # the tables below
```

## Summary

- **Sample:** the first 12 minutes of 72 games of the slice, 24 per map, 1,152
  players, played again headlessly with no desync.
- **First contact** is the first time a unit of the player other than a scout
  is damaged by an enemy unit. Its median is 4:08 on All That Glitters, 3:20
  on Rosetta and 4:40 on Supreme Isthmus; 87%, 90% and 76% of the players have
  it within 8 minutes.
- **A third to almost half of an 8-minute opening comes after it:** 33%, 44%
  and 31% of the build orders of the first 8 minutes.
- **It depends on the position.** Front positions meet the enemy after 2 to
  4.5 minutes (the two positions on the isthmus of Supreme Isthmus after 2:05;
  its two pond positions, also called front, after 7:23), air positions after
  4 to 5 minutes, sea positions after 4 to 4.5. Tech positions mostly do not
  within 8 minutes: 29% do on Glitters and 22% on Isthmus. Within a front
  position the middle half of the players is about 1 to 1.5 minutes apart.
- **A side** is in contact after about 2 minutes (1:50 to 2:23): somebody's
  raider has been shot at.
- **The definition matters by about a minute.** Counting hits given and scouts
  moves the median 45 to 70 seconds earlier; waiting for the first unit lost
  or for 500 damage moves it 30 to 65 seconds later. Leaving out commanders
  shooting at each other changes nothing.
- **Cutoffs for games that were not re-simulated:** the median of the map and
  position keeps 53 to 70% of the window's orders; 8 to 11% of what it keeps
  was ordered after the player's own contact, and it drops 8 to 16% of what
  was ordered before.

## Method

**The sample.** 72 games of the training slice
([`dataset.md`](../reference/dataset.md)): for each of the three maps and each
of the engines 2025.06.24, 2026.06.12, 2026.07.04 and 2026.09.03, six games
drawn at random from the replays that are downloaded, parsed and used by the
opening dataset, from at most three game versions per map and engine to limit
the downloads. Each game was played from its replay for 12 game minutes (frame
21,600) or to its end, with the exact engine and game version it was recorded
on (28 game versions). No run had a desync warning. With four engines at once
a game took 150 s of wall time and 160 s of CPU time on average, and at most
5.7 GB of RAM.

| map                      | games | players | attacker known | attacker guessed |
| ------------------------ | ----- | ------- | -------------- | ---------------- |
| All That Glitters v2.2.3 | 24    | 384     | 18             | 6                |
| Rosetta 1.4.4            | 24    | 384     | 17             | 7                |
| Supreme Isthmus v2.1     | 24    | 384     | 17             | 7                |

Played for 10:26 to 12:00 of game time (median 12:00).

**What is recorded.** The state export widget writes a `hit` line the first
time a unit is damaged by a given enemy player, with both units' types, and
the damage between every pair of enemy players summed per second. Units
destroyed were already recorded with the destroying team. Damage from or to
the neutral team does not count, and neither does damage that has no attacker
(wreckage, fire, collisions) where the attacker is known.

**Who did the damage.** The engine knows the attacker, but BAR's widget
handler does not pass it on to widgets. The state files measured here were
written by an earlier version of the widget: in game versions up to autumn
2026 it wrapped the handler and read the attacker (52 of the 72 games); later
versions don't allow that, and it put the damage down to the nearest enemy
unit within 1,300 map units instead (20 games: all 18 on engine 2026.09.03 and
2 on 2026.07.04, game versions from `test-31820`). The two ways are compared
[below](#known-attacker-against-nearest-enemy). The widget now asks the engine
(`Spring.GetUnitLastAttacker`, see
[`state-extraction.md`](state-extraction.md)), which works in every version;
re-running those 20 games with it removes the guess.

**A player** is one of the 16 players of a game (a team, to the engine); a
**side** is one of the two ally teams. A player's **position** is the
recommended start position they took
([ADR 0011](../decisions/0011-take-positions-from-the-map-metadata.md)). The
two sides of a map mirror each other, so a position is taken together with the
position at the same place in the other side's list (`P1` with `P9`, and so
on), which doubles the players per row.

**Times** are game time, as minutes:seconds. "None" means the quantile was not
reached while the games were played: fewer players than that had contact in 12
minutes. The quartiles show the spread: the middle half of the players lies
between the lower and the upper one.

## Definitions of contact

Six ways of saying when a player first met the enemy
(`reason8.openings.contact.MEASURES`):

`any_hit`
: A unit of the player is hit by an enemy unit, or hits one.

`hit_with_scouts`
: A unit of the player is hit by an enemy unit.

`hit`
: A unit of the player other than a scout is hit by an enemy unit. **This is
  the first contact the dataset uses.**

`hit_without_duels`
: The same, not counting a commander hit by a commander.

`loss`
: A unit of the player other than a scout is destroyed by an enemy unit.

`damage`
: Enemy units have done 500 damage to the player's units, about the health of
  two light bots.

Scouts are the units built to look, not to fight: Tick, Rover, Rascal,
Wheelie, the air scouts Blink and Finch, and Legion's Noctua and scout boat.

### All That Glitters v2.2.3

| first contact       | players | lower quartile | median | upper quartile | contact in 8 min | orders after contact |
| ------------------- | ------- | -------------- | ------ | -------------- | ---------------- | -------------------- |
| `any_hit`           | 384     | 2:27           | 3:16   | 4:13           | 91%              | 43%                  |
| `hit_with_scouts`   | 384     | 2:36           | 3:34   | 4:44           | 88%              | 39%                  |
| `hit`               | 384     | 3:16           | 4:08   | 5:11           | 87%              | 33%                  |
| `hit_without_duels` | 384     | 3:16           | 4:08   | 5:11           | 87%              | 33%                  |
| `loss`              | 384     | 3:49           | 4:49   | 7:04           | 80%              | 26%                  |
| `damage`            | 384     | 3:52           | 4:37   | 6:00           | 81%              | 27%                  |

### Rosetta 1.4.4

| first contact       | players | lower quartile | median | upper quartile | contact in 8 min | orders after contact |
| ------------------- | ------- | -------------- | ------ | -------------- | ---------------- | -------------------- |
| `any_hit`           | 384     | 2:06           | 2:33   | 3:15           | 95%              | 54%                  |
| `hit_with_scouts`   | 384     | 2:11           | 2:43   | 3:37           | 92%              | 51%                  |
| `hit`               | 384     | 2:31           | 3:20   | 4:37           | 90%              | 44%                  |
| `hit_without_duels` | 384     | 2:31           | 3:20   | 4:37           | 90%              | 44%                  |
| `loss`              | 384     | 3:06           | 4:12   | 6:20           | 81%              | 36%                  |
| `damage`            | 384     | 3:11           | 4:01   | 5:38           | 84%              | 36%                  |

### Supreme Isthmus v2.1

| first contact       | players | lower quartile | median | upper quartile | contact in 8 min | orders after contact |
| ------------------- | ------- | -------------- | ------ | -------------- | ---------------- | -------------------- |
| `any_hit`           | 384     | 2:11           | 3:33   | 6:23           | 83%              | 41%                  |
| `hit_with_scouts`   | 384     | 2:25           | 4:04   | 7:18           | 79%              | 37%                  |
| `hit`               | 384     | 2:51           | 4:40   | 7:52           | 76%              | 31%                  |
| `hit_without_duels` | 384     | 2:51           | 4:40   | 7:52           | 76%              | 31%                  |
| `loss`              | 384     | 3:36           | 5:46   | 10:16          | 65%              | 23%                  |
| `damage`            | 384     | 3:24           | 5:26   | 9:11           | 69%              | 26%                  |

Why `hit`:

- **Scouts on the player's side do not count.** For 307 of the 1,152 players
  the very first hit they take is on their own scout. A scout that is shot has
  done its job; its owner loses next to nothing and has nothing to answer. Air
  positions show it best: their scouts are shot at long before anything else
  of theirs is, and counting scouts would end their openings 0.8 to 1.5
  minutes earlier.
- **Scouts on the enemy's side do count.** In 20% of the first contacts the
  attacker is a scout, mostly a Tick shooting at a light bot, a metal
  extractor or a builder. That is a raid on the player, however small.
- **Hits taken, not hits given.** What a player's units are hit by is what
  they have to answer. A player who attacks is hit back within seconds, so
  hits given add little: `any_hit` differs from `hit_with_scouts` by 10 to 30
  seconds.
- **Commander duels need no rule.** Of 1,072 first contacts, 32 are hits on
  the commander and 4 are a commander hit by a commander: `hit_without_duels`
  gives the same times.
- **The first loss and the damage threshold come later**, 30 to 65 seconds in
  the median. They are surer signs of a fight, but in between the player is
  already under fire.

The first unit hit is most often one of the player's own first light bots on
its way to the enemy (`corak` and `armpw`: 273 of the 1,072 first contacts),
then resurrection bots, metal extractors and `corbw` drones. So first contact
is mostly the player's first units meeting the enemy's, not a raid on the
base.

## Sides

The first contact of a side is the earliest first contact of its eight
players.

| map                      | sides | lower quartile | median | upper quartile |
| ------------------------ | ----- | -------------- | ------ | -------------- |
| All That Glitters v2.2.3 | 48    | 2:05           | 2:23   | 3:04           |
| Rosetta 1.4.4            | 48    | 1:57           | 2:05   | 2:15           |
| Supreme Isthmus v2.1     | 48    | 1:37           | 1:50   | 2:06           |

## Per map and position

First contact (`hit`) per map and position. "Orders after contact" is the
share of the build orders of the first 8 minutes that the players of the
position gave after their own first contact. "Cutoff" is the median, rounded
down to 5 seconds and capped at 8 minutes: where the dataset ends an opening
of that position in a game that was not re-simulated.

### All That Glitters v2.2.3

| positions | role  | players | lower quartile | median | upper quartile | contact in 8 min | orders after contact | cutoff |
| --------- | ----- | ------- | -------------- | ------ | -------------- | ---------------- | -------------------- | ------ |
| P1, P9    | front | 48      | 3:19           | 4:14   | 4:58           | 96%              | 34%                  | 4:10   |
| P2, P10   | air   | 49      | 4:08           | 5:01   | 7:55           | 76%              | 25%                  | 5:00   |
| P3, P11   | tech  | 48      | 7:26           | none   | none           | 29%              | 5%                   | 8:00   |
| P4, P12   | front | 45      | 3:53           | 4:35   | 5:04           | 98%              | 26%                  | 4:35   |
| P5, P13   | front | 49      | 2:39           | 3:17   | 4:14           | 100%             | 47%                  | 3:15   |
| P6, P14   | front | 46      | 2:59           | 3:45   | 4:30           | 100%             | 45%                  | 3:45   |
| P7, P15   | front | 50      | 3:16           | 3:54   | 4:17           | 100%             | 38%                  | 3:50   |
| P8, P16   | front | 49      | 2:43           | 3:27   | 3:54           | 98%              | 45%                  | 3:25   |

### Rosetta 1.4.4

| positions | role       | players | lower quartile | median | upper quartile | contact in 8 min | orders after contact | cutoff |
| --------- | ---------- | ------- | -------------- | ------ | -------------- | ---------------- | -------------------- | ------ |
| P1, P9    | front      | 47      | 2:19           | 2:57   | 3:44           | 100%             | 51%                  | 2:55   |
| P2, P10   | front/tech | 47      | 3:37           | 6:28   | 9:43           | 66%              | 25%                  | 6:25   |
| P3, P11   | front      | 48      | 2:15           | 2:55   | 4:00           | 100%             | 49%                  | 2:55   |
| P4, P12   | front      | 48      | 2:32           | 2:47   | 3:30           | 100%             | 57%                  | 2:45   |
| P5, P13   | air        | 48      | 2:56           | 3:53   | 6:01           | 90%              | 39%                  | 3:50   |
| P6, P14   | front      | 51      | 2:16           | 2:53   | 3:47           | 98%              | 55%                  | 2:50   |
| P7, P15   | front/tech | 48      | 3:16           | 6:39   | 10:48          | 62%              | 25%                  | 6:35   |
| P8, P16   | front      | 47      | 2:26           | 3:02   | 3:42           | 100%             | 51%                  | 3:00   |

### Supreme Isthmus v2.1

| positions | role       | players | lower quartile | median | upper quartile | contact in 8 min | orders after contact | cutoff |
| --------- | ---------- | ------- | -------------- | ------ | -------------- | ---------------- | -------------------- | ------ |
| P1, P9    | sea        | 46      | 3:28           | 4:04   | 5:31           | 96%              | 45%                  | 4:00   |
| P2, P10   | tech       | 49      | 8:06           | 11:20  | none           | 22%              | 6%                   | 8:00   |
| P3, P11   | air        | 47      | 3:29           | 4:59   | 6:11           | 89%              | 39%                  | 4:55   |
| P4, P12   | front      | 50      | 5:40           | 7:23   | 10:16          | 60%              | 10%                  | 7:20   |
| P5, P13   | front      | 49      | 1:44           | 2:05   | 2:25           | 100%             | 61%                  | 2:05   |
| P6, P14   | front      | 48      | 1:47           | 2:06   | 2:38           | 98%              | 66%                  | 2:05   |
| P7, P15   | front/tech | 47      | 5:34           | 8:01   | 11:00          | 49%              | 17%                  | 8:00   |
| P8, P16   | sea        | 48      | 3:55           | 4:29   | 5:08           | 94%              | 36%                  | 4:25   |

## Cutoffs for games that were not re-simulated

Only re-simulated games have a measured contact. For the others an opening
ends at one time per map and position, a quantile of the measured first
contacts of that position. A low quantile keeps few orders given after contact
and drops many given before it; a high one the other way round. Measured on
the sample itself, against each player's own first contact:

| quantile | map                      | orders kept | of them after contact | orders before contact | of them dropped |
| -------- | ------------------------ | ----------- | --------------------- | --------------------- | --------------- |
| 0.25     | All That Glitters v2.2.3 | 56%         | 4%                    | 67%                   | 19%             |
| 0.25     | Rosetta 1.4.4            | 39%         | 2%                    | 56%                   | 33%             |
| 0.25     | Supreme Isthmus v2.1     | 59%         | 5%                    | 69%                   | 20%             |
| 0.50     | All That Glitters v2.2.3 | 66%         | 8%                    | 67%                   | 9%              |
| 0.50     | Rosetta 1.4.4            | 53%         | 11%                   | 56%                   | 16%             |
| 0.50     | Supreme Isthmus v2.1     | 70%         | 8%                    | 69%                   | 8%              |
| 0.75     | All That Glitters v2.2.3 | 76%         | 14%                   | 67%                   | 3%              |
| 0.75     | Rosetta 1.4.4            | 69%         | 21%                   | 56%                   | 4%              |
| 0.75     | Supreme Isthmus v2.1     | 78%         | 13%                   | 69%                   | 2%              |

"Orders kept" is the share of the build orders of the first 8 minutes that the
cutoff keeps, "of them after contact" the share of those that the player gave
after their own first contact, "orders before contact" the share of the
8-minute orders given before it, and "of them dropped" the share of those that
the cutoff drops.

The dataset uses the **median** (`reason8.openings.contact.CUTOFF_QUANTILE`):
it keeps about as many orders as were given before contact, and what it keeps
is 89 to 92% from before contact. The lower quartile would bring that to 95 to
98% and drop 19 to 33% of the orders given before contact.

The cutoffs are a table in the code (`POSITION_CUTOFF_SECONDS`), printed by
`reason8 contact --report` and pasted there. With 45 to 51 players per
position they are not exact: resampling the games gives 95% intervals that are
46 seconds wide in the median, and up to 3.5 minutes wide for the front/tech
positions of Rosetta, where players differ most.

## Known attacker against nearest enemy

In 20 of the 72 games the widget could not read the attacker and put the
damage down to the nearest enemy unit. To see what that does, 8 games with a
known attacker (three on Glitters, two on Rosetta, three on Isthmus; engines
2025.06.24, 2026.06.12 and 2026.07.04) were played a second time with the
widget told to guess (`Reason8DamageAttacker = 0`), and the first contacts of
their 128 players compared:

- 121 players have a first contact (`hit`) both ways and 7 have none either
  way. Nobody has one only one way.
- For 114 of the 121 it is the same frame. For 7 the guess is earlier, by 23
  seconds to 9 minutes: damage that nobody aimed (wreckage, fire, a teammate's
  shot) while an enemy unit, usually a scout, was within range. The guess is
  never later.
- Units lost are the same both ways (the engine names the destroyer). The
  damage sums are not: with the guess they are 6% to three times higher,
  because damage without an attacker is counted.

So in the games with a guessed attacker about 6% of the first contacts are too
early. Those games are a quarter of the sample, which makes the medians of
this document early by a few seconds at most.

## What else the state files hold

The same runs wrote, for every game, what a model of the decisions after the
opening will need as context. None of it is used yet.

Wind
: The wind strength at every snapshot (every 5 game seconds), and the map's
  minimum and maximum wind and tidal strength in the header. The wind changes
  all the time and decides what a wind turbine is worth at that moment.

Economy
: Per player and snapshot: metal and energy stored, storage, income and
  expense.

Units
: Per snapshot every unit with its type, owner, position, health and build
  progress.

Placement
: Every unit created, with its position and the unit that builds it, and when
  it was finished: what was really built and where, not only what was ordered.

Fighting
: Every unit destroyed with the destroying team, every first hit between two
  enemy units, and the damage between every pair of enemy players per second.

A game's first 12 minutes are about 4 MB of JSON lines, 0.9 MB gzipped, in
`data/state/date=<day>/<replay name>.jsonl.gz`.

## Limits

- **A small sample.** 24 games per map and 45 to 51 players per position. It
  is enough to tell positions that meet the enemy after 2 minutes from those
  that do after 4 or not at all, and not enough for differences of half a
  minute.
- **Not a random sample of the slice.** The four engines have the same number
  of games, although 2026.07.04 has half of the slice and 2026.09.03 a small
  part; the games come from at most three game versions per map and engine, 28
  in all; and they come from the replays downloaded and parsed so far. Contact
  times per engine were not compared.
- **Contact is damage.** A player who has seen the enemy, or whose teammate
  called for help, counts as not yet in contact. What each player could see is
  not recorded yet ([`state-extraction.md`](state-extraction.md)).
- **One definition for every role.** For a front player the first hit on a
  raider is the start of the fight. For an air player it may be one drone shot
  at over the enemy base, which changes little of what they build next: air
  positions are first hit after 4 to 5 minutes but lose their first unit other
  than a scout only after 8 to 9.5.
- **The guessed attacker** in 20 games (above).
- **Mirrored positions are taken together.** The maps are symmetric, but the
  two sides need not play the same; the sample is too small to check.
- **The cutoffs were judged on the games they were made from.** On other games
  they will fit a little worse than the table above says.
- **Twelve minutes.** A first contact later than that is "none". The dataset
  only needs the first 8.
- **Start positions.** For 50 of the 1,152 players the first unit appeared
  more than 50 map units from the start position the parsed replay gives.
  Their position, and so their row in the tables, may be wrong. Why the two
  differ is not looked into here.
- **Skill.** The sample is not split by skill; better players may raid
  earlier.
