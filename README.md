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
uv sync                       # create .venv with all dependencies
uv run pre-commit install     # run the checks on every commit
uv run pytest                 # run the tests
```

## The idea in one paragraph

Instead of hand-writing rules ("build 2 mexes, then a lab, then…"), we show a
model thousands of real games and train it to predict *what a good player does
next* in a given situation. This is called **imitation learning** (or
behavioural cloning). It's how AlphaStar's StarCraft II agent was bootstrapped
before it improved further through self-play. We start with the smallest
version of that idea that can actually be tested: **learn the opening for each
start position on a popular team map**, then have a bot play it in team games.

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
  choice? Compare against a dumb baseline first. What counts in the end is how
  the bot plays in the game.

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

The first milestone succeeds when, on Supreme Isthmus, a classifier cannot
tell the bot's openings from human ones at the same position, and its economy
at first contact is at least stock BARb's
([ADR 0003](docs/decisions/0003-define-success-as-in-game-measures.md)).

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

## Related work

- **BARb** — the AI that ships with BAR, built on
  [CircuitAI](https://github.com/rlcevg/CircuitAI).
- **[Apex](https://github.com/apexearth/bar-ai)** — a BARb fork where small
  neural nets adjust a build "market", trained on AI-vs-AI games. It also has
  tooling to re-play replays headlessly and log game state, which is directly
  relevant to us. Reason8 differs by learning from **human** replays.
- **AlphaStar / AlphaStar Unplugged** (StarCraft II) — imitation from human
  replays, then offline RL; also the main lesson on human-like limits.
- See [`related-work.md`](docs/research/related-work.md) for what Apex changed
  in BARb, what it measured, and what we reuse or do differently.

## Being a good citizen

- Download replays politely (rate-limited, cached, never re-downloaded) — this
  is community-funded infrastructure.
- BAR repos have an AI usage policy (`AI_POLICY.md`); follow it if
  contributing upstream.
- Player names in replays are personal data — the training data we publish
  should be anonymised.
- Ask BAR maintainers and tournament organisers before bulk downloads or
  publishing derived datasets.

## Layout

```
reason8/              # the Python package
  game/               #   game versions and balance patches
tests/                # mirrors reason8/
docs/
  decisions/          # architecture decision records, from the most fundamental
  research/           # studies and measurements behind the decisions
data/                 # local data — git-ignored
```

## License

GPL-2.0-or-later, the same as Beyond All Reason's code: you can use it under
version 2 of the GNU General Public License or any later version. The licence
text is in [LICENSE](LICENSE); see
[ADR 0002](docs/decisions/0002-license-the-project-gpl-2-0-or-later.md).
