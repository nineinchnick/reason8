# Related work: Apex, and what Reason8 takes from it

These notes build on [`barb.md`](barb.md), which explains how stock BARb
works; read that first.

Everything here comes from **reading** these sources. Nothing was run for this
document; two of Apex's observations about BARb were tried later and are
marked below.

- **Apex:** [apexearth/bar-ai](https://github.com/apexearth/bar-ai) at commit
  [`927ff16c`][head] (2026-11-18, release v0.5.17). 3,349 commits since
  2026-07-27.
- **Apex's C++:** its `cpp/` folder, compared with the commit it forked
  CircuitAI from,
  [`0ef36267`](https://github.com/rlcevg/CircuitAI/commit/0ef36267633d6c1b2f6408a8d8a59fff38745dc3)
  (2025-12-16).
- **Stock BARb:** Apex's own snapshot in [`reference/barb-stable/`][ref]
  (taken 2026-07-27). It differs in a few files from the BARb that ships with
  engine `recoil_2026.09.03`, so line counts below are for the snapshot.

Statements marked *(inferred)* are our conclusions, not something Apex's docs
or commits say outright.

## TL;DR

- **Apex kept BARb's body and replaced its decisions.** Pathing, placement,
  threat maps and unit orders are still CircuitAI. What to build, where, and
  what each factory makes is now one priced "market" written in AngelScript.
  The script grew from about 550 lines (stock `hard` profile) to about
  115,000.
- **Its own army control lost to stock BARb, twice.** Both times the fix was
  to hand the army back to BARb's code. Its gains are in economy and
  production. *This supports our roadmap: leave army control with BARb.*
- **Learning from who won mostly failed.** Three training methods in a row
  were stopped because the signal was lost in noise. The one learned part that
  shipped predicts a narrow, directly observed outcome (will this build job
  survive?). *Imitation gives a label for every decision, which is exactly
  what those methods lacked.*
- **Apex already tried imitation, briefly.** [`tools/imitate.py`][imitate]
  learns BARb's building mix (37.7% accuracy against a 25.7% baseline) and has
  a `--human` mode that was run on one replay. Neither is switched on in the
  game. *The human-replay niche is still open.*
- **Its replay extraction is small and the idea is sound:** play the replay in
  `spring-headless` with a spectator widget that prints events. About 330
  lines in total. We should write our own version rather than copy it.
- **There is no licence on the repository**, so we read it for ideas and copy
  nothing.

## What Apex is

Apex is a Skirmish AI that started as a copy of BARb and is developed by one
experienced BAR player. Its README says most of the code is written with an AI
coding assistant, directed and play-tested by the owner. The goals in
[`docs/doctrine.md`][doctrine] put "fun to play against" first and "beat BARb
in more than 80% of even games" second; the README says the second goal has
not been reached yet.

Its central rule is that **every decision is a price**. There are no build
orders and no thresholds such as "go T2 at 20 metal income". The README calls
a hand-written threshold a bug.

## What Apex replaced in BARb, and why

`barb.md` lists six places where a model could hook into BARb, from editing
opener tables (1) to forking the C++ (6). Apex is option 6, and it also
rewrote everything behind options 1 to 5.

**What a builder does next**
: *Stock BARb (see `barb.md`):* Idle builder takes the best task from a shared
  pool, scored by travel cost and priority
: *Apex:* [`Market::Decide`][how]: about twenty "proposers" (extractor,
  energy, converter, factory, defence, reclaim...) each offer their best job;
  the builder takes the highest `gain / cost`, where cost includes metal,
  build time, the walk and the chance of dying on the way
: *Why (source):* The task pool and its rules were deleted on 2026-08-22
  ([`fcbabf2e`][c-kill], 37 script files, about 13,600 lines). First market
  prototype the same day ([`a5c2708f`][c-market])

**Economy rules** (`economy.json` energy limits, factory choice, factory switch timer)
: *Stock BARb (see `barb.md`):* C++ `EconomyManager` plus JSON tables
: *Apex:* Switched off inside the C++ ([`da745816`][c-strip]). Energy,
  factories and tech are ordinary jobs in the market
: *Why (source):* So that nothing can spend resources outside the market. A
  static check ([`tools/check.py`][check]) fails the build if any other code
  issues a build order

**Commander's first buildings**
: *Stock BARb (see `barb.md`):* Not a separate decision
: *Apex:* One choice per game between five plans: factory first, or 1, 2 or 3
  extractors first, or 2 extractors and a generator ([`opennet.as`][opennet])
: *Why (source):* The right order depends on the resource bonus, so it was
  made a recorded decision instead of a rule

**Factory openers**
: *Stock BARb (see `barb.md`):* 1–3 weighted role sequences per factory
: *Apex:* Table kept, but simplified. `armlab` went from several sequences
  (the first has weight 0.4) to two (0.9 and 0.1)
  ([`misc/commander.as`][commander])
: *Why (source):* Not stated

**Factory output after the opener**
: *Stock BARb (see `barb.md`):* Random draw from `factory.json` probability
  tiers
: *Apex:* [`Market::ConOrderFor`][how]: constructors up to a floor derived
  from income, then army units priced against the enemy army seen and each
  unit type's track record. `factory.json` "decides nothing"
: *Why (source):* Same pricing idea

**Defence**
: *Stock BARb (see `barb.md`):* `build_chain.json` lists per faction
: *Apex:* A "protect" job priced by how much it closes the worst open approach
  to the base; buildings snap to a grid
: *Why (source):* Same pricing idea

**Army control**
: *Stock BARb (see `barb.md`):* C++ fight tasks (attack, defend, raid, scout)
: *Apex:* **Stock BARb again.** Apex's own version was reverted on 2026-09-07
  ([`7a1a9895`][c-revert]) and switched off again in v0.2.7. The current
  default is `TUNE_STOCK_ARMY = 1`: BARb controls ground units, Apex's script
  only decides how the army is *used* (mass, raid, hold) and runs aircraft
: *Why (source):* Measured, see the next section

**Team play**
: *Stock BARb (see `barb.md`):* None
: *Apex:* A shared "team board": allies build one experimental factory
  together, share upgrades and constructors
: *Why (source):* Owner's direction. The README calls it experimental and not
  measured

**Neural nets**
: *Stock BARb (see `barb.md`):* None
: *Apex:* One small policy network scales the market's prices; see below

**Difficulty profiles**
: *Stock BARb (see `barb.md`):* `easy`, `medium`, `hard`, `hard_aggressive`
: *Apex:* One profile, `standard`

**Fairness**
: *Stock BARb (see `barb.md`):* Uses line of sight unless the `cheating`
  option is on
: *Apex:* Same

**Size of the change** (our count):

AngelScript, one profile
: *Stock BARb:* 544 lines in 7 files (`hard`), plus 500 shared
: *Apex:* about 114,900 lines in 212 files (`standard`)

JSON config, one profile folder
: *Stock BARb:* 5,103 lines (`hard`)
: *Apex:* 4,878 lines (`standard`)

C++ (`src/circuit`)
: *Stock BARb:* 301 files, about 53,900 lines
: *Apex:* 131 files changed, 7 added, about +26,600 / −2,100 lines

The largest C++ change is the file that exposes C++ functions to scripts
(`InitScript.cpp`, about +3,200 lines in Apex's fork). *So moving decisions
into AngelScript was not free: the scripts needed many new C++ bindings to see
enough of the game (inferred from the diff). That matches the warning in
`barb.md` about hook 5.*

### Three practical things we learned about BARb itself

These come from Apex's notes and affect hooks 1–4 in `barb.md`.

1. **A custom BARb variant needs its own short name, not just a version.** A
   multiplayer lobby does not send the AI version, so "BARb, version reason8"
   would load stock BARb. Apex copies the engine's `AI/Skirmish/BARb/stable/`
   folder to `AI/Skirmish/Apex/<version>/`, changes `AIInfo.lua`, and puts its
   `config/` and `script/` next to the library. When the game archive has no
   config for that name, CircuitAI falls back to those files
   ([`tools/deploy_ai.py`][deploy], header and the "archive-free play"
   comment). *This answers the open question in `barb.md` ("confirm a custom
   profile loads, and how") on paper, and it needs no C++ build: the stock
   library can be reused. We tried it and it works:
   [`in-game.md`](../reference/in-game.md).*
2. **BARb has hidden timers.** `behaviour.json` can give a unit a `since`,
   `cooldown` or `limit`. Apex found converters banned until 300 seconds and
   storage capped at one ([`docs/traps.md`][traps], S60). *A learned opening
   that orders such a unit earlier would be silently refused.*
3. **A script error fails silently.** If the AngelScript does not compile, the
   match still runs with near-stock behaviour (S3), and scripts and JSON are
   only read at start (S51). *Our PoC bot must check the log for script errors
   before trusting any result. When we tried it on stock BARb's library the
   outcome was worse than near-stock: the AI was removed and its team gave no
   orders at all, while the game ran on
   ([`in-game.md`](../reference/in-game.md)).*

## What its version history says

Apex writes down what each release measured, including changes that made it
worse: [`docs/versions.md`][versions], [`docs/old-versions.md`][oldversions],
the release tags, and one page per test batch under [`results/`][results].
Almost all tests are headless AI-vs-AI games against stock BARb or against
Apex's previous release.

### What worked

Giving the army back to stock BARb
: Head to head 0–3 became 3–0 over 12 games; the share of time an attack was
  under way went from 23% to 58% ([`7a1a9895`][c-revert]). Again in v0.2.7: 5
  wins, 2 draws, 1 loss against BARb, where Apex's own army layers on the same
  seeds scored 2–1–5

Pricing the early army and map share (candidates 5 and 7 of v0.2.7)
: 21–0–3 and 10–0–2 against the previous release on a small map

Basic defence of metal extractors (v0.3.7)
: 18–6 against v0.3.6

Extractor guards plus BARb's own fight settings (v0.5.06)
: Wins against BARb went from 6–5 to 9–1 over 24 paired games

A learned "will this build job fail?" model (on by default from v0.5.06)
: Constructors killed −40%, failed jobs −26%, wins 8 against 7 over 24 pairs
  ([`docs/tunables.md`][tunables], `TUNE_LEARNED_RISK`)

The latest release gate we found: v0.5.17 against BARb `hard`, 20 one-on-one
games on Comet Catcher with a +50% resource bonus and a 30-minute cap, won 4,
lost 0, and was ahead on income in 13 of the 16 games that hit the cap
([results page][r-v0517]). With no bonus the record is thinner: a 4-game batch
on 2026-11-13 reads 1 win, 1 loss, 2 ahead at the cap.

### What didn't work

Apex's own fight logic (fight estimates, focus fire with movement, counter-unit mix, keeping the commander home)
: Each was worse or made no difference; see the `cand-0.2.7-*` rows in
  [`old-versions.md`][oldversions]. One control run found the losses were not
  caused by those layers at all

"Personalities" (random play styles)
: 11–22% worse damage efficiency; off by default

Many small changes that each "worked"
: Twelve changes that each fired as designed took a head-to-head from 2–2 to
  0–8 ([`traps.md`][traps], Method)

Matching the owner's own economy
: The owner recorded reference games. Apex's economy stayed at about half of
  his curve; the gap is energy and build power from minute 2, not extractors
  ([`issues/eco-half-his-curve.md`][eco])

### What happened to the neural nets

The policy network reads a few dozen numbers about the game (36 of the 101
values Apex logs as its game state: incomes, army sizes on both sides,
threats, what is standing) plus each option's own numbers, and scales the
market's prices. With all weights at zero the hand-written prices play alone.
How to train it changed four times in five weeks:

to 2026-10-10
: *Method:* Regression on logged decisions ([`tools/nntrain.py`][nntrain])
: *Outcome:* Replaced

10-11 to 10-28
: *Method:* Random search: play random networks, re-test the winners
: *Outcome:* Stopped. The README says it "could not tell a good net from a
  lucky one"

10-28 to 10-29
: *Method:* Policy gradient: nudge every output a little, credit each nudge
  with how the position changed over the next 2 minutes ([`6bc00d15`][c-pg])
: *Outcome:* Stopped after 883 games: "no decision with detectable signal".
  Each nudge shared its reward with about 660 others. The network also drifted
  and had to be rolled back ([`913d0549`][c-guard])

from 10-29
: *Method:* Paired games: same map and seed, one setting leaned up and one
  down ([`5d1089d3`][c-lean])
: *Outcome:* We found no result reported

from 11-04
: *Method:* Follow every build job to its end and learn from what actually
  happened to it ([`4c783872`][c-ledger])
: *Outcome:* Produced the job-risk model above, the only learned part with a
  measured gain

Two cautions when reading Apex's net results. An A/A test (the same AI on both
arms) showed that detecting a 10% change in game score needs about 1,100
paired games, against 28 pairs for "metal produced by minute 16"
([`4c783872`][c-ledger]). And from 10-07 to 11-18 a lobby default silently
overrode the "nets off" setting in some comparisons
([`issues/modoption-overridden-by-lobby.md`][modopt]).

*What we take from this:*

- *Win or loss is a very weak teacher at the scale one person can simulate.
  Imitation gives a correct answer for every decision, so it should need far
  fewer games. This is the main argument for Reason8's approach, and it now
  has someone else's measurements behind it.*
- *The same applies to how we evaluate. "Did the bot win" will not separate
  two models. We need closer measures such as how often the model's opening
  matches a human's, and income at fixed minutes.*
- *Apex's owner could not get its economy near his own play by pricing. A
  model that imitates strong players' economy is attacking the same gap from
  the other side.*

## `imitate.py` compared with what we need

[`tools/imitate.py`][imitate] (303 lines, added in [`b4d91d03`][c-imitate]) is
the closest thing in Apex to Reason8's idea.

**What it does.** Every time a team *finishes a structure*, it records the
situation and the kind of structure. A small network (12 inputs, two hidden
layers of 32, 9 outputs) learns to predict the kind from the situation. Games
are split 80/20 by game, and accuracy is compared with always guessing the
commonest class.

- **Inputs (12):** game minute, metal income, energy income, the number of
  finished structures in each of 8 classes, and the metal value of the mobile
  army.
- **Output (9 classes):** extractor, energy, converter, storage, factory,
  construction turret, ground defence, air defence, other.
- **Result on BARb:** 98,518 structures from 924 games; 37.7% correct on
  held-out games, against 25.7% for the baseline.
- **Use in the game:** the predicted odds tilt the market's prices by a
  strength `apex_nn_imitate`. The default is 0. The trained weights ship in
  v0.5.17 but the strength is still 0, and we found no head-to-head test of it
  *(inferred: no commit or doc reports one)*.
- **`--human` mode** ([`8af40ea5`][c-human]): the same features and classes,
  taken from human teams in extracted replays. The commit reports one replay
  (six humans, 1,425 structures) and no accuracy. Nothing in the repository
  reads the resulting file *(inferred from searching the tools and scripts)*.

**How that compares with what human imitation needs:**

**What is predicted**
: *`imitate.py`:* One of 9 structure classes
: *What Reason8 needs:* The exact unit, including units from factories
: *Why:* "Energy" does not say wind or solar; the opening is mostly exact
  units. Factory output is not predicted at all

**When a sample is taken**
: *`imitate.py`:* When a structure *finishes*
: *What Reason8 needs:* When the player *orders* it
: *Why:* Finishing lags the decision by the build time, and cancelled or
  destroyed builds never appear. Orders have the opposite problem: some are
  never carried out. We use orders, and check them against what was finished
  in re-simulated replays

**Order of events**
: *`imitate.py`:* Only counts so far
: *What Reason8 needs:* The sequence so far
: *Why:* Openings are sequences. Two players with the same counts at minute 3
  may be following different plans

**Map and start position**
: *`imitate.py`:* Not used
: *What Reason8 needs:* Required
: *Why:* README goal: each start position on a team map has its own meta

**Faction**
: *`imitate.py`:* Not used
: *What Reason8 needs:* Required
: *Why:* Unit names differ per faction

**Team size and role**
: *`imitate.py`:* Not used
: *What Reason8 needs:* Required for team games
: *Why:* Apex's one human replay shows it: 44% of structures at minutes 20–24
  were construction turrets, typical of a back-line economy player

**Player skill**
: *`imitate.py`:* Not used (BARb has one skill level)
: *What Reason8 needs:* Filter or weight by rating
: *Why:* We want to imitate good players, and the public dataset has OpenSkill
  ratings

**Game version**
: *`imitate.py`:* Not used
: *What Reason8 needs:* Recorded per sample
: *Why:* Balance patches change the right answer

**Stored resources**
: *`imitate.py`:* Not used (income only)
: *What Reason8 needs:* Yes, from re-simulated replays
: *Why:* Stalling or overflowing drives the next build

**Enemy information**
: *`imitate.py`:* Own army only
: *What Reason8 needs:* What the player could see, from milestone 3
: *Why:* Must respect fog of war to stay human-like

**Where the data comes from**
: *`imitate.py`:* Engine log lines, so every game must be simulated
: *What Reason8 needs:* Milestone 1: commands parsed straight from the replay
  file. Milestone 2: simulated state
: *Why:* Parsing is far cheaper than re-simulating

**Evaluation**
: *`imitate.py`:* Held-out games, commonest-class baseline
: *What Reason8 needs:* The same, plus top-k accuracy, and splits by map,
  position and skill
: *Why:* Same method, more slices

*The method is the same as ours and it is a useful sanity check: even with 12
crude inputs, a small network beat the baseline by 12 points on BARb, whose
choices are partly random. What is missing for humans is mostly context (map,
position, faction, skill) and exact units.*

One idea worth keeping for later: Apex does not let the imitation model pick
the build. It **tilts the prices** of options the game already allows, with a
strength that can be turned to zero. *That is a safe way to plug a learned
prior into a working bot, and it is how a Reason8 model could feed BARb's
probability tables in milestone 2.*

## How Apex extracts data from replays

A replay stores commands, not game state (see the README), so Apex re-plays
it:

1. [`tools/replay_extract.py`][extract] (114 lines) creates an empty write
   directory and copies one widget into its `LuaUI/Widgets/` folder.
2. It starts `spring-headless --write-dir <dir> --config <cfg> <replay.sdfz>`,
   with `SPRING_DATADIR` pointing at the BAR install so the engine finds the
   game and the map.
3. The widget, [`barai_replay_export.lua`][widget] (217 lines), runs as a
   spectator with full view. It is **unsynced**: it only watches, so it cannot
   change the simulation. It sets the replay speed to 200× and quits at game
   over.
4. The widget prints one line per event to the engine log. The script keeps
   the lines tagged `[BARAI_`, and reads map, game version, players and AI
   teams from the start script embedded in the replay.

What the widget records:

`BARAI_PROD`
: *When:* a unit leaves a factory
: *Fields:* team, frame, unit name, metal cost, factory

`BARAI_BUILD`
: *When:* a structure is finished
: *Fields:* team, frame, unit name, cost, position

`BARAI_DEATH`
: *When:* a unit dies
: *Fields:* unit, position, whether it was finished, attacker's team, type and
  position

`BARAI_DMG`
: *When:* every 10 s
: *Fields:* damage dealt and received so far, split by mobile and static

`BARAI_WASTE`
: *When:* every minute
: *Fields:* metal and energy produced and wasted so far

`BARAI_RESULT`
: *When:* game over
: *Fields:* winning ally teams. If the recording stops early, the one side
  with a commander left

What it does **not** record: commands, when a build was *started* and by whom,
stored resources, unit positions over time, and what each player could see. A
second widget used by [`tools/census.py`][census] adds a per-minute count of
units per team.

[`tools/replay_batch.py`][batch] runs this over a folder of replays, two at a
time by default, skips finished ones, and retries empty results up to three
times because "a run that died under memory pressure" returns nothing.

**Numbers Apex reports.** One 8v8 replay gave 1,516 finished structures, 1,878
factory units and 1,426 deaths in the first 31 minutes
([`3bf605be`][c-export]). `census.py` says a replay takes "about 1 minute" at
speed. The README says each headless engine uses 5–6 GB of memory; that figure
is given for AI-vs-AI matches, and no separate figure is given for replays.
**We did not measure anything. Speed, memory and output size on public replays
are not measured here.**

### What it would take to reuse

- **Engine, game and map must match the replay.** The engine has to find the
  exact game version and map the replay was recorded with *(inferred from how
  lockstep replays work; Apex replays games from the owner's own install,
  where those versions are already present, and its tools do not fetch missing
  ones)*. For public replays across many versions this is the main cost, and
  it ties into the version policy in the README.
- **Linux.** Apex's tools assume Windows (`spring-headless.exe`, PowerShell).
  Our engine install has a Linux `spring-headless`, and the launch line is
  simple, so this is a rewrite of about 100 lines of Python, not a port.
- **Our own widget.** We need different output: build *starts* with the
  builder, stored resources, periodic unit counts, and later what each player
  could see. We also want structured output (one JSON line per event) instead
  of text scraped from the log.
- **Watch for stray widgets.** Apex found that headless games load every user
  widget in the data folder, and one printing a result line was misread as
  every match's result (S62). Use a clean write directory per run.

## Licensing

- The repository has **no `LICENSE` file**, and GitHub reports no licence. By
  default that means all rights reserved: we may read it, but not copy code.
- **Files that carry their own licence line:** every Lua gadget and widget
  under [`game-patches/gadgets/`][gadgets] and
  [`game-patches/widgets/`][widgets] (21 files, including the replay export
  widget) declares `GNU GPL, v2 or later` (two say `GPL v2 or later`) in its
  info table.
- **Inside `cpp/`**, a few files keep headers from their original authors:
  Spring engine files (GPL v2 or later), MicroPather (zlib-style) and
  `GridAnalyzer.h` (MIT/X11).
- The C++ as a whole is a modified copy of
  [CircuitAI](https://github.com/rlcevg/CircuitAI), which is GPL-2.0, and
  Apex's own fork
  [apexearth/CircuitAI](https://github.com/apexearth/CircuitAI) keeps that
  licence. The AngelScript and JSON started as copies of BARb's files from the
  BAR game repository. *So much of Apex is probably already bound by the GPL
  (inferred; this is not legal advice).*
- **The Python tools** (`imitate.py`, `replay_extract.py`, the match harness)
  have no licence line at all.

## What we reuse, what we do differently

**Army control**
: *From Apex:* Leave it to stock BARb; Apex measured twice that its own
  version was worse
: *Reason8:* Same (already in our roadmap)
: *Why:* Their evidence saves us the experiment

**How a model enters the bot**
: *From Apex:* Tilt existing choices with an adjustable strength; zero means
  "plain bot"
: *Reason8:* Same idea, applied to BARb's opener and probability tables
: *Why:* The bot can always finish a game, and the model can be turned down if
  it is wrong

**Installing a custom AI**
: *From Apex:* Own short name, copy of the stock BARb folder, config and
  script next to the library
: *Reason8:* Done the same way, with our own build tool
  ([ADR 0007](../decisions/0007-ship-the-model-as-tables-in-a-barb-variant.md))
: *Why:* No C++ build, works in hosted games

**Replay state extraction**
: *From Apex:* Headless replay plus an unsynced spectator widget
: *Reason8:* Same design, our own code, used from the first milestone
: *Why:* Sound idea; their code is unlicensed, Windows-only and logs the wrong
  things for us

**Evaluation habits**
: *From Apex:* Cap the game speed (uncapped headless games stall the AIs),
  swap sides and start boxes, use paired games on the same seed, run an A/A
  test to learn the noise first
: *Reason8:* Adopt all four
: *Why:* Apex lost days to each of these

**Imitation set-up**
: *From Apex:* Split by game, compare with the commonest-class baseline
: *Reason8:* Same
: *Why:* Standard and cheap

**Where decisions live**
: *From Apex:* 115k lines of hand-written prices in a C++ fork
: *Reason8:* Learned tables inside stock BARb, one layer at a time
: *Why:* We want the knowledge to come from replays, and we cannot maintain a
  fork of that size

**What teaches the model**
: *From Apex:* Outcomes of AI-vs-AI games
: *Reason8:* Human decisions in public replays; self-play only in milestone 4
: *Why:* Apex's outcome-based training did not find a signal. Human games also
  contain the play we want to copy

**Opponent**
: *From Apex:* Tuned against BARb
: *Reason8:* Judged against human play first, then against BARb
: *Why:* A bot tuned against one AI learns that AI's habits

**What is predicted**
: *From Apex:* 9 structure classes, at finish time
: *Reason8:* Exact units in order, at order time, with map, position, faction
  and skill
: *Why:* See the comparison table above

**Goal**
: *From Apex:* Strongest and most fun AI for hosted games
: *Reason8:* Human-like team player under human limits
: *Why:* Different goals. We found no human-like limits on command rate or
  attention in Apex (inferred)

## Limits of this study

- Apex's replay extraction was read, not run: its speed, memory use and output
  on public replays are not measured here.
- Apex's army layer ([`docs/army.md`][army]) and its match harness
  (`tools/run_match.py`, `tools/run_tournament.py`, `tools/bench.py`) were
  only skimmed.

## Sources

- Apex docs at [`927ff16c`][head]: `README.md`, `docs/how-it-works.md`,
  `docs/doctrine.md`, `docs/versions.md`, `docs/old-versions.md`,
  `docs/working.md`, `docs/traps.md`, `docs/tunables.md`, `ISSUES.md`,
  `results/README.md`
- Apex code: `tools/imitate.py`, `tools/replay_extract.py`,
  `tools/replay_batch.py`, `tools/census.py`, `tools/mp_archive.py`,
  `tools/deploy_ai.py`, `tools/package_ai.py`,
  `game-patches/widgets/barai_replay_export.lua`,
  `ai/Unstable/game-side/script/standard/` (`tunables.as`,
  `misc/commander.as`, `manager/brain/market/{opennet,nnlog,policydata}.as`),
  `.github/release.env`
- Apex commits and tags cited inline; tag messages via `git tag -n`
- Our counts: `diff` of `cpp/src/circuit` against CircuitAI `0ef36267`;
  `wc -l` over `reference/barb-stable/game-side` and `ai/Unstable/game-side`
- Licences: GitHub repository metadata for `apexearth/bar-ai`,
  `apexearth/CircuitAI` and `rlcevg/CircuitAI`; a search for licence lines in
  the Apex tree

[army]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/docs/army.md
[batch]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/tools/replay_batch.py
[c-export]: https://github.com/apexearth/bar-ai/commit/3bf605be
[c-guard]: https://github.com/apexearth/bar-ai/commit/913d0549
[c-human]: https://github.com/apexearth/bar-ai/commit/8af40ea5
[c-imitate]: https://github.com/apexearth/bar-ai/commit/b4d91d03
[c-kill]: https://github.com/apexearth/bar-ai/commit/fcbabf2e
[c-lean]: https://github.com/apexearth/bar-ai/commit/5d1089d3
[c-ledger]: https://github.com/apexearth/bar-ai/commit/4c783872
[c-market]: https://github.com/apexearth/bar-ai/commit/a5c2708f
[c-pg]: https://github.com/apexearth/bar-ai/commit/6bc00d15
[c-revert]: https://github.com/apexearth/bar-ai/commit/7a1a9895
[c-strip]: https://github.com/apexearth/bar-ai/commit/da745816
[census]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/tools/census.py
[check]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/tools/check.py
[commander]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/ai/Unstable/game-side/script/standard/misc/commander.as
[deploy]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/tools/deploy_ai.py
[doctrine]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/docs/doctrine.md
[eco]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/issues/eco-half-his-curve.md
[extract]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/tools/replay_extract.py
[gadgets]: https://github.com/apexearth/bar-ai/tree/927ff16c170382767fb8dff54df9719028b63ccc/game-patches/gadgets
[head]: https://github.com/apexearth/bar-ai/tree/927ff16c170382767fb8dff54df9719028b63ccc
[how]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/docs/how-it-works.md
[imitate]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/tools/imitate.py
[modopt]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/issues/modoption-overridden-by-lobby.md
[nntrain]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/tools/nntrain.py
[oldversions]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/docs/old-versions.md
[opennet]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/ai/Unstable/game-side/script/standard/manager/brain/market/opennet.as
[r-v0517]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/results/v0515/2026-11-18-sh3-v0-5-17-candidate-vs-barb-stable-hard-final-tree-no-lobb.md
[ref]: https://github.com/apexearth/bar-ai/tree/927ff16c170382767fb8dff54df9719028b63ccc/reference/barb-stable
[results]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/results/README.md
[traps]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/docs/traps.md
[tunables]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/docs/tunables.md
[versions]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/docs/versions.md
[widget]: https://github.com/apexearth/bar-ai/blob/927ff16c170382767fb8dff54df9719028b63ccc/game-patches/widgets/barai_replay_export.lua
[widgets]: https://github.com/apexearth/bar-ai/tree/927ff16c170382767fb8dff54df9719028b63ccc/game-patches/widgets
