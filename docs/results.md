# Results: predicting the next build

The numbers later models are compared against. Every model predicts the unit
of the next step of an opening, the orders of one drag merged into one step,
from the steps before it and what is known before the game: the player's
faction, the map and the start position. The protocol is
[ADR 0018](adr/0018-evaluate-next-build-models-on-held-out-games.md), the data
[`openings-dataset.md`](openings-dataset.md). Code: `reason8/baseline.py`.

```sh
uv run python -m reason8.baseline                 # validation: compare and choose
uv run python -m reason8.baseline --split test    # the tables below
```

## The models

uniform
: Every unit equally likely. Its top-1 is 0%, because the true unit ties with
  all others and ties count against the model.

unit frequency, unit frequency per faction
: The most ordered units, overall or of the player's faction, whatever came
  before.

repeat the previous step
: The unit of the previous step, with the share of steps that repeat the one
  before them in training; the rest by the faction's frequencies.

bigram, trigram, 4-gram, faction
: The next unit after the previous one, two or three steps of the same faction
  (the issue's baselines A and B). The start of the opening counts as a step,
  so the first steps are predicted from what players of the faction do first.

trigram, faction and map; and role; and position
: The faction trigram, told the map, the map and the role of the start
  position, or the map and the position itself: each history length is tried
  with that condition first and then without it.

4-gram, faction, map and position
: The same with three previous steps.

The n-grams interpolate from the most specific context down to plain unit
frequencies and then to the uniform distribution, with Witten-Bell weights: a
context is trusted as much as it has seen different next units. Each model is
counted on every step of the training openings and scored on the first 30
steps of each held-out opening.

## Data

The dataset `openings_v1` as built on 2026-11-22 from 3,597 parsed replays of
the slice ([`openings-dataset.md`](openings-dataset.md)): 2,852 training
games, 315 validation games and 343 test games. The models were compared on
validation and the tables below are on test. With more of the slice parsed,
rebuild the dataset and run both commands again; the split of a game never
changes, so the new numbers replace these.

## Validation

| model                              | top-1             | top-3             | log-loss            |
| ---------------------------------- | ----------------- | ----------------- | ------------------- |
| uniform                            | 0.0% (0.0–0.0)    | 0.0% (0.0–0.0)    | 6.122 (6.122–6.122) |
| unit frequency                     | 9.5% (9.2–9.8)    | 24.9% (24.2–25.5) | 4.072 (4.041–4.101) |
| unit frequency per faction         | 18.1% (17.7–18.5) | 36.3% (35.7–36.9) | 3.265 (3.240–3.289) |
| repeat the previous step           | 42.5% (42.1–42.9) | 57.9% (57.4–58.3) | 2.664 (2.642–2.688) |
| bigram, faction                    | 44.0% (43.6–44.4) | 69.1% (68.6–69.5) | 2.054 (2.038–2.071) |
| trigram, faction                   | 46.6% (46.1–47.0) | 72.1% (71.8–72.5) | 1.911 (1.894–1.928) |
| 4-gram, faction                    | 47.8% (47.4–48.3) | 73.6% (73.3–74.1) | 1.875 (1.856–1.894) |
| trigram, faction and map           | 47.9% (47.5–48.3) | 73.9% (73.5–74.3) | 1.865 (1.846–1.885) |
| trigram, faction, map and role     | 48.4% (48.0–48.8) | 75.1% (74.7–75.5) | 1.791 (1.773–1.809) |
| trigram, faction, map and position | 48.6% (48.2–49.0) | 75.1% (74.7–75.5) | 1.805 (1.787–1.823) |
| 4-gram, faction, map and position  | 49.2% (48.8–49.5) | 75.3% (74.9–75.8) | 1.863 (1.841–1.884) |

The lowest log-loss is `trigram, faction, map and role` (1.791), which is the
model the detailed tables are about and the one that is saved.

## Test

Trained on 2852 games (44098 openings), scored on the test split: 343 games,
5299 openings, the first 30 steps of each. Intervals are 95%, from resampling
games.

### All models

| model                              | top-1             | top-3             | log-loss            |
| ---------------------------------- | ----------------- | ----------------- | ------------------- |
| uniform                            | 0.0% (0.0–0.0)    | 0.0% (0.0–0.0)    | 6.122 (6.122–6.122) |
| unit frequency                     | 9.5% (9.2–9.8)    | 25.2% (24.5–25.8) | 4.026 (3.999–4.052) |
| unit frequency per faction         | 18.2% (17.8–18.6) | 36.8% (36.2–37.4) | 3.241 (3.219–3.263) |
| repeat the previous step           | 42.6% (42.2–43.0) | 57.9% (57.5–58.4) | 2.653 (2.629–2.676) |
| bigram, faction                    | 44.2% (43.8–44.6) | 69.3% (68.9–69.8) | 2.045 (2.028–2.063) |
| trigram, faction                   | 46.7% (46.3–47.2) | 72.4% (72.0–72.8) | 1.901 (1.882–1.919) |
| 4-gram, faction                    | 48.1% (47.6–48.6) | 73.9% (73.5–74.3) | 1.859 (1.839–1.879) |
| trigram, faction and map           | 47.9% (47.5–48.3) | 74.1% (73.7–74.5) | 1.853 (1.833–1.874) |
| trigram, faction, map and role     | 48.6% (48.2–49.0) | 75.4% (75.0–75.9) | 1.781 (1.762–1.802) |
| trigram, faction, map and position | 48.7% (48.3–49.0) | 75.4% (74.9–75.7) | 1.797 (1.778–1.818) |
| 4-gram, faction, map and position  | 49.6% (49.2–49.9) | 75.7% (75.2–76.1) | 1.845 (1.823–1.869) |

157697 steps scored per model. Chosen on validation log-loss:
`trigram, faction, map and role`.

`trigram, faction` on raw orders (drags not merged), for comparison with the
measurements in docs/game-versions.md and docs/maps/: 59.0% (58.6–59.4), 80.2%
(79.9–80.5), 1.543 (1.530–1.557) over 158875 orders.

The tables below are for `trigram, faction, map and role`. The last column is
its top-1 minus that of `trigram, faction` on the same steps, in points, with
a paired interval.

### By step of the opening

| step  | games | steps | top-1             | top-3             | log-loss            | top-1 vs reference   |
| ----- | ----- | ----- | ----------------- | ----------------- | ------------------- | -------------------- |
| 1     | 343   | 5299  | 93.4% (92.5–94.3) | 99.2% (98.9–99.4) | 0.228 (0.198–0.266) | +0.0 (+0.0 to +0.0)  |
| 2–5   | 343   | 21194 | 45.3% (44.5–46.0) | 82.2% (81.5–83.0) | 1.548 (1.528–1.571) | +9.1 (+8.2 to +10.0) |
| 6–10  | 343   | 26488 | 45.7% (45.0–46.5) | 76.0% (75.3–76.6) | 1.759 (1.737–1.784) | +1.4 (+1.0 to +1.7)  |
| 11–20 | 343   | 52823 | 48.0% (47.3–48.6) | 75.0% (74.4–75.7) | 1.823 (1.796–1.851) | +0.7 (+0.5 to +0.9)  |
| 21–30 | 343   | 51893 | 47.4% (46.8–48.1) | 70.3% (69.7–70.9) | 2.005 (1.978–2.033) | +0.5 (+0.3 to +0.7)  |

### By map

| map                      | games | steps | top-1             | top-3             | log-loss            | top-1 vs reference  |
| ------------------------ | ----- | ----- | ----------------- | ----------------- | ------------------- | ------------------- |
| All That Glitters v2.2.3 | 132   | 63092 | 49.4% (48.9–50.0) | 76.4% (75.9–76.8) | 1.721 (1.701–1.740) | +1.1 (+0.9 to +1.3) |
| Rosetta 1.4.4            | 92    | 38719 | 50.7% (50.1–51.4) | 78.6% (78.0–79.3) | 1.685 (1.646–1.723) | +1.1 (+0.9 to +1.4) |
| Supreme Isthmus v2.1     | 119   | 55886 | 46.1% (45.6–46.6) | 72.1% (71.6–72.7) | 1.916 (1.893–1.941) | +3.2 (+3.0 to +3.5) |

### By faction

| faction | games | steps | top-1             | top-3             | log-loss            | top-1 vs reference  |
| ------- | ----- | ----- | ----------------- | ----------------- | ------------------- | ------------------- |
| Armada  | 343   | 80482 | 48.0% (47.5–48.5) | 75.4% (74.9–75.9) | 1.784 (1.760–1.810) | +1.9 (+1.7 to +2.1) |
| Cortex  | 343   | 70472 | 49.1% (48.5–49.6) | 75.4% (74.8–76.0) | 1.771 (1.747–1.798) | +2.0 (+1.7 to +2.2) |
| Legion  | 75    | 6743  | 50.4% (49.1–51.7) | 75.0% (73.3–76.4) | 1.857 (1.788–1.931) | +0.3 (-0.3 to +0.8) |

### By era

| era                                 | games | steps | top-1             | top-3             | log-loss            | top-1 vs reference  |
| ----------------------------------- | ----- | ----- | ----------------- | ----------------- | ------------------- | ------------------- |
| Air constructors and mobile jammers | 11    | 5224  | 48.1% (46.1–49.9) | 75.2% (73.8–76.5) | 1.800 (1.731–1.876) | +1.4 (+0.8 to +2.1) |
| August balance patch                | 40    | 19029 | 48.3% (47.2–49.4) | 75.6% (74.5–76.7) | 1.778 (1.729–1.828) | +1.8 (+1.3 to +2.3) |
| July balance patch                  | 99    | 44664 | 49.2% (48.4–50.0) | 76.3% (75.4–77.1) | 1.750 (1.715–1.790) | +1.9 (+1.6 to +2.2) |
| May balance patch                   | 175   | 80387 | 48.4% (48.0–48.9) | 75.1% (74.5–75.7) | 1.790 (1.765–1.817) | +1.8 (+1.6 to +2.0) |
| Season 3                            | 18    | 8393  | 47.4% (45.8–49.0) | 73.4% (71.8–74.9) | 1.861 (1.784–1.938) | +2.7 (+2.0 to +3.6) |

### By map and position

#### All That Glitters v2.2.3

| position | openings | steps | top-1             | top-3             | log-loss            | top-1 vs reference  |
| -------- | -------- | ----- | ----------------- | ----------------- | ------------------- | ------------------- |
| P1       | 132      | 3946  | 48.0% (45.7–50.4) | 73.5% (71.5–75.5) | 1.868 (1.786–1.957) | -0.2 (-0.9 to +0.5) |
| P2       | 131      | 3884  | 46.2% (44.2–48.3) | 70.8% (68.9–72.5) | 1.935 (1.861–2.012) | +1.7 (+0.7 to +2.8) |
| P3       | 132      | 3946  | 47.2% (45.2–49.2) | 76.8% (74.9–78.4) | 1.721 (1.657–1.797) | +1.1 (+0.4 to +2.0) |
| P4       | 134      | 4000  | 50.5% (48.4–52.6) | 76.8% (74.9–78.7) | 1.753 (1.657–1.863) | +1.3 (+0.6 to +2.0) |
| P5       | 133      | 3982  | 46.2% (44.2–48.1) | 72.7% (70.8–74.7) | 1.859 (1.780–1.938) | +1.0 (+0.4 to +1.6) |
| P6       | 131      | 3930  | 52.6% (50.9–54.7) | 80.3% (78.9–81.9) | 1.552 (1.497–1.605) | +1.1 (+0.5 to +1.6) |
| P7       | 129      | 3869  | 52.6% (50.7–54.5) | 79.7% (78.0–81.2) | 1.556 (1.511–1.605) | +0.9 (+0.3 to +1.5) |
| P8       | 133      | 3990  | 51.3% (49.5–53.1) | 79.0% (77.4–80.6) | 1.602 (1.547–1.660) | +1.8 (+1.1 to +2.5) |
| P9       | 132      | 3958  | 47.9% (45.6–50.1) | 73.6% (71.9–75.4) | 1.838 (1.761–1.926) | +0.7 (+0.0 to +1.3) |
| P10      | 133      | 3969  | 47.2% (45.3–49.1) | 72.3% (70.5–74.2) | 1.902 (1.822–1.975) | +1.4 (+0.5 to +2.4) |
| P11      | 131      | 3926  | 49.8% (48.0–51.6) | 78.4% (76.8–80.0) | 1.640 (1.579–1.701) | +1.5 (+0.7 to +2.4) |
| P12      | 129      | 3853  | 49.4% (47.2–51.4) | 74.9% (73.2–76.5) | 1.765 (1.699–1.834) | +1.0 (+0.3 to +1.6) |
| P13      | 134      | 3992  | 46.0% (43.9–48.0) | 74.8% (72.9–76.5) | 1.816 (1.745–1.893) | +0.2 (-0.4 to +0.8) |
| P14      | 130      | 3900  | 51.8% (49.7–53.7) | 78.9% (77.1–80.6) | 1.619 (1.557–1.683) | +1.0 (+0.2 to +1.7) |
| P15      | 135      | 4050  | 52.7% (50.6–54.6) | 80.8% (79.4–82.2) | 1.528 (1.485–1.578) | +1.7 (+1.1 to +2.2) |
| P16      | 130      | 3897  | 51.6% (49.5–53.7) | 78.6% (77.1–80.1) | 1.586 (1.532–1.643) | +1.4 (+0.7 to +2.1) |

#### Rosetta 1.4.4

| position | openings | steps | top-1             | top-3             | log-loss            | top-1 vs reference  |
| -------- | -------- | ----- | ----------------- | ----------------- | ------------------- | ------------------- |
| P1       | 88       | 2640  | 51.4% (49.3–53.6) | 78.9% (76.9–80.7) | 1.637 (1.566–1.711) | +1.3 (+0.2 to +2.5) |
| P2       | 87       | 2602  | 50.4% (47.7–52.8) | 77.2% (74.1–80.0) | 2.007 (1.612–2.533) | -0.8 (-1.6 to +0.1) |
| P3       | 88       | 2640  | 53.9% (51.6–56.5) | 79.8% (77.9–81.9) | 1.624 (1.525–1.731) | +1.6 (+0.4 to +2.9) |
| P4       | 58       | 1740  | 46.4% (43.2–49.4) | 71.7% (68.9–74.6) | 1.950 (1.828–2.067) | +1.0 (+0.0 to +2.1) |
| P5       | 71       | 2130  | 47.9% (45.1–50.7) | 71.4% (69.0–73.5) | 1.968 (1.857–2.102) | +1.9 (+0.8 to +3.0) |
| P6       | 82       | 2460  | 49.3% (47.4–51.5) | 79.6% (77.6–81.7) | 1.637 (1.568–1.703) | +1.3 (+0.4 to +2.2) |
| P7       | 86       | 2580  | 50.6% (48.7–52.5) | 81.7% (79.9–83.6) | 1.520 (1.460–1.581) | +1.4 (+0.7 to +2.3) |
| P8       | 83       | 2490  | 53.2% (51.1–55.5) | 82.7% (80.6–84.7) | 1.519 (1.457–1.579) | +1.7 (+1.0 to +2.5) |
| P9       | 90       | 2700  | 49.2% (47.0–51.4) | 77.3% (75.4–79.2) | 1.721 (1.653–1.788) | +0.5 (-0.9 to +1.7) |
| P10      | 80       | 2400  | 51.2% (49.0–53.5) | 80.7% (78.9–82.3) | 1.557 (1.491–1.627) | +1.3 (+0.3 to +2.2) |
| P11      | 90       | 2700  | 50.7% (48.4–53.3) | 79.7% (77.9–81.6) | 1.632 (1.560–1.701) | +1.7 (+0.7 to +2.7) |
| P12      | 60       | 1800  | 45.6% (42.8–48.4) | 72.5% (69.8–75.3) | 1.887 (1.785–1.988) | +0.2 (-0.8 to +1.1) |
| P13      | 75       | 2247  | 47.9% (45.7–50.1) | 70.0% (67.8–72.3) | 2.015 (1.902–2.132) | +1.4 (+0.5 to +2.3) |
| P14      | 87       | 2610  | 52.2% (50.0–54.5) | 82.6% (81.0–84.1) | 1.566 (1.503–1.636) | +0.7 (+0.0 to +1.3) |
| P15      | 87       | 2610  | 54.1% (52.2–56.1) | 83.3% (81.6–84.8) | 1.436 (1.371–1.505) | +0.9 (+0.2 to +1.5) |
| P16      | 79       | 2370  | 54.0% (51.3–56.7) | 83.1% (81.4–85.0) | 1.498 (1.432–1.566) | +1.5 (+0.6 to +2.4) |

#### Supreme Isthmus v2.1

| position | openings | steps | top-1             | top-3             | log-loss            | top-1 vs reference  |
| -------- | -------- | ----- | ----------------- | ----------------- | ------------------- | ------------------- |
| P1       | 112      | 3360  | 46.4% (44.4–48.5) | 71.1% (69.1–72.9) | 1.946 (1.871–2.029) | +3.8 (+2.8 to +4.6) |
| P2       | 117      | 3504  | 47.6% (46.0–49.4) | 79.5% (78.0–81.0) | 1.564 (1.501–1.632) | +3.7 (+2.7 to +4.6) |
| P3       | 119      | 3549  | 44.8% (42.7–46.8) | 69.1% (67.4–70.9) | 1.945 (1.866–2.030) | +4.2 (+3.1 to +5.3) |
| P4       | 119      | 3187  | 44.5% (42.0–46.8) | 69.8% (67.7–71.8) | 2.139 (2.035–2.256) | +0.1 (-0.5 to +0.7) |
| P5       | 121      | 3582  | 44.3% (42.1–46.6) | 71.4% (69.3–73.5) | 1.913 (1.834–1.987) | +2.3 (+1.5 to +3.0) |
| P6       | 122      | 3642  | 48.4% (46.3–50.6) | 73.5% (71.6–75.3) | 1.838 (1.766–1.915) | +1.6 (+0.8 to +2.5) |
| P7       | 121      | 3604  | 45.9% (44.0–47.7) | 74.9% (73.1–76.5) | 1.799 (1.733–1.872) | +6.2 (+4.7 to +7.7) |
| P8       | 119      | 3562  | 44.6% (42.7–46.6) | 68.6% (66.8–70.4) | 2.142 (2.059–2.223) | +1.9 (+1.3 to +2.5) |
| P9       | 119      | 3557  | 46.0% (44.2–47.7) | 69.9% (68.0–71.9) | 1.971 (1.897–2.057) | +4.2 (+3.3 to +5.0) |
| P10      | 120      | 3583  | 49.2% (47.2–51.3) | 78.3% (76.3–80.4) | 1.585 (1.496–1.678) | +5.4 (+4.3 to +6.6) |
| P11      | 119      | 3525  | 45.4% (43.3–47.5) | 69.1% (67.3–70.9) | 1.960 (1.892–2.036) | +4.6 (+3.4 to +5.7) |
| P12      | 121      | 3256  | 44.8% (42.5–47.1) | 70.1% (67.9–72.2) | 2.214 (2.088–2.349) | -0.3 (-1.0 to +0.5) |
| P13      | 116      | 3455  | 44.9% (42.4–47.4) | 72.0% (69.6–74.2) | 1.908 (1.819–2.014) | +2.3 (+1.5 to +3.1) |
| P14      | 121      | 3582  | 48.5% (46.6–50.4) | 72.8% (70.8–74.8) | 1.832 (1.763–1.904) | +1.9 (+1.2 to +2.5) |
| P15      | 117      | 3483  | 46.5% (44.7–48.4) | 75.0% (73.1–76.9) | 1.786 (1.700–1.863) | +7.0 (+5.5 to +8.5) |
| P16      | 116      | 3455  | 45.4% (43.4–47.7) | 68.7% (66.8–70.6) | 2.169 (2.061–2.284) | +2.2 (+1.5 to +2.9) |

## Findings

- **Counting sets a high bar.** The chosen n-gram predicts the next step right
  48.6% of the time and has it among its three guesses 75.4% of the time, on
  test; the best top-1 is 49.6%. Repeating the previous step already gives
  42.6% top-1: openings are runs of extractors and energy. Unit frequencies
  alone reach 18%.
- **Short histories carry most of it.** Going from one previous step to two
  gains 2.5 points of top-1, from two to three 1.4. A three-step history with
  the map and position gains another 1.5 points of top-1, but its log-loss is
  worse than that of the trigram with the map and position: its probabilities
  are too sure on the little data per context.
- **The map and the role help, the exact position adds little.** Telling the
  trigram the map and the role gains 1.9 points of top-1 and 0.12 nats of
  log-loss over the faction trigram; the position instead of the role is as
  good in top-1 and a little worse in log-loss. On Supreme Isthmus the gain is
  3.2 points, and up to 7.0 at a single position (`P15`). The exceptions are
  the two pond positions (`P4`, `P12`), whose role is front like four other
  Isthmus positions: the role tells the model nothing there.
- **The gain is at the start.** The role model gains 9.1 points at steps 2 to
  5, where the first factory and the first energy are chosen, and half a point
  after step 10. The first step is right 93% of the time with or without it.
- **No era stands out.** Top-1 is 47.4 to 49.2% in every opening era, inside
  the intervals of one another, as ADR 0012 expected.
- **Raw orders flatter.** On raw orders, where a drag counts each building,
  the faction trigram scores 59.0% top-1, the number the earlier measurements
  in [`maps/`](maps/README.md) report. On steps it scores 46.7%.
- **Against StarCraft.** Justesen and Risi (2017) report a top-1 error of
  54.6% and a top-3 error of 22.9% predicting the next build in StarCraft from
  replays. Here the errors are 51.4% and 24.6%: about the same, on a different
  game and a simpler model.

## The saved model

`python -m reason8.baseline` saves the n-gram with the lowest validation
log-loss to `data/models/ngram_v1.json`: its levels, vocabulary and counts,
what it was trained on (`TrainedOn`: the first and last build and every unit
it can order) and the dataset's manifest. `load_model()` reads it back and
`check_model()` runs `check_game_version()`
([ADR 0012](adr/0012-keep-the-time-window-across-balance-patches.md)): it
warns when the game is a month or an opening-changing patch ahead of the
training data and refuses when the model can order a unit the game does not
have.

## Using it in the game

The in-game side plays `ai/Reason8/openings.json`
([`in-game.md`](in-game.md)). Exporting this model there is not a format
change alone:

Key
: `openings.json` has one opening per side (Armada, Cortex), and `opening.as`
  picks it by the AI's side. A per-position model needs openings keyed by map
  and spawn point, and the AI has to find its own spawn point in the game:
  from its start point and the recommended positions the lobby sends
  (`mapmetadata_startpos`), which the scripts may not be able to read.

A sequence, not a distribution
: The file holds one fixed list of steps. The model gives the next step's
  probabilities; a list has to be decoded from it. Taking the most likely step
  each time loops (an extractor after two extractors is again most likely), so
  the export needs a decoding rule, for example the most common opening of the
  position up to its first factory, or a beam search with a length limit.

Drags
: A merged step says "wind turbines", not how many. The export needs the
  count, from the dataset's repeats.

Builders
: The file splits an opening into the commander's structures and each
  factory's units. The dataset tells structures from factory units (`kind`)
  but not which builder took a structure; after the first two or three minutes
  constructors build too, and the file has no place for them.

Task types
: Every structure needs a BARb task type in `tasks` (extractor, energy,
  factory, defence, radar, ...). Making that table for the 70 or so units that
  cover 99% of the orders of a faction is a small, separate job.

The first three need a change to `opening.as` and the export; until then a
single opening per side can be exported by hand from the per-position tables
of [`openings-dataset.md`](openings-dataset.md).
