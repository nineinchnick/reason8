# Reason8

An AI for
[Beyond All Reason](https://github.com/beyond-all-reason/Beyond-All-Reason)
(BAR) that learns to play from publicly available replays of human games.

> **Status:** early proof of concept. Nothing playable yet. See the
> [issues](../../issues) and [milestones](../../milestones) for what's being
> worked on.

## Getting started

You need [uv](https://docs.astral.sh/uv/getting-started/installation/); it
installs the right Python (3.15) for you.

```sh
git clone https://github.com/nineinchnick/reason8.git && cd reason8
uv sync          # create .venv with all dependencies
uv run pytest    # run the tests
uv run ruff check . && uv run ruff format .   # lint and format
```

Getting the data (into the git-ignored `data/`, or `$REASON8_DATA_DIR`):

```sh
uv run reason8 download --limit 100   # match dumps, then 100 replays of the slice
parser/fetch.sh                       # once: the pinned replay parser
uv run python -m reason8.parse        # data/replays -> data/parsed/*.json.zst
```

The downloader keeps one connection at about one request per second, never
fetches a file twice, and records every match's status in
`data/replays/manifest.parquet`. See [`docs/dataset.md`](docs/dataset.md) for
the selection and [`docs/replay-format.md`](docs/replay-format.md) for the
parsed output.

## Data storage

The shared copy of the data directory lives in a private S3 bucket; a local
`data/` is a working copy
([ADR 0014](docs/adr/0014-keep-the-data-in-a-private-s3-bucket.md)). Raw
replays contain player names and are never published. Using the bucket is
opt-in: ask the maintainer for access, configure AWS credentials as usual
(`aws configure` or `aws login`), and name the bucket:

```sh
export REASON8_S3_URI=s3://<bucket>     # or pass --s3-uri to each command
uv run reason8 sync pull replays parsed # bucket -> data/
uv run reason8 sync push                # data/ -> bucket: replays, parsed, matches
```

`sync` copies files that are missing or differ in size, merges the manifest
and the parse index, and never deletes anything. With the bucket configured,
`reason8 download` looks there before asking BAR's servers and uploads what it
downloads from them. Storing the whole first slice (about 175 GB of replays
and 54 GB of parsed replays) costs about $6 a month.

## The idea in one paragraph

Instead of hand-writing rules ("build 2 mexes, then a lab, then…"), we show a
model thousands of real games and train it to predict *what a good player does
next* in a given situation. This is called **imitation learning** (or
behavioural cloning). It's how AlphaStar's StarCraft II agent was bootstrapped
before it improved further through self-play. We start with the smallest
version of that idea that can actually be tested: **learn the opening build
order for each start position on a popular team map**, then have a bot play it
in team games.

## How training works (for newcomers)

**Data**
: Replay files (`.sdfz`) of real BAR matches, plus match metadata (map, skill
  ratings, winner).

**Examples**
: Turn each replay into many *(situation → action)* pairs, e.g. *"after
  building these 6 things, the player built a Bot Lab"*.

**Model**
: A function with adjustable numbers (parameters) that takes a situation and
  outputs a probability for each possible action.

**Training**
: Repeatedly show the model examples and nudge its parameters so the action
  the human actually took becomes more likely.

**Evaluation**
: On games the model never saw, how often is its top guess the human's real
  choice? Compare against a dumb baseline first.

**Deployment**
: Run the model inside (or alongside) the game so a bot can act on its
  predictions.

## Goals

- **A team player.** The first target is team games: on popular maps like
  Supreme Isthmus each start position has an established meta, and the bot
  should learn and recognise it. It should also cooperate: answer help
  requests during raids, join planned raids, and follow the team captain's
  requests.
- **Plays to the end.** Openings are only the start. 1v1 games are the main
  source for learning whole-game decisions, because one player makes every
  decision.
- **Human-like.** The bot plays under the same limits as people: only what it
  can see, human command rates (including bursts), reaction time and limited
  attention. It should win by decisions, not by speed or extra information.
- **Grows inside BARb.** BARb, the AI that ships with BAR, already plays full
  games. Reason8 replaces its decisions one layer at a time (openings → macro
  → production), so the bot can always finish a game.

## Roadmap

**1. PoC: learned openings**
: Team bot that plays the opening for its start position, predicted from
  replays; BARb takes over after

**2. Learned macro (1v1)**
: The model decides what to build for the whole game from game state recovered
  from replays; BARb runs production and army

**3. Learned production**
: Unit mix chosen from scouted information; team communication

**4. Beyond imitation**
: Offline RL on replays, then self-play, still within the human-like limits

Army control and unit micro stay with BARb until there's a reason to change
that.

### Out of scope (for now)

PvE modes (Scavengers, Raptors) and free-for-all games.

## Where the data comes from

[`data-processing`](https://github.com/beyond-all-reason/data-processing) public dumps — e.g. `https://data-marts.beyondallreason.dev/matches.parquet`
: Match metadata, rebuilt twice a week: map, game type, winner, duration, game
  version, player skill (OpenSkill), and `replay_file_name`.

BAR public object storage — `https://storage.uk.cloud.ovh.net/v1/AUTH_10286efc0d334efd917d476d7183232e/BAR/demos/<replay_file_name>`
: The replay files themselves. The replay site notes downloads *may be expired
  if older than a year*.

[`sdfz-demo-parser`](https://github.com/beyond-all-reason/demo-parser) (used by [bar-lobby](https://github.com/beyond-all-reason/bar-lobby))
: Parses `.sdfz` into JSON: header, players, end-of-game stats and the packet
  stream, including **build commands resolved to unit names**.

`https://api.bar-rts.com/replays`
: The replay search API bar-lobby uses (`?players=…&limit=…&page=…`,
  `/replays/<id>`).

Tournaments, leagues and casts
: A smaller hand-picked set of expert games (Alpha Cup, weekly leagues,
  YouTube casts), used for evaluation and extra weight.

### An important caveat about replays

BAR runs on the Recoil engine, which uses *lockstep* simulation: a replay
records **player commands**, not the game state. To know "what the map looked
like" at minute 7 you have to re-run the replay through the engine. The PoC
deliberately avoids needing that by working on build orders (which are visible
directly in the commands). Even then, a command is an intention: builds can be
cancelled or re-queued. Full game state is needed from milestone 2;
[`docs/state-extraction.md`](docs/state-extraction.md) shows how to recover it
with a headless engine and what it costs.

### Game versions

BAR is rebalanced every few weeks, so openings from old versions could be
wrong today. Measured on Supreme Isthmus, a year of balance patches moved
openings less than sampling noise, so the dataset keeps its whole time window
across patches, records the version and patch era of every game, and models
record the versions they were trained on and check them when loaded. See
[`docs/game-versions.md`](docs/game-versions.md) for the patches, the
measurement and the routine after a patch, and
[ADR 0012](docs/adr/0012-keep-the-time-window-across-balance-patches.md) for
the policy.

### Map meta

BAR's map metadata recommends start positions per map, each with a role
(front, tech, air, sea), and the game shows them before the start. On the
slice maps 97 to 99% of players start on one. `reason8.positions` gives every
player of a replay that position, from the game's own lobby options or from
the map list fetched by `python -m reason8.map_metadata`: sixteen positions on
an 8v8 map, eight per side. Supreme Isthmus has seven recognisably different
openings per side; All That Glitters and Rosetta have three (front, tech,
air). The meta is strongest in the first factory and loose in the exact build
order. See [`docs/maps/`](docs/maps/README.md) for the positions, the sources
and the numbers per map, and
[ADR 0015](docs/adr/0015-take-positions-from-the-map-metadata.md) for how
positions are defined.

## Compute

Training and headless simulation run **locally first**. Bulk jobs (re-running
thousands of replays, large evaluation runs) can move to a **cloud cluster**
of containerised headless engines when local machines aren't enough. Measured
costs and thresholds will live in `docs/compute.md`.

## Related work

- **BARb** — the AI that ships with BAR, built on
  [CircuitAI](https://github.com/rlcevg/CircuitAI).
- **[Apex](https://github.com/apexearth/bar-ai)** — a BARb fork where small
  neural nets adjust a build "market", trained on AI-vs-AI games. It also has
  tooling to re-play replays headlessly and log game state, which is directly
  relevant to us. Reason8 differs by learning from **human** replays.
- **AlphaStar / AlphaStar Unplugged** (StarCraft II) — imitation from human
  replays, then offline RL; also the main lesson on human-like limits.
- See [`docs/barb.md`](docs/barb.md) for how BARb works and where a learned
  model can hook in.
- See [`docs/related-work.md`](docs/related-work.md) for what Apex changed in
  BARb, what it measured, and what we reuse or do differently.
- See [`docs/in-game.md`](docs/in-game.md) for how a model's decisions get
  into a running game, and how to build and run the Reason8 AI headlessly.

## Being a good citizen

- Download replays politely (rate-limited, cached, never re-downloaded) — this
  is community-funded infrastructure. `reason8 download` does this and stops
  when the server answers 429 or 503.
- BAR repos have an AI usage policy (`AI_POLICY.md`); follow it if
  contributing upstream.
- Player names in replays are personal data — the training data we publish
  should be anonymised.
- Ask BAR maintainers and tournament organisers before bulk downloads or
  publishing derived datasets.

## Layout (planned)

```
reason8/
  data/          # local cache — git-ignored
  notebooks/     # exploration
  reason8/       # Python package: download, parse, dataset, models
  docs/          # research notes; decisions in docs/adr/
  parser/        # pinned sdfz-demo-parser (fetch.sh), fixture tooling
  tools/         # scripts; tools/headless runs games and replays headlessly,
                 #   tools/variant builds and checks the in-game AI
  ai/            # in-game side: ai/Reason8, a BARb variant (AngelScript)
```

## License

GPL-2.0-or-later, the same as Beyond All Reason's code: you can use it under
version 2 of the GNU General Public License or any later version. The licence
text is in [LICENSE](LICENSE); see
[ADR 0016](docs/adr/0016-license-the-project-gpl-2-0-or-later.md).
