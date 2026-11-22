# Reason8

An AI for [Beyond All Reason](https://github.com/beyond-all-reason/Beyond-All-Reason) (BAR) that learns to play from publicly available replays of human games.

> **Status:** early proof of concept. Nothing playable yet — see the [issues](../../issues) and the *PoC* milestone for what's being worked on.

## The idea in one paragraph

Instead of hand-writing rules ("build 2 mexes, then a lab, then…"), we show a model thousands of real games and train it to predict *what a good player does next* in a given situation. This is called **imitation learning** (or behavioural cloning). It's how AlphaStar's StarCraft II agent was bootstrapped before it improved further through self-play. We start with the smallest version of that idea that can actually be tested: **learn opening build orders from replays**, then have a simple in-game AI follow them.

## How training works (for newcomers)

| Step | What it means here |
|---|---|
| **Data** | Replay files (`.sdfz`) of real BAR matches, plus match metadata (map, skill ratings, winner). |
| **Examples** | Turn each replay into many *(situation → action)* pairs, e.g. *"after building these 6 things, the player built a Bot Lab"*. |
| **Model** | A function with adjustable numbers (parameters) that takes a situation and outputs a probability for each possible action. |
| **Training** | Repeatedly show the model examples and nudge its parameters so the action the human actually took becomes more likely. |
| **Evaluation** | On games the model never saw, how often is its top guess the human's real choice? Compare against a dumb baseline first. |
| **Deployment** | Run the model inside (or alongside) the game so a bot can act on its predictions. |

## Where the data comes from

| Source | What it gives us |
|---|---|
| [`data-processing`](https://github.com/beyond-all-reason/data-processing) public dumps — e.g. `https://data-marts.beyondallreason.dev/matches.parquet` | Match metadata, rebuilt twice a week: map, game type, winner, duration, game version, player skill (OpenSkill), and `replay_file_name`. |
| BAR public object storage — `https://storage.uk.cloud.ovh.net/v1/AUTH_10286efc0d334efd917d476d7183232e/BAR/demos/<replay_file_name>` | The replay files themselves. The replay site notes downloads *may be expired if older than a year*. |
| [`sdfz-demo-parser`](https://github.com/beyond-all-reason/demo-parser) (used by [bar-lobby](https://github.com/beyond-all-reason/bar-lobby)) | Parses `.sdfz` into JSON: header, players, end-of-game stats and the packet stream, including **build commands resolved to unit names**. |
| `https://api.bar-rts.com/replays` | The replay search API bar-lobby uses (`?players=…&limit=…&page=…`, `/replays/<id>`). |

### An important caveat about replays

BAR runs on the Recoil engine, which uses *lockstep* simulation: a replay records **player commands**, not the game state. To know "what the map looked like" at minute 7 you have to re-run the replay through the engine. The PoC deliberately avoids needing that by working on build orders (which are visible directly in the commands); getting full game state is tracked as a separate research issue.

## Related work

- **BARb** — the AI that ships with BAR, built on [CircuitAI](https://github.com/rlcevg/CircuitAI).
- **[Apex](https://github.com/apexearth/bar-ai)** — a BARb fork where small neural nets adjust a build "market", trained on AI-vs-AI games. It also has tooling to re-play replays headlessly and log game state, which is directly relevant to us. Reason8 differs by learning from **human** replays.

## Being a good citizen

- Download replays politely (rate-limited, cached, never re-downloaded) — this is community-funded infrastructure.
- BAR repos have an AI usage policy (`AI_POLICY.md`); follow it if contributing upstream.
- Player names in replays are personal data — the training data we publish should be anonymised.

## Layout (planned)

```
reason8/
  data/          # local cache — git-ignored
  notebooks/     # exploration
  reason8/       # Python package: download, parse, dataset, models
  parser/        # thin Node wrapper around sdfz-demo-parser
  ai/            # in-game side (Lua) — later
```

## License

GPL-2.0, same as Beyond All Reason — see [LICENSE](LICENSE).
