# Methodology

_Draft. Covers what is implemented so far: Kuhn and Leduc poker, `direct` and `play` modes._

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

## Prompt sensitivity

Two optional variants measure how much results depend on wording (`--prompt`):

* `<game>-v1-para`: the same rules, reworded and reordered.
* `<version>+shuffled`: the legal actions listed in a shuffled order, fixed per infostate.

The spread of a model's metrics across these variants is reported alongside its main result.

## Uncertainty

Bootstrap confidence intervals (95%, percentile, 200 replicates by default) resample the valid
samples at each infostate with replacement and recompute every metric.

**Small-sample bias.** Exploitability is a maximum over opponent strategies, so sampling noise in
σ̂ can only be exploited, never cancel out: the plug-in estimate is biased upwards. Example
(mock subject sampling the equilibrium, true exploitability ≈ 0):

| N per infostate | Estimate | 95% CI | Bias-corrected |
|---|---|---|---|
| 50 | 0.030 | [0.018, 0.080] | 0.016 |
| 200 | 0.018 | [0.008, 0.039] | 0.015 |
| 1000 | 0.004 | [0.002, 0.016] | 0.000 |

(Produced by `scripts/run_benchmark.py --agent cfr --samples N`.) Results therefore report the
bootstrap bias estimate and the bias-corrected value `max(0, 2·point − bootstrap mean)` next to
the plain estimate. The correction is partial; the reliable remedy is larger N. Distribution
subjects are not affected.

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

## Reproducibility

Every attempt is logged to `calls.jsonl` with the model, parameters, prompt version and hash, the
user prompt, raw output, parse result, token counts, latency and timestamp. The system prompt is
constant within a run and is stored once in `manifest.json`. Replies are cached on (provider,
model, parameters, prompt hash, sample index, attempt), so reruns are free and identical.

## Limitations (so far)

* Small games. Kuhn poker has 12 infostates and Leduc 288, and both equilibria are well known and
  may appear in model training data.
* Results depend on the prompt wording and on the sampling settings a provider allows. Some
  current models do not allow the temperature to be changed.
* The strict parser may count verbose but sensible replies as failures. This is deliberate and
  is reported through M4.
