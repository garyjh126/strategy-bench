"""Play mode: simulated values against known exact values, reproducibility, fallbacks, cross-check."""

import pytest

from strategybench.adapters.mock import MockDistributionClient, MockTextClient, policy_lookup
from strategybench.analysis.metrics import exact_seat_values, solve_equilibrium
from strategybench.baselines.scripted import first_action_policy, uniform_policy
from strategybench.estimation.play import expected_subject_decisions, play_match
from strategybench.games import get_game_spec
from strategybench.prompts import DEFAULT_TEMPLATES
from strategybench.runner import RunConfig, run_direct, run_play

KUHN = get_game_spec("kuhn")
KUHN_T = DEFAULT_TEMPLATES["kuhn"]
GAME = KUHN.load()


@pytest.fixture(scope="module")
def eq():
    return solve_equilibrium(KUHN.load_string, 2000)


def _text(policy, **kw):
    return MockTextClient("t", policy_lookup(KUHN, KUHN_T, policy), vocabulary=KUHN.vocabulary(), **kw)


def test_always_pass_vs_equilibrium_matches_exact_value(eq):
    # Exact: always-pass as Player 1 scores -2/9 against Player 2's equilibrium (see test_metrics_kuhn).
    result = play_match(KUHN, KUHN_T, _text(first_action_policy(GAME)), eq.policy, "equilibrium", 20000)
    lo, hi = result.ci95(0)
    assert lo <= -2 / 9 <= hi
    assert result.seat_hands == [10000, 10000]
    assert result.fallbacks == 0


def test_play_is_reproducible(eq):
    a = play_match(KUHN, KUHN_T, _text(uniform_policy(GAME)), eq.policy, "equilibrium", 500, seed=3)
    b = play_match(KUHN, KUHN_T, _text(uniform_policy(GAME)), eq.policy, "equilibrium", 500, seed=3)
    c = play_match(KUHN, KUHN_T, _text(uniform_policy(GAME)), eq.policy, "equilibrium", 500, seed=4)
    assert a.seat_mean == b.seat_mean
    assert a.seat_mean != c.seat_mean


def test_failed_decisions_fall_back_and_are_counted(eq):
    client = _text(uniform_policy(GAME), garbage_rate=1.0)
    result = play_match(KUHN, KUHN_T, client, eq.policy, "equilibrium", 200, max_retries=1)
    assert result.fallbacks == result.subject_decisions > 0
    assert result.reliability.samples_failed == result.subject_decisions
    assert result.reliability.attempts == 2 * result.subject_decisions


def test_distribution_client_queries_each_prompt_once(eq):
    client = MockDistributionClient("u", policy_lookup(KUHN, KUHN_T, uniform_policy(GAME)))
    result = play_match(KUHN, KUHN_T, client, eq.policy, "equilibrium", 2000)
    assert client.calls <= 12
    exact = exact_seat_values(GAME, uniform_policy(GAME), eq.policy)
    for seat in range(2):
        lo, hi = result.ci95(seat)
        assert lo <= exact[seat] <= hi


def test_expected_decisions_kuhn_uniform():
    # Kuhn: seat 0 always acts once, again after check-bet (prob 1/4); seat 1 always acts once.
    value = expected_subject_decisions(GAME, uniform_policy(GAME), uniform_policy(GAME))
    assert value == pytest.approx((1.25 + 1.0) / 2)


def test_direct_then_play_cross_check_agrees(eq):
    client = _text(uniform_policy(GAME))
    cfg = RunConfig(n_samples=300, n_boot=50)
    _, col, strat = run_direct(KUHN, KUHN_T, client, cfg, equilibrium=eq, return_internals=True)
    result = run_play(KUHN, KUHN_T, client, cfg, 20000, "uniform", equilibrium=eq, direct=(col, strat))
    rows = result["cross_check"]
    assert len(rows) == 2 and all(r["agree"] for r in rows)
    assert all(r["exact_se"] > 0 for r in rows)
