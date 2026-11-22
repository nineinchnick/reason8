# BARb: the default BAR AI

These notes come from reading the source:

- **C++:** [rlcevg/CircuitAI](https://github.com/rlcevg/CircuitAI), branch
  `barbarian`, at commit `e3bebd3` (2026-09-13)
- **Game-side scripts and configs:**
  [Beyond-All-Reason](https://github.com/beyond-all-reason/Beyond-All-Reason)
  `luarules/configs/BARb/stable/`, `master` as of 2026-11-22

The "Not covered yet" section at the end lists what still needs hands-on
testing.

## TL;DR

- BARb (also called "BARbarian") is a **native Skirmish AI**, a C++ library
  the engine loads. It's built from **CircuitAI**. Most behaviour is in C++.
  **AngelScript** scripts and **JSON** configs, shipped with the game itself,
  tune it per difficulty.
- It doesn't plan. **Managers keep a pool of build tasks. Each idle unit takes
  the best task for itself**, scored by priority, travel cost and safety.
- **The opening** is a weighted random pick from a few hand-written sequences
  per factory. **After the opening**, each factory picks units at random using
  hand-tuned probability tables that depend on income.
- **Both are lookup tables of probabilities, which is the same shape as a
  model's output.** *So the easiest place for Reason8 to plug in is to replace
  these tables with predictions learned from replays, and leave the rest of
  BARb alone.*

## Where things live

C++ (CircuitAI)
: *Where:* `src/circuit/` in CircuitAI. Compiled into `SkirmishAI.dll` /
  `libSkirmishAI.so`, shipped with the engine
: *What it does:* Everything heavy: managers, task pool, threat and influence
  maps, pathing, placement, combat

AngelScript
: *Where:* BAR repo: `luarules/configs/BARb/stable/script/<profile>/` + shared
  `common.as`, `define.as`, `task.as`, `unit.as`
: *What it does:* Hooks the C++ calls (see below). Mostly just calls back into
  C++ defaults; the real logic is the **factory openers** and a few economy
  thresholds

JSON
: *Where:* BAR repo: `luarules/configs/BARb/stable/config/<profile>/*.json`
: *What it does:* Unit roles, threat values, unit probabilities per factory,
  energy building limits, defence lists, commander behaviour

**Profiles (difficulties):** `easy`, `medium`, `hard`, `hard_aggressive`.
`AIOptions.lua` uses `hard` by default. `init.as` loads the config parts
`behaviour`, `block_map`, `build_chain`, `commander`, `economy`, `factory`,
`response`. If the matching mod options are on, it also adds `_leg` (Legion
faction), scav-unit and extra-unit files.

**Loading:** with the `game_config` option on (the default), the AI reads
scripts and configs **from the game archive first**. It only falls back to
copies bundled next to the DLL. *So BARb's behaviour can change with a BAR
game update even when the engine and DLL stay the same.* (`SetupManager.cpp`,
`ScriptManager.cpp`)

**Fairness:** there's an option called `cheating` ("LOS vision"), off by
default. With it off, the enemy tracking code checks line of sight and radar
before reading enemy units (`EnemyManager.cpp`).

## The decision loop

```
          ┌──────────────── managers add tasks ────────────────┐
          │                                                    │
 EconomyManager (mexes, energy, storage, factories, geo)       │
 MilitaryManager (defences, big guns, combat targets)          ▼
 FactoryManager (recruit tasks, assist)              ┌──────────────────┐
 AngelScript (openers, AiMakeDefence …)  ──────────► │  task pool       │
                                                     │  (priority, pos, │
 idle unit ──► AiMakeTask(unit) [AngelScript] ──►    │   build def)     │
               DefaultMakeTask [C++] ──picks best──► └──────────────────┘
```

### Builders (`BuilderManager::DefaultMakeTask` → `MakeBuilderTask`)

For each idle constructor:

1. If it can fight and there's a target nearby → **combat**.

2. **Commander**: early on, or while in danger, it's kept close to base
   (`commander.json`: `hide.time`, `hide.threat`).

3. Builders marked `BASE` become **energizers**: one cheap constructor (under
   200 metal; picked once there are more of its type than guard tasks, or if
   it flies) and one expensive constructor (`builder.as`). They take base
   tasks (`MakeEnergizerTask`).

4. Everyone else: ask the economy to add metal tasks for the nearest metal
   spot group (`MakeEconomyTasks`). Then go through **every task in the pool**
   and drop the ones that:

   - this builder can't do,
   - can't be reached,
   - are in a threatened spot (threat map plus influence map), or
   - aren't urgent while the economy is stalling.

   From the rest, pick the lowest **travel cost × 1/(priority+1)²**.

5. If nothing fits: energy task, then reclaim, then a "big gun" (late-game
   structure) if income allows, then guard a factory or army leader, then
   guard the commander, then patrol.

### Economy (`EconomyManager`)

- **Energy**: for each generator type, `economy.json` sets a random count
  limit between `[min, max]`, plus thresholds for metal income, energy income
  and a score. Example from `hard`: `armsolar: [12, 14, 0, 0, 0.03]`,
  `armfus: [3, 4, 50, 900, 1.9]`.
- **Resource state flags** (`economy.as`): e.g. "metal empty" means below 20%
  of storage. Energy is never flagged empty in the first 3 minutes. These
  flags gate a lot of decisions.
- **Factory choice** (`GetFactoryToBuild`): settings in `factory.json` →
  `select`: air-map threshold, map-size speed factor, minimum land %, etc.
- **When to switch factories** (`factory.as` `AiIsSwitchTime`):
  `(frames since last switch)^0.9 × metal income + 7 × stored metal`, compared
  with a random limit `AiRandom(8000, 12000) × SECOND` that's redrawn after
  each switch.

### Factories (`FactoryManager::DefaultMakeTask` → `CreateFactoryTask`)

1. **Opener:** when a factory is finished, `factory.as` → `Opener::GetOpener`
   **picks one of 1–3 hand-written sequences at random**, with weights. A
   sequence is a list of **roles**, not units, e.g. `armlab`, weight 0.4:
   `BUILDER, SCOUT×2, RAIDER×2, BUILDER, RAIDER, BUILDER, RAIDER×5, BUILDER, RAIDER`.
   Each role becomes a concrete unit through that factory's role definitions,
   and the whole sequence is queued.
2. **After the opener:** first build power (constructors), unless the economy
   is stalling; then firepower. Units are drawn from `factory.json` →
   `factory.<name>.unit` with **probability vectors per income tier**,
   separately for land and air maps. For example, `armlab` has 8 units and
   tiers split at metal income `[2, 25, 35, 50, 100]`.
3. Air factories stop when the enemy's anti-air threat goes above 80
   (`military.as`, marked deprecated).

### Military (not studied in depth yet)

`MilitaryManager` handles defence placement (`build_chain.json` → `porcupine`
lists defences per faction), army quotas and retreat thresholds
(`behaviour.json`: `quota`, `retreat`, `defence`), and counter-unit responses
(`response.json`). `AiMakeDefence` in `military.as` only allows defences after
5 minutes, or once metal income is above 10, or when enemy mobile threat shows
up. *This is out of scope for the PoC, but it'll matter once we go past the
opening.*

### How it sees the game

`ThreatMap`
: Grid of enemy threat by type (air / surface / water). Used for safety checks
  and path costs

`InfluenceMap`
: Ally vs enemy influence per cell

`EnemyManager`
: Known enemy units, cost per role, mobile threat

`EconomyManager`
: Current, storage, pull and income for metal and energy; average incomes

`MetalManager`
: Metal spots and spot groups, which are taken

Unit config (`behaviour.json`)
: Role, attributes, threat multipliers, power and retreat for every unit

*A Reason8 model running inside BARb would see the same signals. That's richer
than what we can get from replay commands alone, so the features we train on
need to be ones we can also get at play time.*

## Where a learned model could hook in

From least to most invasive:

**Opener tables** in `script/<profile>/misc/commander.as` (1)
: *What the model decides:* Which opening sequence a factory plays (weights,
  or a sequence we generate)
: *Effort:* AngelScript or data only, no C++. *Best match for the PoC*

**Factory unit probabilities** in `config/<profile>/factory.json` (2)
: *What the model decides:* Mix of units per income tier
: *Effort:* JSON only. Could be learned offline from replays and written in as
  numbers

**`Factory::AiGetFactoryToBuild`** (3)
: *What the model decides:* Which factory to build first or next
: *Effort:* AngelScript. The C++ default is one call away

**Energy limits** in `economy.json` (4)
: *What the model decides:* How many of each generator, and when
: *Effort:* JSON only

**`Builder::AiMakeTask`** (5)
: *What the model decides:* Which task each builder takes
: *Effort:* AngelScript, but would need a lot of game state passed to the
  script, or running the model in C++

**C++ fork** (what Apex does) (6)
: *What the model decides:* Anything
: *Effort:* Needs a build in Docker against Recoil sources

*Hooks 1–4 need no new code at play time. We'd learn the numbers offline from
human replays and write them into a custom profile, e.g. `config/reason8/` +
`script/reason8/`. That could be our first playable PoC, and much cheaper than
writing a bot from scratch.* The connection here is speculative until we've
confirmed a custom profile can be loaded without changing the game archive.

**One mismatch to sort out:** BARb's openers are in **roles** (RAIDER,
SCOUT…), and only for **factory** output. Replays give us **unit names** for
every BUILD order, including the commander's and builders' structures. We need
a mapping between them. `behaviour.json` gives every unit its roles, so it can
serve as that mapping.

## What players say (anecdotal)

- One player reports a 100% win rate against 1v1 hard BARb over a couple of
  weeks, says the AI "does not have much of a plan", and regularly out-ecos
  it.
- In bigger AI-vs-AI games, players have seen BARb overflow its resources
  while doing almost nothing, or move siege units in "conga lines" around its
  own base. One player suspects the AI gets stuck deciding what to do.

*Both fit the design above: random tables instead of a plan, and a task pool
that can run out of useful tasks.* That's a reasonable guess, not something
we've confirmed.

## Not covered yet (needs BAR running)

- [ ] Play a few skirmishes against `hard` BARb on 1–2 popular 1v1 maps and
  keep the replays. They'll be test data for the replay parser
- [ ] Confirm a custom profile (copy of `hard` with edited openers) loads, and
  how: game-side override vs files next to the DLL. Apex's approach (own short
  name, files next to the library) is described in
  [`related-work.md`](related-work.md); still to be tried
- [ ] Note how BARb's openings look next to human openings on the same maps
- [ ] Military layer in depth (only if we go past the opening)

## Sources

- CircuitAI `barbarian`:
  `src/circuit/module/{BuilderManager,EconomyManager,FactoryManager,MilitaryManager}.cpp`,
  `src/circuit/setup/SetupManager.cpp`,
  `src/circuit/script/ScriptManager.cpp`,
  `src/circuit/unit/enemy/EnemyManager.cpp`, `data/AIOptions.lua`
- BAR: `luarules/configs/BARb/stable/script/hard/{init,main}.as`,
  `manager/{builder,economy,factory,military}.as`, `misc/commander.as`;
  `config/hard/{factory,economy,commander,behaviour,build_chain}.json`
- Player reports: r/beyondallreason threads "How to be faster" (Dec 2024) and
  "Barb AI (hard) chilling in game with multiple AI" (Jan 2024)
