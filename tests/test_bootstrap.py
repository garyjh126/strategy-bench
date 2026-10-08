"""Bootstrap: basic intervals, bias correction, and why percentile intervals are not reported."""

import numpy as np
import pytest

from strategybench.analysis.bootstrap import METRIC_KEYS, basic_ci, bootstrap_metrics, percentile_ci
from strategybench.analysis.metrics import solve_equilibrium
from strategybench.baselines.scripted import first_action_policy
from strategybench.estimation.infostates import enumerate_infostates
from strategybench.games import get_game_spec

GAME = get_game_spec("kuhn").load()
INFOS = enumerate_infostates(GAME)


@pytest.fixture(scope="module")
def eq():
    return solve_equilibrium("kuhn_poker", 2000)


def _counts(policy, n, rng):
    counts = {}
    for info in INFOS:
        probs = policy.action_probabilities(info.state)
        actions = list(info.legal_actions)
        draws = rng.multinomial(n, np.array([probs[a] for a in actions]) / sum(probs[a] for a in actions))
        counts[info.key] = {a: int(d) for a, d in zip(actions, draws, strict=True) if d}
    return counts


def test_basic_interval_reflects_the_percentile_interval():
    values = [0.2, 0.3, 0.35, 0.5, 0.6]
    lo, hi = percentile_ci(values)
    assert basic_ci(0.3, values) == pytest.approx((0.6 - hi, 0.6 - lo))
    assert basic_ci(0.05, values) == (0.0, 0.0)  # reflected below zero, so clipped


def test_deterministic_subject_has_no_uncertainty(eq):
    counts = _counts(first_action_policy(GAME), 50, np.random.default_rng(0))
    boot = bootstrap_metrics(GAME, INFOS, counts, eq, 20, np.random.default_rng(1))
    for key in METRIC_KEYS:
        lo, hi = boot.basic[key]
        assert lo == pytest.approx(hi) == pytest.approx(boot.bias_corrected[key])
        assert boot.percentile[key] == pytest.approx(boot.basic[key])
        assert boot.bias[key] == pytest.approx(0.0, abs=1e-12)
    assert boot.bias_corrected["exploitability"] == pytest.approx(1.0, abs=1e-3)  # always-pass: 1 ante


def test_equilibrium_subject_percentile_interval_misses_and_basic_corrects(eq):
    # True exploitability is the reference's own (about 4e-5). Sampling noise can only be
    # exploited, so the estimate and every replicate overshoot it.
    counts = _counts(eq.policy, 100, np.random.default_rng(0))
    boot = bootstrap_metrics(GAME, INFOS, counts, eq, 100, np.random.default_rng(1))
    lo_pct, _ = boot.percentile["exploitability"]
    lo_basic, hi_basic = boot.basic["exploitability"]
    assert lo_pct > eq.exploitability  # the percentile interval excludes the truth
    assert boot.bias["exploitability"] > 0
    assert lo_basic <= boot.bias_corrected["exploitability"] <= hi_basic
    assert lo_basic < lo_pct
