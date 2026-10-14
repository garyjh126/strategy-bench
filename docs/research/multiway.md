# Multiway poker equilibria: a research spike

> **Status.** Research spike, October 2026. It is not a StrategyBench phase and changes nothing
> under `src/strategybench/`. Code and raw results are in `research/multiway/`.
>
> **Where the numbers come from.** Every table below, and every experimental number quoted in
> the text, is written into this file by `research/multiway/make_tables.py` from the JSON files in
> `research/multiway/results/`. In the Markdown source, generated text sits between
> `<!-- BEGIN table:… -->` markers or between `<!--v:…-->` and `<!--/v-->` comments. Where a
> sentence claims something the numbers do not show directly (for example, that CFR+ splits
> between two sub-families), `make_tables.py` checks it and stops if the results no longer
> support it. Numbers quoted from papers carry a citation. Fractions such as −1/48 are the
> analytic values from Szafron et al.
>
> **Units.** Values are expected chips per hand, shown in milli-antes (mA). The ante is 1 chip,
> so 1 mA = 0.001 chips. "Gain" always means one player's best-response gain: the value of a
> best response against the other players' fixed strategies, minus that player's current value.

## Summary

* **Three-player Kuhn poker has many equilibria with different seat values.** In the analytic
  family of Szafron, Gibson and Sturtevant (2013), player 2 always gets −1/48 chips per hand.
  Player 2 also controls a parameter β that moves up to 1/96 chips per hand from player 1 to
  player 3, while every profile stays an equilibrium. We drew
  <!--v:fam_members-->1,200<!--/v--> random members and checked them numerically. Each one is an exact
  equilibrium: no player gains more than <!--v:fam_max_gain-->3e-16<!--/v--> chips, which is
  floating-point zero.
* **Different solvers, and different starting points, end at different equilibria.**
  <!--v:conv_count-->23<!--/v--> runs finished with every player's gain at most
  <!--v:conv_threshold-->0.01<!--/v--> mA. Across them, player 1's value ranges from
  <!--v:conv_p1_min-->−30.63<!--/v--> to <!--v:conv_p1_max-->−24.59<!--/v--> mA per hand. That spread of
  <!--v:conv_p1_spread-->6.04<!--/v--> mA is <!--v:conv_spread_pct-->58<!--/v-->% of the family's full
  range. Player 2's value stays within <!--v:conv_p2_dev-->0.002<!--/v--> mA of −1/48 in every
  converged run, as it is in every member of the family.
* **Each solver has its own selection habits.** CFR always settled in one sub-family, with player 2
  almost never bluffing the Jack. CFR+ split between two sub-families. No run came near the member
  that an exact solver returned (Ganzfried, β = 0): the smallest β in any run was
  <!--v:beta_min-->0.087<!--/v-->.
* **CFR's guarantee in three-player games is a coarse correlated equilibrium (CCE), not Nash.**
  The guarantee covers the sequence of iterates, not the average strategy that would be deployed.
  In three-player Kuhn the deployed average strategy happens to be about as close to Nash as the
  iterates are to a CCE: after <!--v:kuhn_iterations-->20,000<!--/v--> simultaneous-update CFR
  iterations from the uniform start, its largest gain is <!--v:sim_avg_gain-->0.83<!--/v--> mA,
  against a CCE gap of <!--v:sim_cce_gap-->0.83<!--/v--> mA.
  This is an empirical fact about this game, not a property of CFR.
* **Unreached infostates are not free.** In every sampled family member, pushing any of
  <!--v:offpath_always-->10<!--/v--> unreached parameters to 0 or 1 breaks the equilibrium. Most
  of them are responses to an opening bet: the threats that stop player 1 from opening. But they
  are not unique. <!--v:cfrplus_offpath_runs-->3 of the 11<!--/v--> CFR+ runs settle on off-path values
  outside the family and remain equilibria to within <!--v:cfrplus_worst_gain-->8.7e-04<!--/v--> mA.
  Ganzfried's exact solution is another such equilibrium. It reproduces here only under the
  parameter label his paper gives (c32), not under its wording ("bet-fold").
* **OpenSpiel's default averaging for external-sampling MCCFR is not the unbiased estimate with
  more than two players.** OpenSpiel's own source says so. On three-player Kuhn, a million
  iterations left a median largest gain of <!--v:mccfr_simple_1e6-->2.94<!--/v--> mA, and
  <!--v:mccfr_worse-->4<!--/v--> of the <!--v:mccfr_simple_seeds-->10<!--/v--> seeds were worse
  at <!--v:mccfr_simple_iters-->10⁶<!--/v--> iterations than at
  <!--v:mccfr_full_iters-->3·10⁵<!--/v-->. The unbiased "full" averaging, run to
  <!--v:mccfr_full_iters-->3·10⁵<!--/v--> iterations, ended between <!--v:mccfr_full_lo-->2.06<!--/v-->
  and <!--v:mccfr_full_hi-->3.09<!--/v--> mA. There are too few seeds and iterations to say how much
  of the difference is the bias.
* **Three-player Leduc did not converge inside the time box.** After
  <!--v:leduc_seconds-->403<!--/v--> seconds of compute, the best run still left a player gaining
  <!--v:leduc_best-->147<!--/v--> mA. We make no equilibrium claims for it.
* **A multiway StrategyBench metric must name its reference opponents.** In the demonstration, a
  uniform-random subject in seat 1 does <!--v:seat_u_p1_b0-->151.04<!--/v--> mA per hand worse than
  the equilibrium strategy it replaces when the other seats play one exact equilibrium, and
  <!--v:seat_u_p1_b14-->265.62<!--/v--> mA worse when they play another. Section 4 proposes per-seat
  metrics measured against a set of reference equilibria, with the range reported.

## 1. Primer: what changes with three players

### Two players: why "equilibrium" means "safe"

In a two-player zero-sum game, the minimax theorem gives three properties at once:

1. **One value.** Every Nash equilibrium gives each seat the same expected payoff, the game
   value. In two-player Kuhn that is −1/18 for the first player.
2. **Interchangeability.** Take player 1's half of one equilibrium and player 2's half of
   another, and you still have an equilibrium.
3. **A guarantee.** An equilibrium strategy is a maxmin strategy. It earns at least the game
   value against *any* opponent, and only a mistake by the opponent can make it earn more.

Together these give "game-theory optimal" its practical meaning: a strategy you can play
without knowing anything about your opponent. They also make exploitability (NashConv / 2) a
single, well-defined distance from that safe point. StrategyBench's M1 relies on all three.

### Three players: what breaks

Three-player poker is still zero-sum, because the chips only move between players. Even so, all
three properties fail.

1. **Many values.** Equilibria can give the same seat different payoffs. In three-player Kuhn,
   player 1's equilibrium value can be anything from −1/32 to −1/48 chips per hand, depending on
   which equilibrium is played. Player 2 decides, through a strategy parameter that changes
   nothing for player 2.
2. **No interchangeability.** Mixing halves of different equilibria can produce a profile that
   is not an equilibrium. Szafron et al. (Table 4) show player 2 losing value this way. Section 4
   measures a case where the mix lets player 1 gain <!--v:seat_mix_p1_gain-->166.67<!--/v--> mA by
   deviating.
3. **No guarantee.** With two opponents, an equilibrium strategy protects you only if *both*
   opponents stick to that same equilibrium. One opponent can lower your value by deviating,
   even at a cost to itself. Two opponents can, deliberately or by accident, play as a team
   against you. In three-player Kuhn, the exact equilibrium strategy for seat 1 can be pushed up
   to <!--v:seat_eq_p1_punish-->62.50<!--/v--> mA below its equilibrium value by a single opponent
   (Section 4).
4. **Hard to compute.** Finding a Nash equilibrium is PPAD-complete for three-player games, and
   even for two-player games that are not zero-sum (Daskalakis, Goldberg and Papadimitriou 2009).
   Being zero-sum does not help once there are three players: adding a third player who only
   absorbs the other two players' payoffs turns any two-player game into a three-player zero-sum
   one. No efficient general algorithm is known. Exact methods (Section 3) currently stop at
   games the size of three-player Kuhn.

So "the equilibrium" and "GTO" have no unique meaning with three players. The careful phrasing is
"an ε-Nash profile with ε = the largest per-player gain", together with the seat values *of that
profile*.

### What CFR actually converges to: coarse correlated equilibrium

Picture a referee who, before each hand, draws a complete strategy profile from a hat and
privately tells each player their own part. A **coarse correlated equilibrium (CCE)** is a hat
such that no player would rather opt out in advance and commit to one fixed strategy of their
own. Opting out happens before the player hears their own recommendation. A Nash equilibrium is
the special case where the referee's draws for different players are independent, so there is
nothing to coordinate on.

CFR drives each player's average regret to zero. If you treat CFR's sequence of iterate
profiles as the hat, with one slip per iteration, that hat is an ε-CCE, and ε goes to 0. Two
things do *not* follow:

* Each player's **average strategy** is the marginal of that hat: the thing you would deploy, and
  what StrategyBench would call "the CFR equilibrium". Played together, the averages need not
  form a Nash equilibrium. They need not even form a CCE.
* In two-player zero-sum games, the marginals of any CCE form a Nash equilibrium. That is why the
  distinction never matters there, and why it suddenly does with three players.

MacQueen and Wright (2023) give the general framework: no-regret self-play converges to a
CCE, and a deployed strategy is its marginal. They also identify a structural reason why
self-play still works in some multiplayer games. If a game is close to a sum of pairwise
two-player constant-sum games (a constant-sum polymatrix game), the marginals of any CCE are
approximately Nash. If, in addition, every approximate equilibrium is also approximately an
equilibrium of each pairwise game ("subgame stable"), then the worst-case loss of those
marginals against new opponents, which they call vulnerability, is bounded. They measured
three-player Leduc to be close to such a game in the neighbourhood of CFR+ strategies. Gibson
(2013) adds a refinement: CFR avoids iteratively strictly dominated actions and strategies, so it
finds more than an arbitrary CCE.

**What we measure in this spike.** For every final profile we report each player's
best-response gain, which tells you how close the deployed strategies are to Nash. For CFR with
simultaneous updates we also report the CCE gap of the iterate sequence. That gap is the
quantity CFR actually guarantees.

## 2. Experiments on three-player Kuhn poker

**Game.** OpenSpiel `kuhn_poker(players=3)`, the game of Szafron et al. and Ganzfried. The deck
has four cards (Jack, Queen, King, Ace) and each player antes 1 chip. There is one betting round
with at most one bet: players check or bet 1 chip in turn, and once someone has bet, every other
player folds or calls. There are <!--v:kuhn_infosets-->48<!--/v--> infostates,
<!--v:kuhn_infosets_per_player-->16<!--/v--> per player. OpenSpiel's tree has
<!--v:kuhn_nodes-->617<!--/v--> nodes because it deals the cards one at a time; Ganzfried counts 601
for the same game with a single deal node.

**Solvers.** All full-width runs use <!--v:kuhn_iterations-->20,000<!--/v--> iterations.

* **CFR, CFR+ and linear CFR, our implementation.** CFR+ uses regret matching+ with linear
  averaging. Linear CFR weights both regrets and averages by the iteration number. All three use
  alternating updates, in the same order as OpenSpiel. Each runs from the uniform strategy and
  from <!--v:random_starts-->10<!--/v--> random initial strategies. A random start draws the first
  iterate uniformly from each infostate's simplex; regrets start at zero.
* **CFR with simultaneous updates.** One uniform start and <!--v:sim_random_starts-->5<!--/v-->
  random starts. The CCE guarantee needs every player's regret measured against one shared
  sequence of profiles, which simultaneous updates provide.
* **Fictitious play, our implementation.** Extensive-form fictitious play (XFP) with
  simultaneous best responses. It runs from a uniform starting average and from
  <!--v:random_starts-->10<!--/v--> random ones.
* **OpenSpiel's C++ solvers.** `CFRSolver` and `CFRPlusSolver` with library defaults.
* **External-sampling MCCFR, OpenSpiel C++.** Simple averaging, which is the default:
  <!--v:mccfr_simple_seeds-->10<!--/v--> seeds, <!--v:mccfr_simple_iters-->10⁶<!--/v--> iterations.
  Full averaging: <!--v:mccfr_full_seeds-->5<!--/v--> seeds, <!--v:mccfr_full_iters-->3·10⁵<!--/v-->
  iterations, because each iteration is about <!--v:mccfr_full_slowdown-->18<!--/v--> times slower
  here.

**Checks on our solver code** (`research/multiway/test_tabular.py`):

* **Gains.** Per-player gains match OpenSpiel's `nash_conv` to 1e-12.
* **Alternating CFR.** Our version reproduces `pyspiel.CFRSolver`'s average policy to 1e-9.
* **Fictitious play.** Ours reproduces OpenSpiel's `XFPSolver` to 1e-12.
* **Two-player value.** CFR+ recovers the two-player Kuhn value of −1/18.

### 2.1 What the solvers reach

Each row covers every run of one solver. Ranges run from the smallest to the largest value over
those runs, measured on the final average profile. β and the closest sub-family are explained in
Section 2.4.

<!-- BEGIN table:solver-summary -->
| Solver | Runs | Iterations | Largest gain, median run (mA) | Largest gain, worst run (mA) | P1 value (mA) | P2 value (mA) | P3 value (mA) | β = max(b11, b21) | Closest sub-family: c11=0 / 0<c11<½ / c11=½ |
|---|---|---|---|---|---|---|---|---|---|
| CFR | 11 | 20,000 | 0.08 | 0.11 | -30.28 to -27.42 | -20.84 to -20.76 | 48.25 to 51.06 | 0.159 to 0.226 | 11 / 0 / 0 |
| CFR+ | 11 | 20,000 | 3.3e-04 | 8.7e-04 | -26.90 to -24.59 | -20.83 | 45.42 to 47.74 | 0.090 to 0.146 | 4 / 0 / 7 |
| Linear CFR | 11 | 20,000 | 1.9e-03 | 3.7e-03 | -30.63 to -25.78 | -20.83 | 46.61 to 51.46 | 0.119 to 0.235 | 11 / 0 / 0 |
| CFR simultaneous | 6 | 20,000 | 1.21 | 1.71 | -30.82 to -26.41 | -20.79 to -19.83 | 47.20 to 51.08 | 0.136 to 0.234 | 5 / 1 / 0 |
| Fictitious play | 11 | 20,000 | 1.03 | 1.44 | -31.33 to -29.36 | -20.46 to -19.63 | 49.52 to 51.79 | 0.185 to 0.234 | 11 / 0 / 0 |
| OpenSpiel CFR | 1 | 20,000 | 0.08 | 0.08 | -28.79 | -20.83 | 49.62 | 0.191 | 1 / 0 / 0 |
| OpenSpiel CFR+ | 1 | 20,000 | 3.1e-04 | 3.1e-04 | -26.56 | -20.83 | 47.39 | 0.137 | 0 / 0 / 1 |
| OpenSpiel ES-MCCFR (simple averaging) | 10 | 1,000,000 | 2.94 | 44.38 | -29.39 to -25.69 | -20.78 to -19.25 | 46.17 to 49.05 | 0.106 to 0.206 | 8 / 0 / 2 |
| OpenSpiel ES-MCCFR (full averaging) | 5 | 300,000 | 2.59 | 3.09 | -30.49 to -26.52 | -20.56 to -19.34 | 46.22 to 50.20 | 0.087 to 0.224 | 4 / 0 / 1 |
<!-- END table:solver-summary -->

Median largest per-player gain at checkpoints (full-width solvers):

<!-- BEGIN table:convergence -->
| Solver | Updates | after 100 (mA) | after 1,000 (mA) | after 10,000 (mA) | after 20,000 (mA) |
|---|---|---|---|---|---|
| CFR | alternating | 14.87 | 1.56 | 0.16 | 0.08 |
| CFR+ | alternating | 1.52 | 0.02 | 4.9e-04 | 3.3e-04 |
| Linear CFR | alternating | 1.76 | 0.06 | 4.1e-03 | 1.9e-03 |
| CFR simultaneous | simultaneous | 35.74 | 5.59 | 1.35 | 1.21 |
| Fictitious play | simultaneous | 31.61 | 6.17 | 1.50 | 1.03 |
| OpenSpiel CFR | alternating | 14.87 | 1.52 | 0.15 | 0.08 |
| OpenSpiel CFR+ | alternating | 1.52 | 0.02 | 4.4e-04 | 3.1e-04 |
<!-- END table:convergence -->

**Reading.**

* **Converged runs are approximate Nash, not just approximate CCE.** With alternating updates,
  CFR, CFR+ and linear CFR all end with every player's gain at most
  <!--v:alt_worst_gain-->0.11<!--/v--> mA. That makes them approximate Nash equilibria in the strict
  sense used here. For CFR this matches Abou Risk and Szafron's observation that CFR finds
  approximate Nash equilibria of three-player Kuhn.
* **Simultaneous updates are much slower.** Simultaneous-update CFR and fictitious play converge
  far more slowly over the same number of iterations: their median largest gains at the end are
  <!--v:sim_median-->1.21<!--/v--> and <!--v:fp_median-->1.03<!--/v--> mA, against
  <!--v:cfr_alt_median-->0.08<!--/v--> mA for CFR with alternating updates. This spike did not test
  whether the gap between update orders is specific to three players.

### 2.2 CCE versus Nash

Simultaneous-update CFR, comparing the CCE gap of the iterate sequence (what CFR guarantees)
with the largest gain of the deployed average profile. The uniform start is shown at several
checkpoints; the other starts are shown at the end.

<!-- BEGIN table:cce -->
| Start | Iterations | Largest gain of average profile (mA) | Largest CCE gap (mA) | P1 value, average profile | P1 value, CCE | P2 value, average profile | P2 value, CCE |
|---|---|---|---|---|---|---|---|
| uniform | 100 | 37.16 | 33.53 | -34.56 | -39.10 | -13.75 | -3.49 |
| uniform | 300 | 15.89 | 14.25 | -38.34 | -29.65 | -16.96 | -24.21 |
| uniform | 1,000 | 6.11 | 5.66 | -29.33 | -27.43 | -18.61 | -18.50 |
| uniform | 3,000 | 2.73 | 2.35 | -30.14 | -29.85 | -19.63 | -19.21 |
| uniform | 10,000 | 1.04 | 0.96 | -28.33 | -28.32 | -20.04 | -20.65 |
| uniform | 20,000 | 0.83 | 0.83 | -29.43 | -29.38 | -20.33 | -20.39 |
| random (seed 1) | 20,000 | 1.60 | 0.75 | -27.97 | -27.00 | -19.98 | -20.41 |
| random (seed 2) | 20,000 | 1.71 | 0.92 | -28.22 | -27.87 | -19.83 | -20.03 |
| random (seed 3) | 20,000 | 1.00 | 0.86 | -30.82 | -30.24 | -20.25 | -20.28 |
| random (seed 4) | 20,000 | 0.72 | 0.79 | -27.55 | -27.36 | -20.76 | -21.15 |
| random (seed 5) | 20,000 | 1.42 | 0.85 | -26.41 | -26.85 | -20.79 | -20.20 |
<!-- END table:cce -->

**Reading.**

* **The two gaps shrink together here.** At <!--v:kuhn_iterations-->20,000<!--/v--> iterations the
  uniform-start run has a largest gain of <!--v:sim_avg_gain-->0.83<!--/v--> mA for the average
  profile and a CCE gap of <!--v:sim_cce_gap-->0.83<!--/v--> mA. Across all starts, the average
  profile's largest gain is <!--v:sim_ratio_lo-->0.9<!--/v--> to <!--v:sim_ratio_hi-->2.1<!--/v-->
  times the CCE gap.
* **The CCE and the deployed profile pay the seats differently.** The value columns compare the
  correlated iterates with the product of the averages. For the uniform start they differ by up
  to <!--v:cce_value_gap_max-->10.3<!--/v--> mA for some seat in the early checkpoints, and by at
  most <!--v:cce_value_gap_final-->0.97<!--/v--> mA in any run at the end. The difference comes
  from the correlation between iterates. Deployed separately, each seat gets the average
  profile's value, not the CCE's.
* **Three-player Kuhn is a benign case.** Nothing forces the gaps to track each other. The PED
  paper (see Section 3) reports vanilla CFR's average strategy doing well for the first several
  hundred iterations on the 5-card variant, then getting markedly worse.

### 2.3 How different are the equilibria?

Seat values across runs that pass a gain threshold, compared with the analytic family's range.

<!-- BEGIN table:ev-spread -->
| Runs kept | Count | Solvers | P1 value (mA) | P2 value (mA) | P3 value (mA) | P1 spread (mA) |
|---|---|---|---|---|---|---|
| every gain ≤ 1.00 mA | 44 | CFR, CFR simultaneous, CFR+, Fictitious play, Linear CFR, OpenSpiel CFR, OpenSpiel CFR+, OpenSpiel ES-MCCFR (simple averaging) | -31.33 to -24.59 | -20.84 to -20.12 | 45.42 to 51.79 | 6.74 |
| every gain ≤ 0.10 mA | 34 | CFR, CFR+, Linear CFR, OpenSpiel CFR, OpenSpiel CFR+ | -30.63 to -24.59 | -20.84 to -20.76 | 45.42 to 51.46 | 6.04 |
| every gain ≤ 0.01 mA | 23 | CFR+, Linear CFR, OpenSpiel CFR+ | -30.63 to -24.59 | -20.83 | 45.42 to 51.46 | 6.04 |
| analytic family (all members) | ∞ | Szafron et al. 2013, Table 3 | -31.25 to -20.83 | -20.83 | 41.67 to 52.08 | 10.42 |
<!-- END table:ev-spread -->

**Reading.**

* **Equilibria differ more than convergence error.** Among runs with every gain at most
  <!--v:conv_threshold-->0.01<!--/v--> mA, player 1's value still varies by
  <!--v:conv_p1_spread-->6.04<!--/v--> mA per hand. That is about <!--v:conv_ratio-->1,600<!--/v-->
  times the largest gain among those runs, so it reflects genuinely different equilibria, not
  incomplete convergence.
* **Player 2's value is pinned.** It stays within <!--v:conv_p2_dev-->0.002<!--/v--> mA of −1/48 in
  every converged run, matching the theorem that every member gives player 2 −1/48.
* **The variation is a transfer between players 1 and 3.** Player 3's value mirrors player 1's.

### 2.4 Which equilibria do the runs approach?

**The analytic family, checked numerically.** Szafron et al. use one parameter per infostate:
a_jk, b_jk and c_jk are the probabilities that players 1, 2 and 3 take the aggressive action
(bet or call) holding card j (1 = Jack, …, 4 = Ace) in betting situation k. Table 2 of the paper
fixes 21 parameters. Table 3 gives three sub-families, indexed by player 3's Jack bluff
probability c11: equal to 0, strictly between 0 and ½, or equal to ½. The seat values depend only
on β = max(b11, b21), player 2's bluffing frequency with the Jack or Queen after a check:

* player 1: −(1/24)(½ + β);
* player 2: −1/48;
* player 3: (1/24)(1 + β);
* β ranges from 0 to ¼.

We encoded the family (`kuhn3_family.py`) and checked random members:

<!-- BEGIN table:family-members -->
| Sub-family | Random members | Largest gain (mA) | Largest gap between value and formula (mA) | P1 value (mA) | P2 value (mA) | P3 value (mA) | Largest gain with the prose b33 formula (mA) |
|---|---|---|---|---|---|---|---|
| c11=0 | 400 | 0 | 2e-13 | -31.25 to -20.89 | -20.83 | 41.72 to 52.08 |  |
| 0<c11<1/2 | 400 | 0 | 2e-13 | -31.25 to -20.87 | -20.83 | 41.70 to 52.08 |  |
| c11=1/2 | 400 | 0 | 2e-13 | -31.24 to -20.84 | -20.83 | 41.67 to 52.07 | 10.33 |
<!-- END table:family-members -->

* **Every member is an exact equilibrium.** All sampled members have gains at floating-point
  zero, and every seat value matches the formula.
* **The paper's prose has a typo; Table 3 is right.** For the c11 = ½ sub-family, the prose gives
  b33 = (1 + b11 + 2b21)/2. That is not an equilibrium: some player gains up to
  <!--v:fam_prose_gain-->10.33<!--/v--> mA. Table 3's general formula,
  b33 = ½ + (b11 + b21)/2 + β/2 − b23(1 − b21), is the one that works.

**Where the runs land.** Every run's final profile was matched against each sub-family's
constraints. The on-path violation is the largest constraint violation among parameters at
infostates reached when player 1 never opens. The off-path violation covers the rest. Per-run
values are in Appendix A. In summary:

* **Every run with alternating updates is close to the family on the path of play.** The median
  on-path violation is <!--v:onpath_cfr-->1.9e-03<!--/v--> for CFR, <!--v:onpath_cfrplus-->6.3e-06<!--/v-->
  for CFR+ and <!--v:onpath_linear-->2.2e-05<!--/v--> for linear CFR.
* **CFR is consistent.** All <!--v:cfr_n-->11<!--/v--> CFR starts landed in the c11 = 0
  sub-family with b11 at most <!--v:cfr_b11_max-->0.004<!--/v-->: player 2 bluffs with the Queen but
  almost never with the Jack. β ranged from <!--v:cfr_beta_lo-->0.159<!--/v--> to
  <!--v:cfr_beta_hi-->0.226<!--/v-->.
* **CFR+ splits.** <!--v:cfrplus_split-->7 of the 11 starts ended closest to the c11 = ½ sub-family and 4 closest to c11 = 0<!--/v-->. β ranged from
  <!--v:cfrplus_beta_lo-->0.090<!--/v--> to <!--v:cfrplus_beta_hi-->0.146<!--/v-->.
* **Linear CFR depends on the start.** From random starts it mostly sat near the top of the
  range: <!--v:linear_high-->7 of 10<!--/v--> runs ended with β above 0.2, and β ranged from
  <!--v:linear_beta_lo-->0.119<!--/v--> to <!--v:linear_beta_hi-->0.235<!--/v-->. The uniform start gave
  β = <!--v:linear_beta_uniform-->0.126<!--/v-->.
* **No run reached either end of the range.** Across all runs β stayed between
  <!--v:beta_min-->0.087<!--/v--> and <!--v:beta_max-->0.235<!--/v-->. The β = 0 end is the member
  returned by Ganzfried's exact quadratically-constrained-program solver, with values
  (−1/48, −1/48, 1/24).
* **Ganzfried's logit solution is a family member in the middle of the range.** Gambit's logit
  quantal-response solution reported values of about (−0.0276, −0.0208, 0.0484). The formula
  puts that at β ≈ <!--v:qre_beta-->0.16<!--/v-->, inside the range the CFR-family runs cover.

The paper itself says its parameter values "were discovered through careful examination of a
set of solutions produced by a Monte Carlo sampling variant of Counterfactual Regret
Minimization [...] with different random seeds". Solver-dependent selection is therefore how the
family was found in the first place.

### 2.5 Unreached infostates

Every family member has player 1 never open with a bet. As a result player 2's "facing an
opening bet" infostates and player 3's "after an opening bet" infostates are never reached. When
β = 0 even more are unreached. Do the strategies there matter?

**Pushing each unreached parameter to 0 or to 1, one at a time,** across all
<!--v:fam_members-->1,200<!--/v--> sampled members:

<!-- BEGIN table:offpath-breaks -->
| Parameter | Infostate | Unreached in | Pushing to 0 or 1 breaks equilibrium | Largest gain created (mA) |
|---|---|---|---|---|
| a44 | P1, A, check, bet, call | 1,200 of 1,200 | 100% | 83.32 |
| b12 | P2, J, facing an opening bet | 1,200 of 1,200 | 100% | 169.76 |
| b22 | P2, Q, facing an opening bet | 1,200 of 1,200 | 100% | 121.22 |
| b32 | P2, K, facing an opening bet | 1,200 of 1,200 | 100% | 293.85 |
| b42 | P2, A, facing an opening bet | 1,200 of 1,200 | 100% | 1060.66 |
| b44 | P2, A, check, check, bet, call | 1,200 of 1,200 | 100% | 166.62 |
| c13 | P3, J, bet, fold | 1,200 of 1,200 | 100% | 123.40 |
| c23 | P3, Q, bet, fold | 1,200 of 1,200 | 100% | 82.52 |
| c33 | P3, K, bet, fold | 1,200 of 1,200 | 100% | 166.39 |
| c43 | P3, A, bet, fold | 1,200 of 1,200 | 100% | 924.27 |
| c14 | P3, J, bet, call | 1,200 of 1,200 | 76% | 33.97 |
| c24 | P3, Q, bet, call | 1,200 of 1,200 | 76% | 33.97 |
| b14 | P2, J, check, check, bet, call | 400 of 1,200 | 0% | 0 |
| b24 | P2, Q, check, check, bet, call | 400 of 1,200 | 0% | 0 |
| c34 | P3, K, bet, call | 1,200 of 1,200 | 0% | 0 |
| c44 | P3, A, bet, call | 1,200 of 1,200 | 0% | 0 |
<!-- END table:offpath-breaks -->

Most of them matter. Of the <!--v:offpath_total-->16<!--/v--> parameters that are unreached in
some member, <!--v:offpath_always-->10<!--/v--> break the equilibrium in every member where they
are unreached, <!--v:offpath_some-->2<!--/v--> in some members and
<!--v:offpath_never-->4<!--/v--> never. <!--v:offpath_opening-->8<!--/v--> of the ones that
always break are responses to an opening bet. Player 2 must call an opening bet with the Ace
(b42) and must not call it with the Jack or Queen (b12, b22) beyond a bound. Player 3 likewise
(c13, c23, c43). Otherwise opening with a bet becomes profitable for player 1: only player 1 can
reach these infostates, by opening. Nash puts real constraints on behaviour no one ever sees.
This is also a plausible reason why sampled solvers converge slowly there: these infostates
carry almost no counterfactual weight once player 1 rarely opens.

**How much freedom there is.** For four representative members, the table gives the range of
each unreached parameter, with the others held fixed, that keeps the profile an exact
equilibrium. Each cell shows the family's value, then the allowed range. The range is found on a
grid of step 0.005, widened to include the family's own value where that falls between grid
points. It is always a single interval, because the other players' gains are convex in the
parameter.

<!-- BEGIN table:offpath-intervals -->
| Parameter | Infostate | c11=0, beta=0 (b32=0, c33=1/2) | c11=0, beta=1/8 (b11=b21=1/8, b32=1/4, c33=3/8) | c11=0, beta=1/4 (b32=15/16, c33=0) | c11=1/2, beta=1/8 (b21=1/16, b23=0, b32=1/4, c33=3/8) |
|---|---|---|---|---|---|
| a13 | P1, J, check, bet, fold | 0: [0, 0] | reached | reached | reached |
| a14 | P1, J, check, bet, call | 0: [0, 1] | reached | reached | reached |
| a23 | P1, Q, check, bet, fold | 0: [0, 0] | reached | reached | reached |
| a24 | P1, Q, check, bet, call | 0: [0, 1] | reached | reached | reached |
| a33 | P1, K, check, bet, fold | 0.5: [0.5, 0.5] | reached | reached | reached |
| a34 | P1, K, check, bet, call | 0: [0, 1] | reached | reached | reached |
| a43 | P1, A, check, bet, fold | 1: [1, 1] | reached | reached | reached |
| a44 | P1, A, check, bet, call | 1: [0, 1] | 1: [0.8, 1] | 1: [0.8, 1] | 1: [0.8, 1] |
| b12 | P2, J, facing an opening bet | 0: [0, 0] | 0: [0, 0.115] | 0: [0, 0] | 0: [0, 0.055] |
| b14 | P2, J, check, check, bet, call | reached | reached | reached | 0: [0, 1] |
| b22 | P2, Q, facing an opening bet | 0: [0, 0] | 0: [0, 0.115] | 0: [0, 0] | 0: [0, 0.055] |
| b24 | P2, Q, check, check, bet, call | 0: [0, 1] | 0: [0, 1] | 0: [0, 1] | reached |
| b32 | P2, K, facing an opening bet | 0: [0, 0] | 0.25: [0.125, 0.34] | 0.938: [0.5, 0.938] | 0.25: [0.125, 0.295] |
| b42 | P2, A, facing an opening bet | 1: [1, 1] | 1: [0.925, 1] | 1: [0.83, 1] | 1: [0.925, 1] |
| b43 | P2, A, check, check, bet, fold | reached | reached | 1: [0, 1] | reached |
| b44 | P2, A, check, check, bet, call | 1: [0.8, 1] | 1: [0.8, 1] | 1: [0, 1] | 1: [0.88, 1] |
| c12 | P3, J, check, bet | 0: [0, 0] | reached | reached | reached |
| c13 | P3, J, bet, fold | 0: [0, 0] | 0: [0, 0.105] | 0: [0, 0] | 0: [0, 0.05] |
| c14 | P3, J, bet, call | 0: [0, 1] | 0: [0, 0.75] | 0: [0, 0] | 0: [0, 0.375] |
| c22 | P3, Q, check, bet | 0: [0, 0] | reached | reached | reached |
| c23 | P3, Q, bet, fold | 0: [0, 0] | 0: [0, 0.105] | 0: [0, 0] | 0: [0, 0.05] |
| c24 | P3, Q, bet, call | 0: [0, 1] | 0: [0, 0.75] | 0: [0, 0] | 0: [0, 0.375] |
| c32 | P3, K, check, bet | 0: [0, 0] | reached | reached | reached |
| c33 | P3, K, bet, fold | 0.5: [0.5, 0.5] | 0.375: [0.25, 0.465] | 0: [0, 0] | 0.375: [0.25, 0.42] |
| c34 | P3, K, bet, call | 0: [0, 1] | 0: [0, 1] | 0: [0, 1] | 0: [0, 1] |
| c42 | P3, A, check, bet | 1: [1, 1] | reached | reached | reached |
| c43 | P3, A, bet, fold | 1: [1, 1] | 1: [0.93, 1] | 1: [0.83, 1] | 1: [0.93, 1] |
| c44 | P3, A, bet, call | 1: [0, 1] | 1: [0, 1] | 1: [0, 1] | 1: [0, 1] |
<!-- END table:offpath-intervals -->

So the family's off-path values are *sufficient*, not *necessary*. The ranges are widest when β
is in the middle. At β = 0, <!--v:iv_pinned_b0-->16 of the 26<!--/v--> unreached parameters are pinned to a
single value; at β = ¼ the Jack and Queen calls are pinned again, but b32, b42 and c43 keep some
room. The <!--v:cfrplus_offpath_runs-->3 of the 11<!--/v--> CFR+ runs with large off-path violations in
Appendix A use this freedom. They have player 2 calling an opening bet with the Queen up to
<!--v:cfrplus_b22_max-->2.5%<!--/v--> of the time, and player 3 calling with the Queen after
bet-fold up to <!--v:cfrplus_c23_max-->6.8%<!--/v-->. These are comparable to the ranges above,
which were computed for other members, and the runs remain equilibria to within
<!--v:cfrplus_worst_gain-->8.7e-04<!--/v--> mA.

**Ganzfried's off-path equilibrium.** Ganzfried (2025) reports an exact equilibrium with the β = 0
seat values that differs from the family at two unreached infostates:

* player 1 always folds the King facing check-bet-fold (a33 = 0, against the family's ½);
* player 3 calls half the time with the King.

His text names the second parameter "c32", which is the situation facing check-bet, but
describes it as "facing bet-fold", which is c33. We tested both readings on β = 0 members. The
"largest gain" cells name the player who gains.

<!-- BEGIN table:ganzfried -->
| Change to the β = 0 member | base b32=0, c33=0.5 | base b32=0.25, c33=0.25 | base b32=0.5, c33=0 |
|---|---|---|---|
| a33=0 only | P2 gains 166.67 | P2 gains 166.67 | P2 gains 166.67 |
| a33=0, c33=1/2 (as described: King facing bet-fold) | P2 gains 166.67 | P2 gains 166.67 | P2 gains 166.67 |
| a33=0, c32=1/2 (as labelled: King facing check-bet) | 0 (equilibrium) | 0 (equilibrium) | 0 (equilibrium) |
| c32=1/2 only | P2 gains 41.67 | P2 gains 41.67 | P2 gains 41.67 |
| a33=0, c32=1/4 | P2 gains 83.33 | P2 gains 83.33 | P2 gains 83.33 |
| a33=0, c32=1 | P2 gains 41.67 | P2 gains 41.67 | P2 gains 41.67 |
<!-- END table:ganzfried -->

* **His result reproduces exactly under the label c32 = ½.** Under the verbal description the
  profile is not an equilibrium: player 2 gains <!--v:ganz_c33_gain-->166.67<!--/v--> mA by betting
  after a check (only player 2 can reach the changed infostates, by doing so).
* **Neither change works on its own.** Each breaks the equilibrium, but together they cancel.
  Single-parameter ranges like those above therefore understate the off-path freedom.
* **The family is not the whole equilibrium set,** as Ganzfried concludes, at least off the path
  of play. Whether other equilibria also differ on the path, with different seat values, is still
  open. Szafron et al. left it open, Ganzfried's example differs only off the path, and this
  spike did not settle it.

### 2.6 MCCFR and the averaging mode

OpenSpiel's source documents why its default ("simple") averaging for external-sampling MCCFR
is not the unbiased estimate with more than two players. Each player's average is updated on
another player's sampled pass, and the importance-sampling weights no longer cancel. Also, if one
player never takes an action, other players' averages in the subtree below it stop being
updated. OpenSpiel keeps it as the default because it is faster, "seems to work better
empirically", and matches Pluribus. Its "full" mode adds a separate full-tree pass that updates
the averages exactly.

<!-- BEGIN table:mccfr -->
| Solver | Seeds | after 10⁴: median (range), mA | after 10⁵ | after 3·10⁵ | after 10⁶ |
|---|---|---|---|---|---|
| OpenSpiel ES-MCCFR (simple averaging) | 10 | 18.16 (9.22 to 22.29) | 6.70 (3.35 to 16.85) | 3.74 (1.50 to 16.62) | 2.94 (0.84 to 44.38) |
| OpenSpiel ES-MCCFR (full averaging) | 5 | 13.65 (8.53 to 19.17) | 5.38 (3.52 to 8.34) | 2.59 (2.06 to 3.09) | not run |
<!-- END table:mccfr -->

**Reading.**

* **Simple averaging is erratic late in the run.** Its median largest gain was
  <!--v:mccfr_simple_mid-->3.74<!--/v--> mA after <!--v:mccfr_full_iters-->3·10⁵<!--/v--> iterations and
  <!--v:mccfr_simple_1e6-->2.94<!--/v--> mA after <!--v:mccfr_simple_iters-->10⁶<!--/v-->, but
  <!--v:mccfr_worse-->4<!--/v--> of its <!--v:mccfr_simple_seeds-->10<!--/v--> seeds were worse
  at the later checkpoint, <!--v:mccfr_worse_40-->2<!--/v--> of them above 40 mA. Across seeds,
  the largest gain at the end ranges from <!--v:mccfr_simple_lo-->0.84<!--/v--> to
  <!--v:mccfr_simple_hi-->44.38<!--/v--> mA.
* **Full averaging is steadier where it was run.** After
  <!--v:mccfr_full_iters-->3·10⁵<!--/v--> iterations its median was
  <!--v:mccfr_full_mid-->2.59<!--/v--> mA, with every seed between <!--v:mccfr_full_lo-->2.06<!--/v-->
  and <!--v:mccfr_full_hi-->3.09<!--/v--> mA.
* **This does not isolate the bias.** With <!--v:mccfr_full_seeds-->5<!--/v--> and
  <!--v:mccfr_simple_seeds-->10<!--/v--> seeds, and full averaging stopped at
  <!--v:mccfr_full_iters-->3·10⁵<!--/v--> iterations, sampling noise could explain part of the
  difference. A fair test would run both modes for equal time over many more seeds.
* **Full-width solvers do far better on a game this small.** Every full-width CFR variant with
  alternating updates ends below the best MCCFR seed (Section 2.1).

### 2.7 Three-player Leduc (stretch, time-boxed)

OpenSpiel `leduc_poker(players=3)` uses an 8-card deck and two betting rounds, and has
<!--v:leduc_infosets-->25,800<!--/v--> infostates. We ran OpenSpiel's C++ external-sampling MCCFR
(simple averaging, two seeds) and C++ CFR+, with C++ best responses at a few checkpoints. One
evaluation, three best responses plus the profile's value, takes about
<!--v:leduc_eval_seconds-->18<!--/v--> seconds.

<!-- BEGIN table:leduc -->
| Run | Iterations | Training time (s) | Gains P1 / P2 / P3 (mA) | Values P1 / P2 / P3 (mA) |
|---|---|---|---|---|
| OpenSpiel ES-MCCFR, seed 0 | 10,000 | 1 | 879 / 991 / 1056 | -125 / -57 / 182 |
| OpenSpiel ES-MCCFR, seed 0 | 100,000 | 8 | 347 / 288 / 325 | -89 / -10 / 100 |
| OpenSpiel ES-MCCFR, seed 0 | 1,000,000 | 74 | 147 / 77 / 85 | -82 / -14 / 96 |
| OpenSpiel ES-MCCFR, seed 1 | 10,000 | 1 | 1053 / 1049 / 1218 | -144 / 14 / 131 |
| OpenSpiel ES-MCCFR, seed 1 | 100,000 | 8 | 374 / 278 / 342 | -86 / -19 / 105 |
| OpenSpiel ES-MCCFR, seed 1 | 1,000,000 | 75 | 173 / 72 / 84 | -78 / -17 / 95 |
| OpenSpiel CFR+ | 10 | 33 | 820 / 649 / 554 | -378 / 55 / 322 |
| OpenSpiel CFR+ | 30 | 99 | 228 / 139 / 108 | -113 / -25 / 137 |
<!-- END table:leduc -->

Nothing here is close to converged. For scale, MacQueen and Wright report that CFR+ run for
1,000 iterations from random initial regrets always reached ε ≤ 0.013 chips (13 mA) on this
game, and that vanilla CFR reached ε ≤ 0.017 after 10,000 iterations. Abou Risk and Szafron's
best responses gained up to 0.130 chips per hand against their CFR strategy. This time box ran
CFR+ for <!--v:leduc_cfrplus_iters-->30<!--/v--> iterations. We draw no conclusions about Leduc's
equilibria from these runs. Seat values are dominated by convergence error.

### 2.8 Limits

* **Kuhn is tiny.** Its equilibrium structure (P1 never opens, P2 controls a transfer) is
  specific to the game. The point carried forward is the *phenomena*, not the numbers.
* **Starting points are one perturbation.** Random initial strategies vary only the first
  iterate. Other perturbations (initial regrets, update order, sampling noise) could select
  differently.
* **Unreached-infostate ranges are single-parameter.** They are found on a grid, with the other
  parameters fixed. Joint changes, as Ganzfried's example shows, can do more.
* **"Converged" means small gains, not an exact equilibrium.** We did not project runs onto exact
  equilibria. On-path closeness to the family is measured by constraint violation, not by
  distance to a nearest member.
* **The CCE gap is measured only for simultaneous-update CFR.** Alternating updates do not
  produce one shared sequence of joint profiles.

## 3. Literature

Every entry was checked on 2026-10-14: title, authors, venue and identifier, against the source
named in the "Verified" column. "Read" says how much of each paper was read for this spike;
everything the text above takes from a paper comes from the part marked as read.

| Reference | Verified | Relevance here | Read |
|---|---|---|---|
| Szafron, Gibson, Sturtevant. *A Parameterized Family of Equilibrium Profiles for Three-Player Kuhn Poker.* AAMAS 2013, pp. 247–254. | Yes: the published PDF on ifaamas.org | The analytic family used in Section 2.4: Tables 1–4, utilities, the equilibrium-selection discussion, proofs. Found the family by inspecting Monte Carlo CFR solutions from different seeds. Leaves open whether other equilibria exist. | In full |
| Ganzfried. *Quadratic Programming Approach for Nash Equilibrium Computation in Multiplayer Imperfect-Information Games.* arXiv:2509.25618 (v1 30 Sep 2025, v3 6 Jul 2026); *Games* 17(1):9, 2026, doi:10.3390/g17010009. | Yes: arXiv listing; journal version in Crossref (the publisher's page refused automated access) | Exact Nash via a nonconvex quadratic program (Gurobi). Solves 3-player Kuhn with dominated actions removed in 2.47 s; not the full game in 24 h. One exact equilibrium (β = 0 values) that differs from the family off the path. Gambit's logit QRE gives a family member with different values. Counts 601 tree nodes with a single deal node. | v3 in full; v1 compared with it line by line (they differ only in references and typesetting) |
| Ganzfried. *Variable Bound Tightening for Nash Equilibrium Computation in Multiplayer Imperfect-Information Games.* arXiv:2606.25997 (v1 24 Jun 2026, v2 30 Jun 2026). | Yes: arXiv listing | Bounds on slack variables let the same approach solve the *full* 3-player Kuhn game in 1.16 s, against more than 24 h before. Seat values of that solution are not reported. Cites the quadratic-programming paper as published in *Games*. | Abstract and Section 4 (experiments) |
| Ganzfried. *Projected Exploitability Descent for Nash Equilibrium Computation in Multiplayer Imperfect-Information Games.* arXiv:2606.29169 (v1 28 Jun 2026). | Yes: arXiv listing | Subgradient descent on a sum-of-gains proxy; tested on d-card 3-player Kuhn from uniform starts, reporting average strategies. On the 5-card game, vanilla CFR "performed extremely well in the first several hundred iterations before later worsening significantly". No exact solution of the 5-card game is known: the exact approach failed in 8 h. | Abstract, benchmark description and first results |
| Ganzfried. *Empirical Analysis of Fictitious Play for Nash Equilibrium Computation in Multiplayer Games.* FLAIRS-38, 2025, doi:10.32473/flairs.38.1.138636; arXiv:2001.11165. | Yes: arXiv listing (which says it subsumes the 2020 article *Fictitious Play Outperforms Counterfactual Regret Minimization*) and Crossref | Reports fictitious play approximating Nash better than CFR across multiplayer game classes, and random restarts helping fictitious play. | Abstract only |
| Ganzfried. *Dominated Actions in Imperfect-Information Games.* arXiv:2504.09716 (v1 13 Apr 2025, v9 22 Jul 2026). | Yes: arXiv listing | Polynomial-time test for dominated actions in **two-player** perfect-recall games with publicly observable actions. The quadratic-programming paper cites it for removing dominated actions before solving, but the actions it removes in 3-player Kuhn are Szafron et al.'s Table 2 values. | Abstract only |
| Wang, Yan, Dou, Huang, Yang, Deng. *Approximating N-Player Nash Equilibrium through Gradient Descent.* arXiv:2501.03001 (Jan 2025). | Yes: arXiv listing | Gradient descent on a best-response-based distance to Nash in normal-form games. | Abstract only |
| MacQueen, Wright. *Guarantees for Self-Play in Multiplayer Games via Polymatrix Decomposability.* NeurIPS 2023 (Advances in Neural Information Processing Systems 36); arXiv:2310.11518. | Yes: NeurIPS proceedings page and arXiv listing | No-regret self-play gives a CCE; deployed strategies are its marginals. CCE marginals are approximately Nash when the game is close to a constant-sum polymatrix game, and their vulnerability is bounded when that game is also subgame stable. On 3-player Leduc, measured δ = 0.009 and γ = 0.004 near CFR+ strategies (CFR+ run for 1,000 iterations from random initial regrets); CFR+ always reached ε ≤ 0.013, and vanilla CFR ε ≤ 0.017 after 10,000 iterations. | Abstract, Sections 3–4, the Leduc experiments and Appendix G |
| Abou Risk, Szafron. *Using Counterfactual Regret Minimization to Create Competitive Multiplayer Poker Agents.* AAMAS 2010, pp. 159–166. | Yes: the authors' publication page (University of Alberta) and the reference list of Szafron et al. 2013 | Introduced 3-player Kuhn and Leduc. Found CFR reached an ε-Nash equilibrium in 3-player Kuhn (ε = 0.0017) but not in 3-player Leduc, where best responses (themselves computed with CFR) gained 0.119, 0.130 and 0.111 chips per hand. | Game definitions and results, in the authors' preprint |
| Gibson. *Regret Minimization in Non-Zero-Sum Games with Applications to Building Champion Multiplayer Computer Poker Agents.* arXiv:1305.0034 (2013). | Yes: arXiv listing | CFR avoids iteratively strictly dominated actions and strategies, a refinement beyond plain CCE. | Abstract only |
| Gibson, Szafron. *On Strategy Stitching in Large Extensive Form Multiplayer Games.* NIPS 2011 (Advances in Neural Information Processing Systems 24). | Yes: NeurIPS proceedings page | Base strategy plus static subgame "experts" for 3-player Leduc and limit hold'em; won the 3-player events of the 2010 Annual Computer Poker Competition. | Abstract only |
| Brown, Sandholm. *Superhuman AI for multiplayer poker.* *Science* 365(6456):885–890, 2019. | Yes: citation details from the NSF public-access listing | Six-player no-limit hold'em agent built on self-play plus search; no equilibrium guarantee. Per OpenSpiel's source, its MCCFR used the simple averaging scheme of Section 2.6. | Not read: the paper and supplement were not retrievable here. Commonly cited method details (a Linear MCCFR blueprint and depth-limited search) were **not** checked against the paper. |
| Zhang, Farina, Sandholm. *Team Belief DAG: Generalizing the Sequence Form to Team Games for Fast Computation of Correlated Team Max-Min Equilibria via Regret Minimization.* ICML 2023, PMLR 202:40996–41018; arXiv:2202.00789. | Yes: PMLR page and arXiv listing | A convex representation of a team's correlated strategies, allowing regret minimization. The tool for an exact "two opponents collude" metric (Section 4). | Abstract only |
| Farina, Celli, Gatti, Sandholm. *Connecting Optimal Ex-Ante Collusion in Teams to Extensive-Form Correlation: Faster Algorithms and Positive Complexity Results.* ICML 2021, PMLR 139:3164–3173. | Yes: PMLR page | Optimal team strategy against an opponent when team members coordinate only before play. Column generation is three orders of magnitude faster than earlier methods. | Abstract only |
| Daskalakis, Goldberg, Papadimitriou. *The Complexity of Computing a Nash Equilibrium.* SIAM J. Comput. 39(1):195–259, 2009. | Yes: the published PDF (author's copy) | Finding a Nash equilibrium in three-player games is PPAD-complete; the abstract notes that later work extended this to two-player games. | Abstract and introduction |

Unverified: only the Pluribus method details noted above.

## 4. Recommendations

### 4a. A multiway StrategyBench metric

**The problem.** In two players, M1 to M3 are measured against "the" equilibrium, which is
well-defined. In three players, a subject's loss depends on which equilibrium the other seats
play, and there is no maxmin guarantee to measure against. The metric has to be defined per
seat, with the other seats held fixed.

**Proposed definitions.** Put the subject's estimated strategy σ̂ in seat k. The other seats play
a fixed **reference profile** R, an approximate Nash equilibrium. Then:

| Metric | Definition | Notes |
|---|---|---|
| **Seat regret** | best-response value in seat k against R's other seats, minus the subject's value | Never negative. The direct analogue of "how much the subject leaves on the table". Equals the loss against the reference when R is an exact equilibrium. |
| **Loss vs reference** | R's own value in seat k minus the subject's value | The analogue of M3. Inherits M3's weakness: right actions with wrong frequencies can show no loss. |
| **Single-opponent exploitation** | for each other seat j: best-response value of j with the third seat fixed, minus j's current value | The analogue of M2. Reports who pays: part of j's gain can come from the bystander, not the subject. |
| **Single-opponent punishment** | for each other seat j: subject's value minus its value when j plays to *minimise* it | Subject-centred worst case from one adversary. Non-zero even for an exact equilibrium strategy. |
| **Self-play table gains** | each seat's best-response gain when σ̂ plays every seat | The analogue of StrategyBench's current setup, where the LLM plays every seat. |
| **Team punishment (later)** | subject's value minus its value when both opponents jointly minimise it | Needs team-game machinery (TB-DAG, ex-ante collusion). Not computed here. |

**Reference choice is part of the metric.** Report each metric against a *set* of reference
equilibria and give the range, not a single number. On three-player Kuhn, the natural set is the
analytic family's two extreme members, β = 0 and β = ¼, plus the CFR+ solution. In games without
an analytic family, use several CFR+ runs from random starts. Label results "relative to
reference set R", never "vs equilibrium".

**Demonstration on three-player Kuhn** (`seat_metric.py`). Reference profiles:

<!-- BEGIN table:seat-references -->
| Reference profile | Largest gain (mA) | P1 (mA) | P2 (mA) | P3 (mA) |
|---|---|---|---|---|
| family beta=0 | 0 | -20.83 | -20.83 | 41.67 |
| family beta=1/4 | 0 | -31.25 | -20.83 | 52.08 |
| CFR+ (OpenSpiel, 5000 iterations) | 8.3e-04 | -26.48 | -20.83 | 47.32 |
<!-- END table:seat-references -->

Uniform-random subject:

<!-- BEGIN table:seat-uniform -->
| Seat | Other seats play | Subject value (mA) | Reference value in that seat (mA) | Loss vs reference (mA) | Seat regret (mA) | Largest opponent gain (mA, who) | Paid by subject / bystander (mA) | Largest punishment loss (mA) |
|---|---|---|---|---|---|---|---|---|
| P1 | family beta=0 | -171.87 | -20.83 | 151.04 | 151.04 | 291.67 (P2) | 296.88 / -5.21 | 296.88 |
| P1 | family beta=1/4 | -296.87 | -31.25 | 265.62 | 265.62 | 218.75 (P3) | 210.94 / 7.81 | 221.35 |
| P1 | CFR+ (OpenSpiel, 5000 iterations) | -178.95 | -26.48 | 152.47 | 152.47 | 229.91 (P2) | 248.01 / -18.09 | 267.40 |
| P2 | family beta=0 | -171.87 | -20.83 | 151.04 | 151.04 | 239.58 (P1) | 338.54 / -98.96 | 401.04 |
| P2 | family beta=1/4 | -171.87 | -20.83 | 151.04 | 151.04 | 406.25 (P1) | 401.04 / 5.21 | 401.04 |
| P2 | CFR+ (OpenSpiel, 5000 iterations) | -145.84 | -20.83 | 125.00 | 125.00 | 351.03 (P1) | 427.08 / -76.05 | 427.08 |
| P3 | family beta=0 | -62.50 | 41.67 | 104.17 | 104.17 | 437.50 (P1) | 500.00 / -62.50 | 500.00 |
| P3 | family beta=1/4 | -187.50 | 52.08 | 239.58 | 239.58 | 244.79 (P1) | 190.10 / 54.69 | 433.59 |
| P3 | CFR+ (OpenSpiel, 5000 iterations) | -118.68 | 47.32 | 166.00 | 166.00 | 302.31 (P1) | 465.09 / -162.78 | 465.09 |
<!-- END table:seat-uniform -->

The subject is an equilibrium strategy from a *different* family member: c11 = ½ and β = ¼, the
strategy player 2 plays in Szafron et al.'s Table 4.

<!-- BEGIN table:seat-mismatch -->
| Seat | Other seats play | Subject value (mA) | Reference value in that seat (mA) | Loss vs reference (mA) | Seat regret (mA) | Largest opponent gain (mA, who) | Paid by subject / bystander (mA) | Largest punishment loss (mA) |
|---|---|---|---|---|---|---|---|---|
| P1 | family beta=0 | -20.83 | -20.83 | 0.00 | 0.00 | 0.00 (P2) | 0.00 / 0.00 | 62.50 |
| P1 | family beta=1/4 | -31.25 | -31.25 | 0.00 | 0.00 | 0.00 (P3) | -10.42 / 10.42 | 31.25 |
| P1 | CFR+ (OpenSpiel, 5000 iterations) | -26.48 | -26.48 | 0.00 | 0.00 | 0.00 (P3) | 16.72 / -16.72 | 47.09 |
| P2 | family beta=0 | -31.25 | -20.83 | 10.42 | 10.42 | 0.00 (P3) | 10.42 / -10.42 | 46.87 |
| P2 | family beta=1/4 | -31.25 | -20.83 | 10.42 | 10.42 | 166.67 (P1) | 46.87 / 119.79 | 46.87 |
| P2 | CFR+ (OpenSpiel, 5000 iterations) | -20.83 | -20.83 | 0.00 | 0.00 | 111.44 (P1) | 46.88 / 64.57 | 46.88 |
| P3 | family beta=0 | 41.67 | 41.67 | 0.00 | 0.00 | 0.00 (P2) | 0.00 / 0.00 | 125.00 |
| P3 | family beta=1/4 | 52.08 | 52.08 | 0.00 | 0.00 | 52.08 (P1) | -20.83 / 72.92 | 135.42 |
| P3 | CFR+ (OpenSpiel, 5000 iterations) | 47.32 | 47.32 | 0.00 | 0.00 | 10.90 (P1) | 2.06 / 8.84 | 130.65 |
<!-- END table:seat-mismatch -->

Subject in every seat:

<!-- BEGIN table:seat-selfplay -->
| Subject in every seat | P1 gain (mA) | P2 gain (mA) | P3 gain (mA) |
|---|---|---|---|
| uniform random | 546.87 | 692.71 | 822.92 |
| always bet or call | 500.00 | 500.00 | 500.00 |
| passive (never bet, call only with the Ace) | 166.67 | 166.67 | 166.67 |
| equilibrium strategy from another member (c11=1/2, beta=1/4) | 0.00 | 0.00 | 0.00 |
<!-- END table:seat-selfplay -->

**What the demonstration shows.**

* **The reference set matters.** The uniform subject's seat-1 loss is
  <!--v:seat_u_ratio-->1.76<!--/v--> times as large against the β = ¼ reference as against β = 0.
* **A flawless subject can look like a weak one.** An equilibrium strategy measured against a
  different equilibrium shows a loss of <!--v:seat_eq_p2_loss-->10.42<!--/v--> mA in seat 2: the κβ
  transfer of the paper's Table 4, at β = ¼. In seat 2 against the β = ¼ reference it also lets
  player 1 gain <!--v:seat_mix_p1_gain-->166.67<!--/v--> mA.
* **Opponent-gain numbers need the "who pays" split.** In that case the subject pays
  <!--v:seat_mix_paid_subject-->46.87<!--/v--> mA of player 1's gain and the bystander, player 3,
  pays <!--v:seat_mix_paid_bystander-->119.79<!--/v--> mA.
* **The split depends on which best response is chosen.** Best responses here break ties towards
  passing, so a "paid by" split describes one best response. In the seat-1 rows of the mismatch
  table the largest opponent gain is 0.00, and the split only shows how that tie-break moves
  chips between the other two players.

**How it would be computed in StrategyBench.** Proposed changes only; none are made in this spike.

1. **`estimation/` needs nothing for direct mode.** Infostate enumeration already handles any
   number of players. Play mode's seat loops and intervals assume two seats: `range(2)` in
   `estimation/play.py`.
2. **A new `analysis/multiway.py`.** The existing `metrics.py` and `breakdown.py` reject
   non-two-player games by design and should stay that way. The new module would compute the
   table above from (game, σ̂, seat, reference profile). It would use OpenSpiel's
   `best_response` with the other seats fixed. For punishment, it needs a best response to
   minus the subject's payoff; OpenSpiel's best response has no utility override, so this
   needs either a small tree walk (as in `research/multiway/tabular.py`) or a negated-payoff
   game wrapper.
3. **Reference sets in `baselines/`.** Several CFR+ runs from random starts, cached like the
   current equilibrium, plus analytic members where they exist.
4. **Bootstrap.** Unchanged in principle: resample σ̂, recompute each metric per reference.
   Report the interval per reference and the range across references.
5. **Games and prompts.** A `GameSpec` for `kuhn_poker(players=3)` and a prompt template with
   three seat texts.

**Effort.**

| Item | Estimate |
|---|---|
| Three-player Kuhn `GameSpec`, prompt and tests | 0.5–1 day |
| `analysis/multiway.py` with sanity tests (family members give zero seat regret; this spike's numbers reproduce) | 2–3 days |
| Reference sets and caching | 0.5 day |
| Bootstrap and site integration (new columns, reference labels) | 1–2 days |
| **Total for three-player Kuhn** | **about one working week** |
| Three-player Leduc | Add solver time for the reference set: many CFR+ iterations at about <!--v:leduc_cfrplus_s_per_it-->3.3<!--/v--> s each; overnight-scale compute |

### 4b. A multiway solver research track

This track stays clean-room: public papers and OpenSpiel only, small games only. No-limit
hold'em stays out of scope. The order below builds measurement first, because every later step
needs it.

1. **An n-player evaluation harness** (2–3 days). Per-player gains, the CCE gap of iterate
   sequences, seat values, and distance to known equilibria. `tabular.py` already does this for
   trees that fit in memory. Port its ideas to OpenSpiel C++ best responses for Leduc-size games.
2. **Equilibrium-selection study** (1 week). On d-card three-player Kuhn and three-player Leduc,
   map which equilibria CFR, CFR+, linear and discounted CFR, MCCFR (both averaging modes),
   fictitious play and its random restarts select. Measure how the selection depends on starts
   and seeds, using seat values as the fingerprint. This spike is the 4-card pilot.
3. **Exactness on small games** (1–2 weeks). Reproduce the quadratic-programming approach with an
   open-source solver if one can handle it, otherwise document the dependency. Use it to certify
   CFR outputs, and to search for on-path equilibria outside the Szafron family, which is open.
   Removing dominated actions is a cheap first step. Ganzfried's polynomial-time test covers
   two-player games only; a three-player version is not in that paper.
4. **Robustness, not just equilibrium** (1–2 weeks). Compute vulnerability and punishment bounds
   (MacQueen and Wright's δ and γ) for solver outputs. Add team-best-response evaluation
   (TB-DAG or ex-ante collusion) to measure how much two opponents could take by coordinating.
   For a multiway "solver" this is arguably the quantity users care about.
5. **Scaling ideas** (open-ended). Sampled CFR with correct averaging, subgame decomposition or
   strategy stitching, and depth-limited search. Most of this is engineering for games beyond
   this project's exact-computation range, so it waits until no-limit hold'em is in scope.

**What is genuinely open:**

* **Which equilibrium.** No principled, computable criterion picks *the* equilibrium to play in
  multiway poker. Candidates include maximin over the equilibrium set, robustness to mismatch
  (Szafron et al.'s Section 6), and refinements such as sequential equilibrium (Ganzfried notes
  the logit path converges to one).
* **Is three-player Kuhn's equilibrium set fully known?** Equilibria outside the family exist off
  the path. Whether any differ on the path, with seat values outside the family's range, is not
  known.
* **When is self-play safe?** Guarantees exist for near-polymatrix, subgame-stable games
  (MacQueen and Wright). Whether real poker variants qualify is measured empirically, not proved.
* **Exact computation scales very poorly.** Exact solving stops at the 4-card three-player Kuhn
  game. No exact solution of the 5-card game is known.

## Appendix A. Every run

On-path and off-path violations are the largest constraint violations against the closest
sub-family (Section 2.4).

<!-- BEGIN table:per-run -->
| Run | Largest gain (mA) | P1 (mA) | P2 (mA) | P3 (mA) | β | Closest sub-family | On-path violation | Off-path violation |
|---|---|---|---|---|---|---|---|---|
| CFR, uniform | 0.08 | -28.79 | -20.83 | 49.62 | 0.191 | c11=0 | 1.1e-03 | 2.5e-05 |
| CFR, random init 1 | 0.08 | -30.28 | -20.76 | 51.03 | 0.226 | c11=0 | 4.0e-03 | 4.9e-05 |
| CFR, random init 2 | 0.08 | -27.92 | -20.83 | 48.75 | 0.170 | c11=0 | 2.0e-03 | 4.3e-05 |
| CFR, random init 3 | 0.09 | -28.12 | -20.82 | 48.94 | 0.175 | c11=0 | 1.1e-03 | 4.8e-05 |
| CFR, random init 4 | 0.11 | -27.42 | -20.83 | 48.25 | 0.159 | c11=0 | 1.6e-03 | 4.5e-05 |
| CFR, random init 5 | 0.09 | -27.76 | -20.78 | 48.53 | 0.165 | c11=0 | 3.3e-03 | 5.0e-05 |
| CFR, random init 6 | 0.10 | -28.84 | -20.84 | 49.69 | 0.193 | c11=0 | 1.9e-03 | 8.5e-05 |
| CFR, random init 7 | 0.08 | -29.68 | -20.78 | 50.47 | 0.212 | c11=0 | 3.9e-03 | 4.8e-05 |
| CFR, random init 8 | 0.08 | -29.05 | -20.79 | 49.84 | 0.197 | c11=0 | 3.5e-03 | 9.2e-05 |
| CFR, random init 9 | 0.08 | -30.24 | -20.82 | 51.06 | 0.226 | c11=0 | 1.2e-03 | 4.8e-05 |
| CFR, random init 10 | 0.08 | -28.64 | -20.83 | 49.46 | 0.187 | c11=0 | 1.5e-03 | 4.2e-05 |
| CFR+, uniform | 3.1e-04 | -26.56 | -20.83 | 47.39 | 0.137 | c11=1/2 | 3.4e-06 | 9.3e-08 |
| CFR+, random init 1 | 1.4e-04 | -24.59 | -20.83 | 45.42 | 0.090 | c11=0 | 7.4e-06 | 3.6e-08 |
| CFR+, random init 2 | 3.3e-04 | -26.79 | -20.83 | 47.62 | 0.143 | c11=1/2 | 3.6e-06 | 6.8e-02 |
| CFR+, random init 3 | 8.7e-04 | -26.26 | -20.83 | 47.09 | 0.130 | c11=0 | 1.0e-05 | 2.5e-02 |
| CFR+, random init 4 | 5.2e-04 | -25.33 | -20.83 | 46.17 | 0.108 | c11=0 | 6.3e-06 | 3.9e-08 |
| CFR+, random init 5 | 4.8e-05 | -25.34 | -20.83 | 46.17 | 0.108 | c11=1/2 | 2.0e-06 | 5.4e-08 |
| CFR+, random init 6 | 8.3e-04 | -26.90 | -20.83 | 47.74 | 0.146 | c11=1/2 | 9.7e-06 | 4.6e-08 |
| CFR+, random init 7 | 6.5e-04 | -25.74 | -20.83 | 46.58 | 0.118 | c11=0 | 8.4e-06 | 1.1e-02 |
| CFR+, random init 8 | 6.9e-04 | -26.60 | -20.83 | 47.44 | 0.138 | c11=1/2 | 7.9e-06 | 1.5e-08 |
| CFR+, random init 9 | 2.1e-04 | -24.84 | -20.83 | 45.67 | 0.096 | c11=1/2 | 4.2e-06 | 1.7e-07 |
| CFR+, random init 10 | 3.3e-05 | -26.08 | -20.83 | 46.92 | 0.126 | c11=1/2 | 4.1e-06 | 1.0e-08 |
| Linear CFR, uniform | 2.2e-03 | -26.07 | -20.83 | 46.91 | 0.126 | c11=0 | 2.4e-05 | 2.5e-09 |
| Linear CFR, random init 1 | 1.6e-03 | -30.34 | -20.83 | 51.17 | 0.228 | c11=0 | 1.8e-05 | 4.9e-09 |
| Linear CFR, random init 2 | 2.7e-03 | -25.78 | -20.83 | 46.61 | 0.119 | c11=0 | 2.8e-05 | 8.1e-09 |
| Linear CFR, random init 3 | 3.7e-03 | -28.78 | -20.83 | 49.61 | 0.191 | c11=0 | 2.8e-05 | 9.1e-07 |
| Linear CFR, random init 4 | 3.0e-03 | -29.09 | -20.83 | 49.92 | 0.198 | c11=0 | 3.4e-05 | 4.5e-09 |
| Linear CFR, random init 5 | 1.6e-03 | -30.61 | -20.83 | 51.44 | 0.235 | c11=0 | 1.8e-05 | 5.0e-09 |
| Linear CFR, random init 6 | 1.7e-03 | -30.63 | -20.83 | 51.46 | 0.235 | c11=0 | 2.0e-05 | 1.5e-08 |
| Linear CFR, random init 7 | 1.7e-03 | -30.50 | -20.83 | 51.33 | 0.232 | c11=0 | 1.9e-05 | 4.8e-09 |
| Linear CFR, random init 8 | 1.9e-03 | -29.95 | -20.83 | 50.78 | 0.219 | c11=0 | 2.2e-05 | 1.5e-08 |
| Linear CFR, random init 9 | 1.8e-03 | -30.12 | -20.83 | 50.95 | 0.223 | c11=0 | 2.1e-05 | 4.8e-09 |
| Linear CFR, random init 10 | 1.9e-03 | -30.00 | -20.83 | 50.83 | 0.220 | c11=0 | 2.2e-05 | 4.2e-09 |
| CFR simultaneous, uniform | 0.83 | -29.43 | -20.33 | 49.77 | 0.198 | c11=0 | 2.4e-02 | 8.7e-05 |
| CFR simultaneous, random init 1 | 1.60 | -27.97 | -19.98 | 47.96 | 0.140 | c11=0 | 5.9e-02 | 5.2e-03 |
| CFR simultaneous, random init 2 | 1.71 | -28.22 | -19.83 | 48.05 | 0.155 | c11=0 | 8.8e-02 | 6.4e-05 |
| CFR simultaneous, random init 3 | 1.00 | -30.82 | -20.25 | 51.08 | 0.234 | c11=0 | 2.8e-02 | 1.2e-04 |
| CFR simultaneous, random init 4 | 0.72 | -27.55 | -20.76 | 48.31 | 0.147 | c11=0 | 1.4e-02 | 4.5e-05 |
| CFR simultaneous, random init 5 | 1.42 | -26.41 | -20.79 | 47.20 | 0.136 | 0<c11<1/2 | 5.4e-02 | 9.9e-05 |
| Fictitious play, uniform | 1.06 | -29.36 | -20.16 | 49.52 | 0.199 | c11=0 | 2.5e-02 | 7.5e-05 |
| Fictitious play, random init 1 | 1.03 | -30.73 | -20.30 | 51.03 | 0.233 | c11=0 | 3.0e-02 | 4.9e-05 |
| Fictitious play, random init 2 | 0.87 | -31.33 | -20.46 | 51.79 | 0.231 | c11=0 | 1.4e-02 | 6.0e-05 |
| Fictitious play, random init 3 | 1.44 | -30.75 | -19.90 | 50.65 | 0.228 | c11=0 | 5.0e-02 | 9.2e-05 |
| Fictitious play, random init 4 | 0.94 | -29.62 | -20.23 | 49.85 | 0.185 | c11=0 | 2.6e-02 | 4.5e-05 |
| Fictitious play, random init 5 | 1.04 | -29.64 | -20.06 | 49.70 | 0.201 | c11=0 | 4.4e-02 | 9.9e-05 |
| Fictitious play, random init 6 | 1.16 | -30.60 | -19.63 | 50.23 | 0.229 | c11=0 | 1.1e-01 | 2.1e-04 |
| Fictitious play, random init 7 | 0.86 | -31.06 | -20.12 | 51.18 | 0.234 | c11=0 | 2.5e-02 | 1.2e-04 |
| Fictitious play, random init 8 | 1.09 | -29.83 | -20.25 | 50.08 | 0.218 | c11=0 | 4.4e-02 | 1.9e-04 |
| Fictitious play, random init 9 | 0.71 | -30.25 | -20.38 | 50.62 | 0.215 | c11=0 | 1.4e-02 | 4.8e-05 |
| Fictitious play, random init 10 | 0.81 | -29.50 | -20.45 | 49.94 | 0.205 | c11=0 | 2.8e-02 | 1.1e-04 |
| OpenSpiel CFR | 0.08 | -28.79 | -20.83 | 49.62 | 0.191 | c11=0 | 1.1e-03 | 2.5e-05 |
| OpenSpiel CFR+ | 3.1e-04 | -26.56 | -20.83 | 47.39 | 0.137 | c11=1/2 | 3.4e-06 | 9.3e-08 |
| OpenSpiel ES-MCCFR (simple averaging), seed 0 | 2.37 | -27.78 | -20.43 | 48.21 | 0.133 | c11=0 | 2.7e-02 | 1.0e-02 |
| OpenSpiel ES-MCCFR (simple averaging), seed 1 | 11.11 | -28.54 | -19.42 | 47.96 | 0.186 | c11=0 | 9.7e-02 | 3.1e-02 |
| OpenSpiel ES-MCCFR (simple averaging), seed 2 | 2.58 | -26.66 | -20.17 | 46.84 | 0.168 | c11=0 | 1.9e-01 | 1.9e-03 |
| OpenSpiel ES-MCCFR (simple averaging), seed 3 | 1.76 | -28.94 | -19.25 | 48.19 | 0.191 | c11=0 | 1.1e-01 | 9.1e-04 |
| OpenSpiel ES-MCCFR (simple averaging), seed 4 | 43.20 | -29.23 | -19.63 | 48.86 | 0.195 | c11=0 | 8.5e-02 | 1.3e-01 |
| OpenSpiel ES-MCCFR (simple averaging), seed 5 | 14.33 | -29.39 | -19.66 | 49.05 | 0.206 | c11=0 | 1.2e-01 | 3.7e-02 |
| OpenSpiel ES-MCCFR (simple averaging), seed 6 | 44.38 | -26.88 | -20.24 | 47.12 | 0.174 | c11=1/2 | 1.6e-01 | 1.3e-01 |
| OpenSpiel ES-MCCFR (simple averaging), seed 7 | 3.30 | -28.99 | -19.25 | 48.24 | 0.167 | c11=1/2 | 8.0e-02 | 5.2e-03 |
| OpenSpiel ES-MCCFR (simple averaging), seed 8 | 0.84 | -25.88 | -20.29 | 46.17 | 0.106 | c11=0 | 1.8e-02 | 6.6e-03 |
| OpenSpiel ES-MCCFR (simple averaging), seed 9 | 1.44 | -25.69 | -20.78 | 46.47 | 0.136 | c11=0 | 4.2e-02 | 1.2e-01 |
| OpenSpiel ES-MCCFR (full averaging), seed 0 | 2.06 | -28.74 | -19.41 | 48.14 | 0.184 | c11=0 | 8.4e-02 | 8.2e-05 |
| OpenSpiel ES-MCCFR (full averaging), seed 1 | 3.09 | -28.40 | -19.34 | 47.74 | 0.187 | c11=0 | 1.4e-01 | 1.9e-04 |
| OpenSpiel ES-MCCFR (full averaging), seed 2 | 2.16 | -26.52 | -19.70 | 46.22 | 0.087 | c11=1/2 | 7.4e-02 | 1.8e-02 |
| OpenSpiel ES-MCCFR (full averaging), seed 3 | 2.82 | -30.49 | -19.71 | 50.20 | 0.224 | c11=0 | 5.7e-02 | 1.7e-04 |
| OpenSpiel ES-MCCFR (full averaging), seed 4 | 2.59 | -27.82 | -20.56 | 48.38 | 0.221 | c11=0 | 1.9e-01 | 2.7e-05 |
<!-- END table:per-run -->

## Appendix B. Reproducing

```bash
uv run pytest research/multiway                           # solver checks (not part of CI)
uv run python research/multiway/run_kuhn3.py              # about 14 minutes; --part family|solvers|mccfr
uv run python research/multiway/seat_metric.py            # seconds
uv run python research/multiway/run_leduc3.py             # about 7 minutes
uv run python research/multiway/make_tables.py            # rewrites the tables and quoted numbers here
```

All runs are deterministic given their seeds: re-running every script on 2026-10-14 reproduced
the earlier result files exactly, apart from timings. Results were produced with OpenSpiel
<!--v:openspiel_version-->2.0.2<!--/v-->. Run times are from one run on an Apple M2 Max laptop.
