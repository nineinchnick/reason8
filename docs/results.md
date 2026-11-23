# Results: predicting the next build

The numbers later models are compared against. Every model predicts the unit
of the next step of an opening, the orders of one drag merged into one step,
from the steps before it and what is known before the game: the player's
faction, the map and the start position. An opening ends at the player's first
contact with the enemy
([ADR 0012](decisions/0012-end-openings-at-first-contact.md)). The protocol is
[ADR 0013](decisions/0013-evaluate-on-held-out-games.md), the data
[`openings-dataset.md`](reference/openings-dataset.md). Code:
`reason8/models/`.

```sh
uv run reason8 baseline                 # validation: compare and choose
uv run reason8 baseline --split test    # the tables below
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
: The next unit after the previous one, two or three steps of the same
  faction. The start of the opening counts as a step, so the first steps are
  predicted from what players of the faction do first.

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

The dataset `openings_v2` as built on 2026-11-22 from 5,066 parsed replays of
the slice ([`openings-dataset.md`](reference/openings-dataset.md)): 4,031
training games, 448 validation games and 492 test games, with openings that
end at first contact. The models were compared on validation and the tables
below are on test. With more of the slice parsed, rebuild the dataset and run
both commands again; the split of a game never changes, so the new numbers
replace these.

## Validation

| model                              | top-1             | top-3             | log-loss            |
| ---------------------------------- | ----------------- | ----------------- | ------------------- |
| uniform                            | 0.0% (0.0–0.0)    | 0.0% (0.0–0.0)    | 6.064 (6.064–6.064) |
| unit frequency                     | 9.7% (9.4–10.0)   | 25.5% (24.9–26.0) | 3.974 (3.948–4.002) |
| unit frequency per faction         | 18.3% (18.0–18.6) | 37.5% (37.0–38.0) | 3.162 (3.141–3.184) |
| repeat the previous step           | 42.9% (42.5–43.2) | 58.5% (58.1–58.9) | 2.597 (2.577–2.617) |
| bigram, faction                    | 44.6% (44.3–45.0) | 70.3% (69.9–70.6) | 1.974 (1.961–1.989) |
| trigram, faction                   | 47.4% (47.0–47.8) | 73.7% (73.4–74.0) | 1.838 (1.824–1.852) |
| 4-gram, faction                    | 48.8% (48.4–49.1) | 75.3% (75.0–75.6) | 1.800 (1.785–1.816) |
| trigram, faction and map           | 48.7% (48.4–49.0) | 75.6% (75.3–75.9) | 1.789 (1.773–1.806) |
| trigram, faction, map and role     | 49.4% (49.1–49.7) | 76.9% (76.5–77.2) | 1.715 (1.700–1.730) |
| trigram, faction, map and position | 49.6% (49.3–49.9) | 76.9% (76.7–77.2) | 1.724 (1.710–1.738) |
| 4-gram, faction, map and position  | 50.5% (50.2–50.8) | 77.3% (77.0–77.7) | 1.771 (1.753–1.788) |

The lowest log-loss is `trigram, faction, map and role` (1.715), which is the
model the detailed tables are about and the one that is saved.

## Test

Trained on 4031 games (63634 openings), scored on the test split: 492 games,
7764 openings, the first 30 steps of each. Intervals are 95%, from resampling
games.

### All models

| model                              | top-1             | top-3             | log-loss            |
| ---------------------------------- | ----------------- | ----------------- | ------------------- |
| uniform                            | 0.0% (0.0–0.0)    | 0.0% (0.0–0.0)    | 6.064 (6.064–6.064) |
| unit frequency                     | 9.6% (9.3–9.8)    | 25.3% (24.7–25.9) | 3.954 (3.929–3.980) |
| unit frequency per faction         | 18.5% (18.1–18.8) | 37.7% (37.2–38.2) | 3.140 (3.120–3.160) |
| repeat the previous step           | 42.8% (42.4–43.1) | 58.4% (58.0–58.7) | 2.591 (2.572–2.611) |
| bigram, faction                    | 44.7% (44.4–45.1) | 70.6% (70.3–71.0) | 1.964 (1.951–1.977) |
| trigram, faction                   | 47.5% (47.1–47.9) | 73.9% (73.6–74.2) | 1.825 (1.812–1.838) |
| 4-gram, faction                    | 49.0% (48.6–49.3) | 75.6% (75.3–75.9) | 1.783 (1.769–1.797) |
| trigram, faction and map           | 48.8% (48.4–49.1) | 75.8% (75.5–76.1) | 1.773 (1.757–1.787) |
| trigram, faction, map and role     | 49.5% (49.2–49.7) | 77.1% (76.8–77.4) | 1.700 (1.687–1.714) |
| trigram, faction, map and position | 49.6% (49.3–49.9) | 77.2% (76.9–77.5) | 1.710 (1.696–1.723) |
| 4-gram, faction, map and position  | 50.8% (50.5–51.1) | 77.7% (77.4–78.0) | 1.751 (1.735–1.767) |

215504 steps scored per model. Chosen on validation log-loss:
`trigram, faction, map and role`.

`trigram, faction` on raw orders (drags not merged), for comparison with the
measurements in docs/research/game-versions.md and docs/research/maps/: 59.2%
(58.9–59.5), 81.0% (80.7–81.2), 1.495 (1.485–1.505) over 225449 orders.

The tables below are for `trigram, faction, map and role`. The last column is
its top-1 minus that of `trigram, faction` on the same steps, in points, with
a paired interval.

### By step of the opening

| step  | games | steps | top-1             | top-3             | log-loss            | top-1 vs reference  |
| ----- | ----- | ----- | ----------------- | ----------------- | ------------------- | ------------------- |
| 1     | 492   | 7764  | 93.4% (92.6–94.0) | 99.2% (99.0–99.4) | 0.209 (0.186–0.230) | +0.0 (+0.0 to +0.0) |
| 2–5   | 492   | 31047 | 46.5% (45.8–47.1) | 82.7% (82.1–83.2) | 1.501 (1.485–1.518) | +8.0 (+7.2 to +8.8) |
| 6–10  | 492   | 38779 | 45.8% (45.2–46.4) | 76.9% (76.4–77.4) | 1.710 (1.692–1.728) | +1.4 (+1.0 to +1.6) |
| 11–20 | 492   | 75377 | 48.4% (47.9–48.8) | 76.1% (75.6–76.5) | 1.772 (1.752–1.790) | +0.9 (+0.7 to +1.0) |
| 21–30 | 492   | 62537 | 49.1% (48.6–49.6) | 72.9% (72.4–73.4) | 1.893 (1.872–1.914) | +0.9 (+0.7 to +1.1) |

### By map

| map                      | games | steps | top-1             | top-3             | log-loss            | top-1 vs reference  |
| ------------------------ | ----- | ----- | ----------------- | ----------------- | ------------------- | ------------------- |
| All That Glitters v2.2.3 | 190   | 87770 | 50.1% (49.6–50.5) | 77.7% (77.3–78.0) | 1.660 (1.645–1.675) | +0.9 (+0.7 to +1.0) |
| Rosetta 1.4.4            | 128   | 53308 | 51.9% (51.4–52.3) | 80.4% (79.9–80.8) | 1.588 (1.565–1.614) | +1.7 (+1.4 to +2.0) |
| Supreme Isthmus v2.1     | 174   | 74426 | 47.0% (46.6–47.5) | 74.1% (73.6–74.5) | 1.830 (1.809–1.848) | +3.5 (+3.3 to +3.7) |

### By faction

| faction | games | steps  | top-1             | top-3             | log-loss            | top-1 vs reference  |
| ------- | ----- | ------ | ----------------- | ----------------- | ------------------- | ------------------- |
| Armada  | 492   | 109194 | 49.2% (48.7–49.5) | 77.0% (76.6–77.4) | 1.703 (1.685–1.722) | +2.1 (+1.9 to +2.3) |
| Cortex  | 492   | 95200  | 49.7% (49.3–50.2) | 77.2% (76.8–77.6) | 1.688 (1.669–1.706) | +1.9 (+1.7 to +2.2) |
| Legion  | 104   | 11110  | 50.2% (49.1–51.3) | 77.2% (76.2–78.4) | 1.782 (1.732–1.838) | +0.5 (+0.0 to +1.0) |

### By era

| era                                 | games | steps | top-1             | top-3             | log-loss            | top-1 vs reference  |
| ----------------------------------- | ----- | ----- | ----------------- | ----------------- | ------------------- | ------------------- |
| Air constructors and mobile jammers | 144   | 64061 | 49.3% (48.8–49.9) | 77.2% (76.6–77.8) | 1.695 (1.671–1.716) | +2.1 (+1.8 to +2.3) |
| August balance patch                | 56    | 25000 | 49.4% (48.5–50.3) | 77.3% (76.4–78.2) | 1.682 (1.645–1.720) | +1.9 (+1.4 to +2.4) |
| July balance patch                  | 99    | 42508 | 50.2% (49.3–50.9) | 77.8% (77.0–78.6) | 1.683 (1.650–1.721) | +1.8 (+1.5 to +2.2) |
| May balance patch                   | 175   | 76144 | 49.3% (48.8–49.8) | 76.8% (76.2–77.3) | 1.714 (1.690–1.739) | +1.9 (+1.6 to +2.2) |
| Season 3                            | 18    | 7791  | 48.4% (46.9–50.1) | 74.8% (73.1–76.5) | 1.776 (1.700–1.850) | +2.8 (+1.9 to +3.9) |

### By map and position

#### All That Glitters v2.2.3

| position | openings | steps | top-1             | top-3             | log-loss            | top-1 vs reference  |
| -------- | -------- | ----- | ----------------- | ----------------- | ------------------- | ------------------- |
| P1       | 190      | 5404  | 49.2% (47.4–51.1) | 75.9% (74.3–77.3) | 1.780 (1.712–1.845) | -0.2 (-0.9 to +0.5) |
| P2       | 187      | 5190  | 46.4% (44.6–48.0) | 71.8% (70.4–73.4) | 1.872 (1.810–1.928) | +1.7 (+0.9 to +2.4) |
| P3       | 190      | 5686  | 47.3% (45.8–48.9) | 76.9% (75.5–78.2) | 1.705 (1.646–1.762) | +0.5 (-0.0 to +1.1) |
| P4       | 192      | 5586  | 51.1% (49.3–52.8) | 77.4% (75.8–78.8) | 1.698 (1.633–1.771) | +1.4 (+0.7 to +2.1) |
| P5       | 193      | 5239  | 47.8% (46.0–49.5) | 75.4% (73.8–76.9) | 1.763 (1.701–1.826) | +0.7 (+0.1 to +1.3) |
| P6       | 189      | 5546  | 52.8% (51.2–54.5) | 81.2% (79.9–82.3) | 1.501 (1.454–1.551) | +0.7 (+0.2 to +1.2) |
| P7       | 189      | 5632  | 53.1% (51.4–54.6) | 81.1% (79.9–82.3) | 1.512 (1.473–1.554) | +0.5 (-0.1 to +1.1) |
| P8       | 190      | 5554  | 52.1% (50.4–53.7) | 79.9% (78.6–81.0) | 1.536 (1.492–1.582) | +0.8 (+0.3 to +1.4) |
| P9       | 190      | 5395  | 47.5% (45.7–49.3) | 74.3% (72.9–75.6) | 1.819 (1.758–1.896) | -0.2 (-0.7 to +0.4) |
| P10      | 191      | 5288  | 46.8% (45.1–48.6) | 73.1% (71.6–74.5) | 1.846 (1.787–1.905) | +2.6 (+1.8 to +3.4) |
| P11      | 188      | 5635  | 48.9% (47.5–50.3) | 78.8% (77.5–80.0) | 1.625 (1.577–1.673) | +0.7 (+0.0 to +1.3) |
| P12      | 187      | 5458  | 50.9% (49.3–52.7) | 76.5% (75.2–77.9) | 1.696 (1.640–1.749) | +0.8 (+0.3 to +1.5) |
| P13      | 197      | 5423  | 47.4% (45.6–49.2) | 77.6% (76.2–79.0) | 1.698 (1.640–1.756) | +0.3 (-0.4 to +1.0) |
| P14      | 187      | 5535  | 52.9% (51.2–54.5) | 80.0% (78.6–81.4) | 1.549 (1.491–1.610) | +0.8 (+0.2 to +1.4) |
| P15      | 194      | 5778  | 53.6% (52.1–55.2) | 81.6% (80.5–82.8) | 1.470 (1.429–1.508) | +1.3 (+0.7 to +1.8) |
| P16      | 186      | 5421  | 52.6% (51.0–54.3) | 80.4% (79.3–81.5) | 1.527 (1.483–1.570) | +1.2 (+0.6 to +1.8) |

#### Rosetta 1.4.4

| position | openings | steps | top-1             | top-3             | log-loss            | top-1 vs reference  |
| -------- | -------- | ----- | ----------------- | ----------------- | ------------------- | ------------------- |
| P1       | 131      | 3481  | 50.7% (48.8–52.5) | 79.7% (78.0–81.3) | 1.594 (1.531–1.663) | +1.8 (+0.7 to +2.9) |
| P2       | 122      | 3651  | 50.8% (48.6–52.8) | 78.6% (76.0–80.8) | 1.815 (1.574–2.149) | +0.6 (-0.1 to +1.3) |
| P3       | 125      | 3439  | 55.0% (52.9–56.9) | 82.7% (81.1–84.2) | 1.470 (1.411–1.538) | +1.6 (+0.5 to +2.9) |
| P4       | 106      | 2388  | 49.2% (47.3–51.6) | 76.8% (75.0–78.8) | 1.752 (1.664–1.835) | +1.6 (+0.0 to +3.1) |
| P5       | 118      | 2914  | 49.3% (47.1–51.5) | 74.4% (72.7–76.1) | 1.810 (1.723–1.896) | +2.4 (+1.4 to +3.6) |
| P6       | 126      | 3527  | 52.3% (50.7–54.0) | 81.4% (79.9–83.0) | 1.521 (1.469–1.575) | +2.3 (+1.2 to +3.4) |
| P7       | 119      | 3569  | 51.1% (49.4–52.7) | 81.8% (80.2–83.4) | 1.510 (1.459–1.567) | +1.1 (+0.3 to +1.8) |
| P8       | 126      | 3664  | 55.2% (53.4–56.9) | 83.3% (81.8–84.8) | 1.433 (1.380–1.486) | +2.3 (+1.3 to +3.3) |
| P9       | 128      | 3273  | 51.0% (49.1–52.8) | 79.4% (77.8–81.0) | 1.607 (1.550–1.669) | +1.7 (+0.6 to +2.9) |
| P10      | 116      | 3480  | 50.6% (48.9–52.3) | 80.2% (78.5–81.8) | 1.568 (1.506–1.628) | +0.9 (+0.2 to +1.5) |
| P11      | 129      | 3554  | 51.9% (49.8–54.1) | 81.6% (80.3–83.0) | 1.560 (1.495–1.627) | +2.5 (+1.3 to +3.7) |
| P12      | 107      | 2479  | 47.4% (45.0–49.7) | 78.7% (76.9–80.5) | 1.703 (1.632–1.781) | +1.4 (-0.1 to +2.9) |
| P13      | 122      | 3152  | 50.1% (48.3–51.9) | 74.5% (73.0–76.2) | 1.846 (1.764–1.923) | +2.8 (+1.8 to +3.9) |
| P14      | 125      | 3538  | 53.8% (52.1–55.6) | 83.2% (82.0–84.4) | 1.475 (1.426–1.524) | +2.9 (+1.7 to +4.0) |
| P15      | 120      | 3598  | 53.3% (51.7–55.1) | 83.3% (81.8–84.7) | 1.446 (1.387–1.508) | +0.5 (-0.1 to +1.0) |
| P16      | 124      | 3601  | 55.2% (53.1–57.0) | 82.8% (81.2–84.3) | 1.451 (1.394–1.514) | +0.5 (-0.6 to +1.4) |

#### Supreme Isthmus v2.1

| position | openings | steps | top-1             | top-3             | log-loss            | top-1 vs reference  |
| -------- | -------- | ----- | ----------------- | ----------------- | ------------------- | ------------------- |
| P1       | 167      | 4832  | 46.1% (44.5–47.7) | 71.8% (70.4–73.2) | 1.910 (1.848–1.973) | +3.1 (+2.4 to +3.8) |
| P2       | 173      | 5178  | 48.8% (47.2–50.2) | 79.6% (78.2–81.0) | 1.544 (1.488–1.607) | +4.5 (+3.6 to +5.3) |
| P3       | 175      | 4795  | 46.1% (44.3–47.8) | 71.5% (70.0–72.9) | 1.847 (1.787–1.904) | +4.1 (+3.2 to +5.1) |
| P4       | 173      | 4569  | 44.2% (42.4–46.2) | 70.6% (68.9–72.4) | 2.104 (2.016–2.200) | -0.0 (-0.5 to +0.5) |
| P5       | 177      | 3912  | 46.3% (44.2–48.3) | 76.3% (74.6–77.9) | 1.710 (1.647–1.774) | +2.7 (+1.9 to +3.5) |
| P6       | 178      | 3879  | 50.4% (48.4–52.4) | 77.2% (75.6–78.7) | 1.664 (1.608–1.721) | +2.3 (+1.5 to +3.1) |
| P7       | 174      | 5181  | 46.1% (44.7–47.7) | 75.1% (73.6–76.4) | 1.782 (1.724–1.844) | +6.5 (+5.2 to +7.7) |
| P8       | 174      | 4901  | 46.2% (44.5–47.8) | 70.5% (68.9–71.8) | 2.067 (2.003–2.139) | +2.4 (+1.8 to +3.0) |
| P9       | 172      | 5002  | 46.4% (45.0–47.9) | 71.7% (70.2–73.1) | 1.904 (1.844–1.961) | +3.4 (+2.6 to +4.2) |
| P10      | 176      | 5244  | 49.1% (47.4–50.9) | 78.7% (77.3–80.3) | 1.591 (1.514–1.665) | +5.8 (+4.9 to +6.9) |
| P11      | 175      | 4729  | 47.1% (45.4–48.6) | 71.2% (69.8–72.6) | 1.838 (1.785–1.895) | +4.6 (+3.7 to +5.5) |
| P12      | 175      | 4581  | 45.0% (43.1–46.9) | 71.3% (69.7–73.0) | 2.119 (2.017–2.232) | -0.3 (-0.8 to +0.2) |
| P13      | 172      | 3863  | 46.6% (44.4–48.8) | 76.8% (75.0–78.6) | 1.702 (1.636–1.762) | +3.0 (+2.2 to +3.7) |
| P14      | 176      | 3857  | 51.2% (49.1–53.0) | 77.9% (76.2–79.6) | 1.622 (1.563–1.684) | +2.0 (+1.2 to +2.7) |
| P15      | 173      | 5158  | 46.0% (44.3–47.6) | 75.3% (73.7–76.8) | 1.783 (1.713–1.855) | +7.1 (+5.7 to +8.4) |
| P16      | 170      | 4745  | 47.8% (45.9–49.6) | 70.5% (69.0–72.0) | 2.037 (1.961–2.120) | +3.0 (+2.4 to +3.6) |

## Until first contact, against the first 8 minutes

The same replays built both ways (`--cutoff window` builds the 8-minute
openings), the same games in every split, `trigram, faction, map and role`,
which validation chooses in both, on test:

| trained on          | scored on           | openings | steps  | top-1             | top-3             | log-loss            |
| ------------------- | ------------------- | -------- | ------ | ----------------- | ----------------- | ------------------- |
| the first 8 minutes | the first 8 minutes | 7682     | 228649 | 48.5% (48.2–48.8) | 75.5% (75.2–75.9) | 1.767 (1.753–1.781) |
| the first 8 minutes | until first contact | 7764     | 215504 | 49.2% (48.9–49.5) | 76.7% (76.4–77.1) | 1.715 (1.702–1.727) |
| until first contact | until first contact | 7764     | 215504 | 49.5% (49.2–49.7) | 77.1% (76.8–77.4) | 1.700 (1.687–1.714) |

The middle row is `reason8 baseline --split test --train-dataset` with the
8-minute build. On validation the first and the last row are 48.4%, 75.3% and
1.780 against 49.4%, 76.9% and 1.715.

## Findings

- **Counting sets a high bar.** The chosen n-gram predicts the next step right
  49.5% of the time and has it among its three guesses 77.1% of the time, on
  test; the best top-1 is 50.8%. Repeating the previous step already gives
  42.8% top-1: openings are runs of extractors and energy. Unit frequencies
  alone reach 18.5%.
- **Steps before first contact are easier to predict, a little.** Scored on
  the openings that end at first contact, the model trained on 8-minute
  openings gets 49.2% of the steps right instead of 48.5%, and 1.715 instead
  of 1.767 nats: the steps left out were predicted worse than the rest.
  Trained on the cut openings as well, it gains another 0.3 points and 0.015
  nats with two thirds of the training orders, a difference inside the two
  intervals (which are not paired). The change shows at steps 21 to 30, which
  only openings with a late contact reach: 49.1% top-1 and 72.9% top-3 there,
  against 47.2% and 70.3% in the 8-minute openings.
- **Fewer steps are scored.** 215,504 instead of 228,649: an opening that ends
  before its 30th step is scored whole, and 68% of the openings reach 30
  steps, against 96% of the 8-minute ones.
- **Short histories carry most of it.** Going from one previous step to two
  gains 2.8 points of top-1, from two to three 1.5. A three-step history with
  the map and position gains another 1.2 points of top-1, but its log-loss is
  worse than that of the trigram with the map and position: its probabilities
  are too sure on the little data per context.
- **The map and the role help, the exact position adds little.** Telling the
  trigram the map and the role gains 2.0 points of top-1 and 0.12 nats of
  log-loss over the faction trigram; the position instead of the role is as
  good in top-1 and a little worse in log-loss. On Supreme Isthmus the gain is
  3.5 points, and up to 7.1 at a single position (`P15`). The exceptions are
  the two pond positions (`P4`, `P12`), whose role is front like four other
  Isthmus positions: the role tells the model nothing there.
- **The gain is at the start.** The role model gains 8.0 points at steps 2 to
  5, where the first factory and the first energy are chosen, and about a
  point after step 10. The first step is right 93% of the time with or without
  it.
- **No era stands out.** Top-1 is 48.4 to 50.2% in every opening era, inside
  the intervals of one another, as ADR 0015 expected.
- **Raw orders flatter.** On raw orders, where a drag counts each building,
  the faction trigram scores 59.2% top-1, the number the earlier measurements
  in [`maps/`](research/maps/README.md) report. On steps it scores 47.5%.
- **Against StarCraft.** Justesen and Risi (2017) report a top-1 error of
  54.6% and a top-3 error of 22.9% predicting the next build in StarCraft from
  replays. Here the errors are 50.5% and 22.9%: about the same, on a different
  game and a simpler model.

## The saved model

`reason8 baseline` saves the n-gram with the lowest validation log-loss to
`data/models/ngram_v2.json`: its levels, vocabulary and counts, what it was
trained on (`TrainedOn`: the first and last build and every unit it can order)
and the dataset's manifest. `load_model()` reads it back and `check_model()`
runs `check_game_version()`
([ADR 0015](decisions/0015-train-across-balance-patches.md)): it warns when
the game is a month or an opening-changing patch ahead of the training data
and refuses when the model can order a unit the game does not have.

## Using it in the game

The in-game side plays `ai/Reason8/openings.json`
([`in-game.md`](reference/in-game.md)). Exporting this model there is not a
format change alone:

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
of [`openings-dataset.md`](reference/openings-dataset.md).
