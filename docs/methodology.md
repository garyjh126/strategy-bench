# Methodology

_Draft. Covers what is implemented so far: Kuhn and Leduc poker, `direct` and `play` modes, and
the reporting site._

## What is measured

StrategyBench measures how much value a best-responding opponent could extract from an AI
subject's behaviour in a small two-player zero-sum poker game, compared with equilibrium play.

Results describe **the model plus this prompt plus these sampling settings on this game**.
They are not a measure of general poker or reasoning ability.

## Setup

* Games are OpenSpiel games. Seat 0 is "Player 1" in prompts.
* An **information state** (infostate) is what the acting player knows: their private card(s)
  and the public action history.
* A **behavioural strategy** gives a probability distribution over legal actions at each
  infostate.
* The equilibrium reference is the average policy of OpenSpiel's C++ CFR+ after 2,000
  iterations, saved to disk so every run of a game is scored against the same reference.

| Game | Decision infostates | Player 1 value | Reference exploitability |
|---|---|---|---|
| Kuhn poker (`kuhn_poker`) | 12 | −0.05556 (theory −1/18) | 4.4e-5 |
| Leduc poker (`leduc_poker(suit_isomorphism=True)`) | 288 | −0.0856 | 8.5e-5 |

(Values printed by `scripts/run_benchmark.py` as "equilibrium seat values".)

**Leduc uses OpenSpiel's suit-isomorphic variant.** The prompt only ever names ranks (suits do
not matter in Leduc), so two infostates that differ only by suit would get identical prompts. The
suit-isomorphic game deals ranks with the correct probabilities, so its infostates are exactly
what the subject can distinguish: 288 instead of 936, with the same game value.

## Querying the subject

The system prompt states the rules (versioned, e.g. `kuhn-v1`). The user message describes
the seat, the private card, the action history so far and an enumerated list of legal action
labels, and asks for exactly one label. Both seats use the same template.

**Parsing is strict.** After removing surrounding whitespace, quotes, backticks, asterisks and
one trailing period, and ignoring case, the reply must equal exactly one legal label. A reply
that names a real game action which is not legal at that point is counted as *illegal*; anything
else is a *parse failure*. A failed attempt is retried with the same prompt up to 2 times (by
default). Every attempt is counted. A sample that never yields a legal action is recorded as
failed; no action is ever substituted.

## Estimating the strategy (`direct` mode)

Every decision infostate is enumerated with OpenSpiel and the subject is queried there
independently, with a fresh context each time.

* **Text subjects** are sampled N times per infostate. The estimated strategy σ̂ at an
  infostate is the empirical frequency of the valid sampled actions.
* **Distribution subjects** (models that return a probability per offered option in one call)
  are queried once per infostate and the returned probabilities are used directly as σ̂. These
  have no sampling error. Their probabilities may be intended as confidences rather than as a
  mixed strategy, so results report which reading was used.

**Fill rule.** An infostate with fewer than `min_samples` valid samples (default 1) is played
uniformly at random over its legal actions. The number of filled infostates is always
reported.

## Validating by play (`play` mode)

The subject plays complete hands against a fixed opponent (the equilibrium, or uniform random).
Seats alternate every hand. Chance and the opponent are sampled from a per-hand random generator
seeded by the run seed, so a match is reproducible. Each subject decision is a fresh query with
its own sample key, independent of the direct-mode samples. If every attempt at a decision fails,
the subject's action is drawn uniformly from the legal actions and the decision is counted as a
fallback; the number of fallbacks is reported.

**Cross-check.** After a direct run, the exact expected payoff of the estimated strategy σ̂
against the opponent, per seat, is compared with the play-mode mean. They are reported as
agreeing when the difference is within 1.96 combined standard errors (the play-mode standard
error, plus the bootstrap standard error of the exact value). This checks that σ̂ predicts how the
subject actually plays.

Example (mock subject playing 80% equilibrium and 20% uniform, with 5% unparseable replies,
200 samples per infostate, 20,000 hands against the equilibrium, Leduc):

| Seat | Exact (from σ̂) | Simulated | z |
|---|---|---|---|
| Player 1 | −0.2126 | −0.2179 | −0.14 |
| Player 2 | −0.0246 | −0.0267 | −0.06 |

(Produced by `scripts/run_benchmark.py --game leduc --agent cfr-noisy --samples 200 --mode both
--hands 20000 --garbage-rate 0.05 --format-noise`.) With 10,000 hands per seat the 95% interval is
about ±0.075 chips per hand, so play mode is far more expensive per unit of precision than direct
mode, and is used as a check rather than as the headline measurement.

## Metrics

All values are expected payoffs per hand, reported in native units and normalised by the
game's unit (Kuhn: 1 ante, so the two coincide).

| | Definition |
|---|---|
| **M1 exploitability** | OpenSpiel `exploitability(game, σ̂)` = NashConv(σ̂) / 2. In a two-player zero-sum game this is the average, over the two seats, of what a best responder gains against σ̂ beyond the equilibrium value. |
| **M2 best-response gain, seat i** | With the subject in seat i: value of a best response in the other seat against σ̂, minus that seat's equilibrium value. M1 is the mean of the two M2 values (checked by a test). |
| **M3 head-to-head loss, seat i** | Equilibrium value of seat i minus the subject's exact expected payoff in seat i against the equilibrium strategy. |
| **M4 reliability** | Parse-failure rate and illegal-action rate (per attempt), retry rate and sample-failure rate (per sample), and **coverage**: the reach-weighted fraction of infostates with at least k valid samples (default k = 5), with reach measured under σ̂. |

**M3 is weaker than M1.** Against an equilibrium opponent, any strategy that only uses actions
in the equilibrium's support earns exactly the equilibrium value. In Kuhn poker a subject that
plays the right actions with the wrong frequencies therefore has M3 ≈ 0 while still being
exploitable (M1 > 0). M1 is the headline metric for this reason.

## Where a best responder gains

Each run page splits the best-response gain M2 into the situations where it is earned. Fix the
subject's estimated strategy σ̂ in seat *i* and let the other seat *j* switch from its
equilibrium strategy σ\* to a best response BR against σ̂. Then, exactly,

    M2_i  =  M3_i  +  Σ over j's infostates I of  contribution(I)

    contribution(I)  =  reach*(I) · [ q(I, BR(I)) − Σ_a σ*(I, a) · q(I, a) ]

* `reach*(I)` is the probability that *I* is reached when seat *j* plays the equilibrium
  against σ̂ (chance × σ̂ × σ\*).
* `q(I, a)` is the expected payoff to seat *j* of taking action *a* at *I*, given that *I* was
  reached, when *j* best-responds from then on. It is computed from OpenSpiel's
  `BestResponsePolicy`, whose counterfactual values are divided by the infostate's
  counterfactual reach.
* The bracket is the **per-visit edge** of the best response over the equilibrium mix. It is
  never negative, because the best response maximises `q(I, ·)`.

So M3 is what the equilibrium wins without adapting, and each contribution is how often a
situation arises times how much more adapting earns there. The identity is a telescoping
(performance-difference) argument over seat *j*'s decisions; the tests check it to 1e-9 on
Kuhn and Leduc for several strategies, and against hand-computed Kuhn values (for an
always-check/fold Player 1, Player 2's situations "Jack after a check" and "Queen after a
check" contribute 4/9 and 1/3).

The page shows the situations with the largest contributions, with a templated sentence for
each, and the subject's own action frequencies at every infostate against the equilibrium,
ordered by reach (opponent at equilibrium) times total variation distance from the equilibrium.

## Prompt sensitivity

Two optional variants measure how much results depend on wording (`--prompt`):

* `<game>-v1-para`: the same rules, reworded and reordered.
* `<version>+shuffled`: the legal actions listed in a shuffled order, fixed per infostate.

The spread of a model's metrics across these variants is reported alongside its main result.

## Uncertainty

Each bootstrap replicate (200 by default) resamples the valid samples at every infostate with
replacement, keeping that infostate's sample size, and recomputes every metric.

**Plug-in bias.** Exploitability and the best-response gains are maxima over opponent
strategies. For any fixed opponent strategy the subject's estimated payoff is unbiased, but the
best responder picks its strategy using the same noisy estimate, so sampling noise is exploited
and never cancels out: the exploitability of the estimated strategy (the *plug-in* estimate) is
biased upwards. The bias is largest near equilibrium, where the best responder is indifferent
almost everywhere, and the bootstrap replicates are biased upwards again, so a percentile
interval (the 2.5% and 97.5% quantiles of the replicates) sits above the truth.

**What runs report.** For every metric (M1, and M2 and M3 per seat):

* the bias-corrected estimate `max(0, 2·x − mean of replicates)`, where `x` is the plug-in value;
* the basic bootstrap interval `[2·x − q97.5, 2·x − q2.5]`, clipped at 0, which is centred on
  the bias-corrected estimate.

The site shows these, with the plug-in value beside them. `metrics.json` also keeps the
percentile intervals (`ci95_percentile`) and the bootstrap bias. Exact subjects (distribution
clients) have no sampling error and are shown exactly.

**Coverage, measured by simulation.** For scripted strategies with a known exploitability,
`scripts/ci_coverage.py` draws independent datasets of N = 200 samples per infostate, builds
both intervals for each, and counts how often they contain the true value:

| Game | Strategy | True M1 | Mean plug-in (sd) | Mean bias-corrected | Percentile coverage | Basic coverage |
|---|---|---|---|---|---|---|
| Kuhn | uniform | 0.458 | 0.462 (0.023) | 0.461 | 94% | 94% |
| Kuhn | equilibrium | 0.000 | 0.014 (0.006) | 0.008 | 0% | 88% |
| Kuhn | 80% equilibrium, 20% uniform | 0.066 | 0.070 (0.011) | 0.067 | 94% | 94% |
| Leduc | uniform | 2.374 | 2.381 (0.034) | 2.368 | 85% | 88% |
| Leduc | equilibrium | 0.000 | 0.104 (0.021) | 0.062 | 0% | 30% |
| Leduc | 80% equilibrium, 20% uniform | 0.638 | 0.649 (0.039) | 0.630 | 92% | 83% |

(Kuhn: 200 datasets with 200 replicates each, `scripts/ci_coverage.py --game kuhn`. Leduc: 60
datasets with 100 replicates each, `scripts/ci_coverage.py --game leduc --datasets 60
--bootstrap 100`; with 60 datasets each coverage figure is uncertain by about ±4 points.)

What this shows:

* The bias-corrected estimate is closer to the truth than the plug-in estimate in every case,
  but near equilibrium only part of the bias is removed (Leduc: 0.062 against a true 0.000).
* Percentile intervals never covered an equilibrium subject's true value in either game. Basic
  intervals did so 88% of the time in Kuhn but only 30% in Leduc.
* Away from equilibrium both intervals are close to nominal in Kuhn and somewhat below it in
  Leduc; for Leduc's 80/20 mix the basic interval did worse than the percentile one.

So the reported intervals are **approximate**: reasonable for clearly exploitable subjects,
optimistic for subjects close to equilibrium, especially in the larger game. A maximum is not
differentiable at an equilibrium, which is a known limit of the bootstrap. More samples per
infostate is the reliable remedy. A cross-fitted estimate (best response chosen on half the
samples, evaluated on the other half), which is biased downwards and so brackets the truth with
the plug-in value, is a candidate for a later version.

**Example** (equilibrium subject in Kuhn, true exploitability about 0):

| N per infostate | Plug-in | Bias-corrected | Basic 95% interval | Percentile 95% interval |
|---|---|---|---|---|
| 50 | 0.030 | 0.014 | [0.000, 0.038] | [0.022, 0.073] |
| 200 | 0.006 | 0.000 | [0.000, 0.006] | [0.005, 0.028] |
| 1000 | 0.006 | 0.003 | [0.000, 0.008] | [0.003, 0.016] |

(Produced by `scripts/run_benchmark.py --agent cfr --samples N --out runs/studies`.)

## Validation

The pipeline is checked against known values (see `tests/`):

* Kuhn equilibrium value −1/18 for Player 1.
* Always-pass: exploitability 1, M2 = 17/18 and 19/18, M3 (seat 1) = 1/6.
* Always-bet: exploitability 1/3, M3 (seat 1) = 1/18.
* Uniform random: exploitability 11/24, both by direct computation and through the full text
  pipeline.
* An equilibrium-playing subject through the pipeline: < 1e-3 when probabilities are read
  directly, < 0.01 when sampled 5,000 times per infostate.
* Mock subjects with injected malformed and illegal output: measured failure rates match the
  injected rates.
* Rerunning from the cache reproduces every result with zero calls.
* Leduc: deterministic subjects through the full pipeline match OpenSpiel's direct computation
  exactly; uniform and equilibrium subjects read as distributions match OpenSpiel to 1e-9 and
  < 1e-3 respectively.
* Play mode: always-pass as Player 1 in Kuhn scores −2/9 against the equilibrium within the
  simulation's 95% interval; matches are reproducible from the seed.
* Breakdown: M2 = M3 + sum of contributions to 1e-9 on Kuhn and Leduc, and hand-computed
  per-infostate contributions for always-pass in both Kuhn seats.
* Site: every number on every page is re-read from its result file at build time; tests check
  that an edited number or an edited published file is caught.

## Reproducibility

Every attempt is logged to `calls.jsonl` with the model, parameters, prompt version and hash, the
user prompt, raw output, parse result, token counts, latency and timestamp. The system prompt is
constant within a run and is stored once in `manifest.json`. Replies are cached on (provider,
model, parameters, prompt hash, sample index, attempt), so reruns are free and identical.

## Reporting

`scripts/build_site.py` builds the static site from the results directory in one command.

**Which runs are shown.** Every run directory with `manifest.json` and `metrics.json` is a
candidate. Sampled runs with fewer than 30 valid samples requested per infostate are smoke tests
and are left out. Runs that measure the same thing (game, provider, model, parameters, prompt
version and estimation kind) are deduplicated, keeping the most recently created. Runs can also
be excluded by name. The build lists every run it leaves out, with the reason, in its output
and in `build.json`.

**Reference subjects.** Rows marked *reference* are scripted policies, not LLMs, answering
through the same text interface (`scripts/run_references.py`): the equilibrium and uniform
random (each read exactly, and sampled at N = 200 like a model), always check/fold, always the
most aggressive action, and an 80/20 mix of equilibrium and uniform with 5% malformed replies.
They anchor the scale and keep the pipeline honest against known values. The exact rows give
the true values; the sampled rows show what a run of the same size reports for the same
strategy, sampling noise included. One such draw is visibly unlucky: Kuhn's sampled uniform
subject lands well above the exact 11/24 because the infostate where Player 2 holds the King and
faces a bet happened to draw 61% folds. It is shown as drawn.

**Prompt variants** (`-para`, `+shuffled`) are listed in their own table; the main table shows
each subject's range of exploitability across the prompts it was run with.

**Replays.** The replay view steps through a hand, showing at each of the subject's decisions
the situation exactly as the subject was told it, its estimated action frequencies against the
equilibrium and, for played hands, its raw replies; and at each opponent decision the
equilibrium mix, the best response and its per-visit edge. Hands come from three sources, always
labelled:

* *Biggest gain* (constructed): for each seat, the three infostates with the largest
  contributions. The hand is the history in that infostate where switching to the best response
  gains most (reach-weighted), followed by the best response and the subject's most likely
  actions.
* *Played*: the first 100 hands of a play-mode match, with every attempt the subject made.
* *Simulated*, only when no play-mode match exists: 100 hands drawn from σ̂ against the
  equilibrium. Every query is independent and context-free, so these follow the same
  distribution as live play, but they were not played live.

**Explanations are templated.** Every sentence on the site is filled in from computed numbers by
fixed templates in `report/explain.py`; none is written by a language model.

**Every number traces to a file.** Each number on a results page is rendered from a result file
published next to the page (`runs/<id>/data/*.json`), and its HTML element names that file and
the JSON pointer of the value. At the end of every build, the site is re-read and each number is
checked against its source; the build fails on any mismatch. `build.json` records the SHA-256
of every published file, and the check also confirms each published file is unchanged. Raw call
logs stay in the run directory. Numbers in this document are produced by the commands cited
next to them.

**Derived files.** The breakdown and the replay hands are written into the run directory as
`breakdown.json` and `replay.json`, computed only from the run's own result files. Each records
the SHA-256 of its inputs and is recomputed when they change.

## Limitations (so far)

* Small games. Kuhn poker has 12 infostates and Leduc 288, and both equilibria are well known and
  may appear in model training data.
* Results depend on the prompt wording and on the sampling settings a provider allows. Some
  current models do not allow the temperature to be changed.
* The strict parser may count verbose but sensible replies as failures. This is deliberate and
  is reported through M4.
* All metrics are measured against a CFR+ reference that is close to, but not exactly, an
  equilibrium (its own exploitability is shown on the leaderboard). Values smaller than that
  reference exploitability are not meaningful.
* The breakdown attributes the gain to the best responder's decisions, not to the subject's
  mistakes. A leak at one of the subject's decisions usually shows up as gains at the opponent
  decisions that follow it, which the replay view puts side by side.
