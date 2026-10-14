# Proposal A: multiway next steps

Source: section 4 of `docs/research/multiway.md` (4a: a per-seat multiway metric; 4b: a
five-step research track). Recommendation: do **A1** next, with **A2** as a small add-on that can
come first or in parallel. Neither needs paid model calls; both use scripted subjects only.

Why these two and not the rest of 4b: they turn the spike into something the benchmark can
report, and both can be checked against exact numbers the spike already produced. The
selection study (4b.2) and the exactness work (4b.3) are research for its own sake; three-player
Leduc (anything in 4b at Leduc size) needs hours of CFR+ per reference run, so it waits until the
Kuhn version has proved the metric.

---

## A1. Per-seat multiway metrics for three-player Kuhn (scripted subjects)

**Goal.** StrategyBench can score a subject in three-player Kuhn: for each seat, its seat regret,
its loss against the reference, single-opponent exploitation (with the "who pays" split) and
single-opponent punishment, each measured against a *set* of reference equilibria (the analytic
family's β = 0 and β = ¼ members plus a CFR+ profile) and reported as a range. This is section
4a, built properly.

**Scope.**

* New `analysis/multiway.py`; the existing `metrics.py` and `breakdown.py` stay two-player and
  unchanged.
* New `GameSpec` and prompt template for `kuhn_poker(players=3)`.
* Reference sets in `baselines/`: the two analytic members (encoded as in
  `research/multiway/kuhn3_family.py`) and cached CFR+ runs.
* The runner routes games with more than two players to the new module (direct mode only; play
  mode assumes two seats).
* Out of scope: real model runs, site pages, three-player Leduc.

**Done looks like.** `uv run python scripts/run_benchmark.py --game kuhn3 --agent uniform`
(and the other scripted agents) writes a `metrics.json` with per-seat, per-reference values,
the range across references and bootstrap intervals per reference; the methodology gains a
"Three players" section stating that results are relative to the reference set, never "vs
equilibrium".

**How it will be checked.** Tests, each against a known value:

1. Any analytic family member as the subject, with the same member as reference: seat regret 0
   in every seat (to 1e-12).
2. The spike's numbers reproduce exactly: the uniform subject's seat-1 loss is 151.04 mA against
   β = 0 and 265.62 mA against β = ¼; the mismatched equilibrium strategy loses 10.42 mA in
   seat 2 (= κβ at β = ¼, the paper's Table 4); the exact seat-1 equilibrium strategy can be
   punished by up to 62.50 mA.
3. Two-player consistency: on two-player Kuhn the new module's seat regret equals the existing
   M3 and its single-opponent exploitation equals M2 (to within the CFR+ reference's own
   exploitability). This ties the new metrics to the old ones.
4. Bootstrap coverage on a noisy mock subject, as `scripts/ci_coverage.py` does for two players.

**Effort.** About one working week, as section 4a estimates: GameSpec and prompt 0.5–1 day;
`analysis/multiway.py` with tests 2–3 days; reference sets 0.5 day; bootstrap and runner 1 day.
Site columns are a separate step (1–2 days) once the numbers are trusted.

**Decision needed from you.** This adds a new module to `analysis/` and a branch in the runner.
The brief's generality rule (new games need no core changes) is about two-player games; a new
metric family for n > 2 is a deliberate extension, and I would log it in
`docs/design-notes.md` as one.

---

## A2. Exact two-opponent ("team") punishment on three-player Kuhn

**Goal.** Compute the last row of the 4a metric table, which the doc lists as "later, needs team
machinery": how far two opponents could push the subject's value down by coordinating.

**The idea that makes it cheap.** Against a *fixed* subject, coordination between the two
opponents buys nothing beyond a well-chosen pair of pure strategies. The subject's value is
linear in any joint (correlated) distribution over the opponents' pure-strategy pairs, so its
minimum sits at a single pair. Correlation machinery (TB-DAG, ex-ante collusion) matters for
team *equilibria*, not for a team best response to a fixed strategy. So:

> team punishment = min over pure strategies s₂ of [ the subject's value when player 3
> best-responds (to minimise it) against (σ̂, s₂) ].

Player 2 has 16 infostates, so 2¹⁶ = 65,536 pure strategies; each inner step is one vectorised
best response on the 617-node tree (`research/multiway/tabular.py` already supports the
"minimise another player" utility). Seconds to a minute in total. The general problem is hard,
so this is exact for Kuhn-size games only.

**Done looks like.** `research/multiway/team_punishment.py` writes
`results/kuhn3_team_punishment.json` for the spike's subjects in every seat; `make_tables.py`
adds a column to the 4a demonstration tables; the doc's "Team punishment (later)" row becomes
computed, with the argument above.

**How it will be checked.**

1. Team punishment ≥ the larger single-opponent punishment (the team can always leave one
   opponent at its reference strategy, which is what single-opponent punishment does).
2. Alternating best responses from many random starts never find a lower value than the
   enumeration (they find local minima only).
3. On two-player Kuhn, "team" is a single opponent: the result equals the single-opponent
   punishment.
4. Spot check against brute force over all pairs, on a version of the game with Player 2's
   strategy restricted to a few infostates.

**Effort.** 1.5–2 days, all in `research/multiway/`, no change to `src/`.

---

## What I would not start yet

* **Equilibrium-selection study (4b.2).** Interesting, but it does not feed the benchmark;
  revisit after A1 if you want a write-up on "which equilibrium does CFR pick".
* **Three-player Leduc metrics.** A reference set needs several CFR+ runs of about 1,000
  iterations at about 3.3 s each (roughly an hour per run on this laptop), and MacQueen and Wright
  report that is enough for ε ≤ 13 mA. Feasible overnight, but only after A1 shows the metric
  is worth it.
* **Exact solving (4b.3).** Needs a nonconvex QP solver (Gurobi in the papers); open-source
  options are unproven at this size. Worth a short feasibility check before committing a week.
