# Methodology

_Draft. Covers what is implemented so far (Phase 1: Kuhn poker, `direct` mode, mock subjects)._

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
* The equilibrium reference is computed with CFR+ (OpenSpiel). For Kuhn poker its
  exploitability is below 1e-4 and the Player 1 value is −1/18, matching theory.

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

## Reproducibility

Every attempt is logged to `calls.jsonl` with the model, parameters, prompt version and hash, the
user prompt, raw output, parse result, token counts, latency and timestamp. The system prompt is
constant within a run and is stored once in `manifest.json`. Replies are cached on (provider,
model, parameters, prompt hash, sample index, attempt), so reruns are free and identical.

## Limitations (so far)

* Tiny games. Kuhn poker has 12 infostates and its equilibrium is well known and may appear in
  model training data.
* Results depend on the prompt wording and on the sampling settings a provider allows. Some
  current models do not allow the temperature to be changed.
* The strict parser may count verbose but sensible replies as failures. This is deliberate and
  is reported through M4.
