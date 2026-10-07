"""Estimator convergence and bootstrap calibration, using a known noisy distribution."""

import numpy as np

from strategybench.analysis.bootstrap import bootstrap_statistic
from strategybench.estimation.infostates import enumerate_infostates
from strategybench.estimation.strategy import strategy_from_counts
from strategybench.games import get_game_spec

GAME = get_game_spec("kuhn").load()
INFOS = enumerate_infostates(GAME)
TRUE_P = 0.3  # probability of action 1 at every infostate


def _draw(n, rng):
    draws = rng.binomial(n, TRUE_P, len(INFOS))
    return {i.key: {1: int(k), 0: n - int(k)} for i, k in zip(INFOS, draws, strict=True)}


def test_estimate_converges_as_n_grows():
    rng = np.random.default_rng(0)
    errors = []
    for n in (20, 200, 2000, 20000):
        strat = strategy_from_counts(GAME, INFOS, _draw(n, rng))
        errors.append(max(abs(strat.policy.policy_for_key(i.key)[1] - TRUE_P) for i in INFOS))
    assert errors == sorted(errors, reverse=True)
    assert errors[-1] < 0.02


def test_bootstrap_ci_coverage_is_plausible():
    rng = np.random.default_rng(1)
    key = INFOS[0].key
    hits, trials = 0, 200
    for _ in range(trials):
        counts = _draw(100, rng)
        lo, hi = bootstrap_statistic(counts, lambda c: c[key].get(1, 0) / 100, 300, rng)
        hits += lo <= TRUE_P <= hi
    assert 0.88 <= hits / trials <= 0.99
