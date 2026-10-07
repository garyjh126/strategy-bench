"""Metric sanity tests against hand-computed Kuhn poker values.

Derivations (seat 0 = Player 1, equilibrium values -1/18 and +1/18):

Always pass (check/fold):
  A best responder bets every time and the passer folds: BR value 1 in either seat.
  NashConv = 2, exploitability = 1. M2 gains: 1 - 1/18 = 17/18 (subject seat 0),
  1 + 1/18 = 19/18 (subject seat 1).
  M3 seat 0 vs Player 2's (unique) equilibrium strategy: Player 2 bets K always and J 1/3
  after a check, so Player 1 scores -2/9 and loses -1/18 + 2/9 = 1/6 relative to equilibrium.
  M3 seat 1 depends on Player 1's equilibrium bluff rate alpha in [0, 1/3]:
  loss = 1/18 + 2*alpha/3, so it lies in [1/18, 1/18 + 2/9].

Always bet (bet/call):
  BR in either seat: call/bet with K (+2), with Q (0), fold/check-fold J (-1) -> 1/3.
  Exploitability = 1/3. M3 seat 0: against Player 2 calling K always and Q 1/3, Player 1
  scores -1/9, loss = 1/18.

Uniform random: NashConv 11/12, exploitability 11/24.
"""

import pytest

from strategybench.analysis.metrics import compute_metrics, solve_equilibrium
from strategybench.baselines.scripted import first_action_policy, last_action_policy, uniform_policy
from strategybench.games import get_game_spec

TOL = 2e-3  # equilibrium is a CFR approximation


@pytest.fixture(scope="module")
def game():
    return get_game_spec("kuhn").load()


@pytest.fixture(scope="module")
def eq():
    return solve_equilibrium("kuhn_poker", 2000)


def test_equilibrium_value(eq):
    assert eq.values[0] == pytest.approx(-1 / 18, abs=TOL)
    assert eq.exploitability < 1e-3


def test_always_pass(game, eq):
    m = compute_metrics(game, first_action_policy(game), eq)
    assert m.exploitability == pytest.approx(1.0, abs=1e-9)
    assert m.br_gain[0] == pytest.approx(17 / 18, abs=TOL)
    assert m.br_gain[1] == pytest.approx(19 / 18, abs=TOL)
    assert m.h2h_loss[0] == pytest.approx(1 / 6, abs=TOL)
    assert 1 / 18 - TOL <= m.h2h_loss[1] <= 1 / 18 + 2 / 9 + TOL


def test_always_bet(game, eq):
    m = compute_metrics(game, last_action_policy(game), eq)
    assert m.exploitability == pytest.approx(1 / 3, abs=1e-9)
    assert m.h2h_loss[0] == pytest.approx(1 / 18, abs=TOL)


def test_uniform(game, eq):
    m = compute_metrics(game, uniform_policy(game), eq)
    assert m.exploitability == pytest.approx(11 / 24, abs=1e-9)


def test_equilibrium_is_unexploitable(game, eq):
    m = compute_metrics(game, eq.policy, eq)
    assert m.exploitability < 1e-3
    assert max(abs(x) for x in m.h2h_loss) < 1e-3


@pytest.mark.parametrize("make", [uniform_policy, first_action_policy, last_action_policy])
def test_m1_is_mean_of_m2(game, eq, make):
    m = compute_metrics(game, make(game), eq)
    assert m.exploitability == pytest.approx(sum(m.br_gain) / 2, abs=1e-9)
