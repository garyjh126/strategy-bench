import pyspiel
import pytest
from open_spiel.python import policy as policy_lib
from open_spiel.python.algorithms import exploitability

from strategybench.baselines.cfr import solve_cfr

KUHN_P1_VALUE = -1.0 / 18.0


@pytest.fixture(scope="module")
def kuhn_result():
    return solve_cfr("kuhn_poker", iterations=2000, eval_every=100)


def test_kuhn_loads():
    game = pyspiel.load_game("kuhn_poker")
    assert game.num_players() == 2
    assert game.num_distinct_actions() == 2


def test_exploitability_decreases(kuhn_result):
    values = [e for _, e in kuhn_result.exploitability_history]
    assert values[-1] < values[0]
    assert kuhn_result.final_exploitability < 1e-3


def test_game_value_matches_theory(kuhn_result):
    p1, p2 = kuhn_result.game_value
    assert p1 == pytest.approx(KUHN_P1_VALUE, abs=2e-3)
    assert p1 + p2 == pytest.approx(0.0, abs=1e-12)  # zero-sum


def test_uniform_policy_is_exploitable():
    # Sanity anchor: uniform random in Kuhn has known exploitability 0.458333... (NashConv 11/12).
    game = pyspiel.load_game("kuhn_poker")
    uniform = policy_lib.UniformRandomPolicy(game)
    assert exploitability.nash_conv(game, uniform) == pytest.approx(11 / 12)


def test_rejects_bad_arguments():
    with pytest.raises(ValueError):
        solve_cfr("kuhn_poker", iterations=0)
