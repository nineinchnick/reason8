# Evaluating the bot in the game

How the Reason8 AI is judged where it matters, in games: the harness that
plays them, the measures of
[ADR 0003](../decisions/0003-define-success-as-in-game-measures.md), the A/A
test that sets how many games a comparison needs, the first comparison with
stock BARb, and what the games cost. Code: `reason8/evaluation/`.

## Running it

```sh
# once: the AI with the current openings (reason8 bot export), in a copy of the engine
uv run reason8 bot build --data-dir data/bar \
    --game "Beyond All Reason test-32018-ad135b9" \
    --engine-copy data/bar/engine-variants/reason8

# Reason8 against stock BARb: 30 seeds, two games each, 7 games at a time
uv run reason8 eval games --data-dir data/bar \
    --game "Beyond All Reason test-32018-ad135b9" \
    --engine-dir data/bar/engine-variants/reason8 \
    --seeds 30 --jobs 7 --out data/eval/reason8-vs-barb
uv run reason8 eval report data/eval/reason8-vs-barb

# the A/A test: stock BARb against itself, the same way
uv run reason8 eval games ... --ai BARb --out data/eval/barb-vs-barb
```

A game that has a `result.json` is not played again, so an interrupted run can
be repeated with the same command. Each game keeps its start script, engine
log, replay (`run/demos/`) and state file.

## How a comparison works

Game
: Two teams of eight AIs on Supreme Isthmus, every team on its recommended
  start position (`reason8 bot game`), 8.5 minutes of game time. The first
  ally team plays Armada, the second Cortex.

Pairs
: Every seed is played twice. In game `a` the evaluated AI (`--ai`) is the
  first ally team and the opponent (`--opponent`, stock BARb) the second; in
  game `b` they swap. So each AI plays every position once per seed, with the
  same faction, and the two games of a seed give 16 pairs: the evaluated AI's
  team and the opponent's team on the same spot. BARb seeds its own random
  numbers from the clock, so the two games differ in more than the AI; the A/A
  test measures how much.

Measures
: The host spectates with the state export widget, which records every team's
  resources and units every 5 game seconds and every hit between the sides
  (`reason8 headless run --snapshots`). A team's opening ends at its first
  contact, the first time a unit of it other than a scout is hit by the enemy
  ([ADR 0012](../decisions/0012-end-openings-at-first-contact.md)), or after
  the 8-minute opening window. At the last snapshot before that the harness
  takes its metal and energy income, the metal and energy cost of its finished
  units (`built_metal`, `built_energy`: the value of what it has built) and
  the number of finished units.

Report
: For each measure, the evaluated AI's total over the pairs as a share of the
  opponent's (100% is equal), with a 95% interval from resampling seeds (the
  16 pairs of a seed share two games). ADR 0003 asks for the economy at first
  contact to be at least BARb's.

## The A/A test

Stock BARb against itself, 30 seeds, 60 games, all of them played to the end.

| measure       | first BARb | second BARb | share                 | seeds for 10% |
| ------------- | ---------- | ----------- | --------------------- | ------------- |
| metal income  | 10.8       | 10.9        | 98.8% (96.6%–101.4%)  | 5             |
| energy income | 160.5      | 163.7       | 98.0% (94.4%–101.8%)  | 11            |
| built metal   | 4844.4     | 4838.7      | 100.1% (98.1%–102.0%) | 3             |
| built energy  | 43932.8    | 43839.3     | 100.2% (97.8%–102.6%) | 4             |
| units         | 22.9       | 23.0        | 99.5% (95.8%–103.5%)  | 11            |

- **No measure moves on its own.** Every interval covers 100%.
- **A few seeds find a 10% difference.** `seeds for 10%` is how many seeds
  find a true 10% difference 95% of the time with 80% power, from the spread
  of the per-seed shares: 3 for built metal, up to 11 for energy income and
  units. Sixteen pairs per seed average out most of the noise of a single
  team, which is why it takes fewer seeds than the 28 pairs Apex needed for
  the metal produced by minute 16
  ([`related-work.md`](../research/related-work.md)).
- **30 seeds** (60 games) narrow the built-metal interval to about ±2%, and
  are the default.
- 99.5% of the teams met the enemy before the end, at a median of 3:31 and
  3:34.

## Reason8 against stock BARb

The openings of `reason8 bot export` (the 4-gram's most typical human opening
of each position, [`results.md`](../results.md#using-it-in-the-game)), 30
seeds, 60 games, all played to the end.

| measure       | Reason8 | BARb    | share                  |
| ------------- | ------- | ------- | ---------------------- |
| metal income  | 8.8     | 10.9    | 81.0% (78.8%–83.5%)    |
| energy income | 252.1   | 167.3   | 150.6% (144.8%–157.5%) |
| built metal   | 4904.4  | 5113.5  | 95.9% (93.9%–97.9%)    |
| built energy  | 42879.4 | 46462.5 | 92.3% (89.9%–94.7%)    |
| units         | 27.1    | 24.8    | 109.5% (105.3%–113.9%) |

Built metal by position, Reason8's share of BARb's:

| faction | position | Reason8 | BARb | share                  |
| ------- | -------- | ------- | ---- | ---------------------- |
| Armada  | P1       | 6461    | 7924 | 81.5% (75.5%–89.5%)    |
| Armada  | P2       | 6242    | 6200 | 100.7% (91.4%–109.8%)  |
| Armada  | P3       | 5833    | 4435 | 131.5% (120.2%–141.9%) |
| Armada  | P4       | 4805    | 6779 | 70.9% (66.2%–76.5%)    |
| Armada  | P5       | 4150    | 4396 | 94.4% (84.7%–103.4%)   |
| Armada  | P6       | 4815    | 4062 | 118.5% (112.2%–125.3%) |
| Armada  | P7       | 4939    | 4596 | 107.5% (99.0%–115.8%)  |
| Armada  | P8       | 5473    | 5507 | 99.4% (90.6%–109.1%)   |
| Cortex  | P9       | 4882    | 4959 | 98.4% (90.8%–106.4%)   |
| Cortex  | P10      | 4423    | 5548 | 79.7% (73.4%–86.9%)    |
| Cortex  | P11      | 3988    | 5661 | 70.4% (66.1%–75.0%)    |
| Cortex  | P12      | 5459    | 4914 | 111.1% (103.8%–118.5%) |
| Cortex  | P13      | 4053    | 3995 | 101.4% (96.1%–107.0%)  |
| Cortex  | P14      | 3887    | 3599 | 108.0% (104.6%–111.7%) |
| Cortex  | P15      | 4887    | 4678 | 104.5% (94.1%–116.3%)  |
| Cortex  | P16      | 4174    | 4564 | 91.5% (83.8%–100.4%)   |

- **Not yet at BARb's economy.** At first contact Reason8 has built 96% of
  BARb's value in metal and 92% in energy, both intervals below 100%: the
  second measure of ADR 0003 is not met.
- **More energy, less metal.** Reason8 makes half again as much energy and a
  fifth less metal. The human openings it plays build long lines of wind and
  tidal generators before their extractors and factory, and the commander
  builds them alone (at most 30 structures, see
  [`in-game.md`](in-game.md#learned-openings-in-team-games)); BARb spreads the
  work over its constructors and builds extractors first.
- **Most extractors after the third are never built.** Scripts cannot see
  metal spots, so an extractor step takes BARb's own next task when that is an
  extractor ([`in-game.md`](in-game.md#how-the-hooks-work)), and after the
  first three BARb rarely offers one. Of the extractor steps in these games,
  all 1,050 of steps 1 to 3 were built, 157 of 347 of steps 4 to 8, and 108 of
  691 of steps 9 to 30; the rest were given up. That is most of the metal gap.
- **Sharing the structures with constructors does not help.** A version in
  which the first two constructors took structures from the commander's list
  (30 seeds, not merged) built 96.2% (94.3%–98.1%) of BARb's metal value: the
  same. The constructors meet the same refusal for extractors.
- **It depends on the position.** Reason8 is ahead at Armada `P3` (+31%), `P6`
  (+18%) and Cortex `P12`, `P14`, and behind at the pond (Armada `P4`, 71%:
  the 30 tidal generators come before the factory) and at Cortex `P10` and
  `P11` (70–80%).
- **Later contact.** 81% of Reason8's teams met the enemy before the end
  against 98% of BARb's, and later: a median of 4:01 against 3:31. So its
  measures come from later in the game, which favours it; the gap would be
  larger at a fixed minute.

## Extractors on the human's spots

The same comparison after extractors were given their own metal spot, the one
nearest to where the human built them, and structures were first placed where
the human placed them ([`in-game.md`](in-game.md#how-the-hooks-work)): 30
seeds, 60 games, all played to the end.

| measure       | Reason8 | BARb    | share                  |
| ------------- | ------- | ------- | ---------------------- |
| metal income  | 11.0    | 10.7    | 102.8% (99.6%–106.2%)  |
| energy income | 254.7   | 156.8   | 162.5% (155.3%–170.0%) |
| built metal   | 5020.7  | 4857.7  | 103.4% (101.0%–105.8%) |
| built energy  | 43669.8 | 43576.7 | 100.2% (97.9%–102.6%)  |
| units         | 27.8    | 22.6    | 122.9% (118.1%–127.5%) |

- **At first contact Reason8's economy is now at least BARb's.** Built metal
  is 103% of BARb's with the interval above 100%, built energy is equal, and
  metal income went from 81% to 103%: the second measure of ADR 0003 is met.
- **Steps are no longer given up.** 157 steps were skipped in the 60 games, 63
  of them extractors, against 865 and 773 before; 2,438 extractors were built
  on the spot chosen for them.
- **Two positions still lag:** Cortex `P11` at 70% (69.5%, 65.3%–73.9%) and
  Armada `P5` at 88% (82.1%–94.8%). The others are at or above BARb.
- **Contact still comes later.** 78% of Reason8's teams met the enemy before
  the end of the game, against 99.8% of BARb's, at a median of 4:13 against
  3:21. The measures come from each team's own contact, so Reason8's are taken
  later, which favours it; a comparison at a fixed minute would tell how much.

## At fixed minutes

Each team measured at its own first contact is what ADR 0003 asks for, but a
team that meets the enemy later is measured later.
`reason8 eval report --at-seconds` measures every team at the same game time
from the kept state files. The same 60 games with extractors on the human's
spots:

| at   | metal income         | energy income          | built metal         | built energy        | units               |
| ---- | -------------------- | ---------------------- | ------------------- | ------------------- | ------------------- |
| 3:00 | 94.0% (92.0%–96.1%)  | 122.2% (119.7%–124.7%) | 92.6% (91.9%–93.2%) | 93.0% (92.5%–93.6%) | 94.8% (93.9%–95.7%) |
| 4:00 | 83.1% (81.4%–84.6%)  | 116.5% (114.3%–118.9%) | 92.9% (92.1%–93.7%) | 90.8% (90.1%–91.5%) | 91.4% (90.4%–92.4%) |
| 5:00 | 83.2% (82.1%–84.3%)  | 119.9% (117.4%–122.7%) | 92.3% (91.4%–93.1%) | 89.0% (88.2%–89.9%) | 92.2% (90.8%–93.6%) |
| 7:00 | 98.0% (94.8%–101.2%) | 105.9% (103.0%–109.3%) | 92.3% (91.2%–93.4%) | 87.7% (86.7%–88.6%) | 95.1% (93.1%–96.9%) |

The A/A games at 4:00 give 100.2% (99.8%–100.7%) for built metal, so the
measure itself is fair.

Built metal at 4:00 by position:

| faction | position | Reason8 | BARb | share                  |
| ------- | -------- | ------- | ---- | ---------------------- |
| Armada  | P1       | 5448    | 4921 | 110.7% (108.2%–113.3%) |
| Armada  | P2       | 4124    | 4967 | 83.0% (80.6%–85.4%)    |
| Armada  | P3       | 3115    | 4710 | 66.1% (65.5%–66.8%)    |
| Armada  | P4       | 4242    | 5039 | 84.2% (81.3%–86.4%)    |
| Armada  | P5       | 4562    | 4942 | 92.3% (90.3%–94.4%)    |
| Armada  | P6       | 5235    | 4459 | 117.4% (114.9%–120.1%) |
| Armada  | P7       | 4429    | 5057 | 87.6% (86.2%–89.1%)    |
| Armada  | P8       | 5336    | 4821 | 110.7% (108.1%–113.4%) |
| Cortex  | P9       | 3913    | 4898 | 79.9% (77.3%–82.6%)    |
| Cortex  | P10      | 3668    | 4886 | 75.1% (73.5%–76.6%)    |
| Cortex  | P11      | 4102    | 4792 | 85.6% (83.6%–87.4%)    |
| Cortex  | P12      | 4122    | 5051 | 81.6% (78.8%–84.0%)    |
| Cortex  | P13      | 5114    | 4638 | 110.3% (108.1%–112.6%) |
| Cortex  | P14      | 5712    | 4271 | 133.7% (127.9%–140.7%) |
| Cortex  | P15      | 5022    | 4958 | 101.3% (99.3%–103.5%)  |
| Cortex  | P16      | 3686    | 4910 | 75.1% (73.4%–76.7%)    |

- **At the same minute Reason8 is behind.** From 3 to 7 minutes it has built
  about 92% of BARb's metal value and 88–93% of its energy value, with tight
  intervals. Its 103% at first contact comes from meeting the enemy almost a
  minute later.
- **More energy, less metal, still.** Energy income is 106–122% of BARb's and
  metal income 83–98%: the human openings put more into energy early.
- **The positions differ a lot.** Five are ahead (Armada `P1`, `P6`, `P8`,
  Cortex `P13`, `P14` by 10–34%); the tech positions (Armada `P3`, 66%) and
  Cortex `P9`, `P10`, `P16` (75–80%) are furthest behind.
- **First contact alone can be gamed.** An AI that is slower to meet the enemy
  gets measured later. A comparison should report both: at first contact, as
  ADR 0003 says, and at a fixed minute.

## What the games cost

Measured on the A/A run: 32 hardware threads, 56 GB of RAM for WSL, 7 games at
a time.

| per game                         | median | range       |
| -------------------------------- | ------ | ----------- |
| wall time (s)                    | 126    | 100–253     |
| loading (s)                      | 32     | 28–127      |
| simulation (s), 8.5 game minutes | 89     | 68–120      |
| speed (game minutes per minute)  | 5.7    | 4.3–7.5     |
| CPU time (s)                     | 155    | 119–294     |
| peak memory (MB)                 | 5,883  | 5,864–5,898 |
| state file (MB)                  | 2.0    | 2.0–2.2     |

- **Memory sets the pace.** A 16-AI game uses 1.2 cores and 5.9 GB, so 56 GB
  hold 7 to 8 games at a time while most of the 32 threads idle. The 60 games
  of a comparison took 21 minutes: about 175 games an hour.
- **The first games of a run load slowly** (up to 127 s, against 32 s later):
  seven engines read the same archives at once.
- **A game folder is 3.7 MB**, most of it the run's logs and the replay.

### When to use the cloud

The workloads ahead, per this machine:

Comparing a model with BARb
: 60 games, about 20 minutes. Local.

Re-simulating replays for the context sample
: a few thousand replays, played back with the same widget; their cost is in
  [`state-extraction.md`](../research/state-extraction.md). Local, or the
  cloud if it has to be faster.

Choosing between many models
: tens of comparisons, so thousands of games. This is where a cluster pays:
  the games are independent and need nothing but the engine, the game and the
  AI folder.

On a cloud machine the same rule holds: memory decides how many games fit, at
about 6 GB each, so a general-purpose instance with 4 GB per core runs about
one game per 1.5 cores, and one with 8 GB per core about one per core. One
game is about 2.6 CPU-minutes, so 1,000 games are about 45 core-hours. Move a
workload to the cloud when it would take this machine more than a night.

## Not covered

- Only Supreme Isthmus, and only Reason8 as Armada on the first ally team and
  Cortex on the second; Legion and the other maps are not played.
- The first measure of ADR 0003, a classifier that tells the bot's openings
  from human ones, is not built yet.
- Win rate: the games end after 8.5 minutes.
- A run in the cloud: the numbers above are for this machine only.
