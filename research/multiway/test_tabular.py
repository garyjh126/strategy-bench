"""Sanity checks for the research solver (run: uv run pytest research/multiway)."""

import numpy as np
import pyspiel
import pytest
from open_spiel.python.algorithms import exploitability
from tabular import GameTree, run_cfr, run_fictitious_play


@pytest.fixture(scope="module")
def kuhn3():
    return GameTree(pyspiel.load_game("kuhn_poker(players=3)"))


@pytest.fixture(scope="module")
def kuhn2():
    return GameTree(pyspiel.load_game("kuhn_poker"))


def test_tree_shape(kuhn3):
    # 48 infostates (16 per player), 96 sequences, 4*3*2 deals.
    assert kuhn3.num_infosets == 48
    assert kuhn3.num_seqs == 96
    assert np.bincount(kuhn3.infoset_player_arr).tolist() == [16, 16, 16]


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_gains_match_openspiel_nash_conv(kuhn3, seed):
    rng = np.random.default_rng(seed)
    sigma = kuhn3.random_strategy(rng)
    ours = kuhn3.gains(sigma)
    pol = kuhn3.to_openspiel(sigma)
    ref = exploitability.nash_conv(kuhn3.game, pol, return_only_nash_conv=False)
    np.testing.assert_allclose(ours["gains"], ref.player_improvements, atol=1e-12)
    np.testing.assert_allclose(
        ours["ev"], exploitability._state_values(kuhn3.game.new_initial_state(), 3, pol), atol=1e-12
    )


def test_openspiel_round_trip(kuhn3):
    sigma = kuhn3.random_strategy(np.random.default_rng(5))
    np.testing.assert_allclose(kuhn3.from_openspiel(kuhn3.to_openspiel(sigma)), sigma)


def test_two_player_kuhn_value(kuhn2):
    # Theory: the first player's equilibrium value is -1/18.
    res = run_cfr(kuhn2, 4000, [4000], variant="cfr+", alternating=True)
    last = res["checkpoints"][-1]
    assert last["ev"][0] == pytest.approx(-1 / 18, abs=1e-3)
    assert max(last["gains"]) < 2e-4


def test_alternating_cfr_matches_openspiel(kuhn3):
    # Same algorithm, same order of updates: the average policies should agree.
    from open_spiel.python import policy

    ours = run_cfr(kuhn3, 50, [50], variant="cfr", alternating=True)["average"]
    solver = pyspiel.CFRSolver(kuhn3.game)
    for _ in range(50):
        solver.evaluate_and_update_policy()
    avg = policy.pyspiel_policy_to_python_policy(kuhn3.game, solver.tabular_average_policy())
    np.testing.assert_allclose(ours, kuhn3.from_openspiel(avg), atol=1e-9)


def test_cce_gap_of_single_profile_equals_gains(kuhn3):
    # With one iterate the empirical distribution is that product profile, so the CCE gap
    # is exactly each player's best-response gain.
    init = kuhn3.random_strategy(np.random.default_rng(3))
    res = run_cfr(kuhn3, 1, [1], variant="cfr", init=init)
    cp = res["checkpoints"][0]
    np.testing.assert_allclose(cp["cce_gap"], cp["gains"], atol=1e-12)


def test_cfr_regret_bound_drives_cce_gap_down(kuhn3):
    res = run_cfr(kuhn3, 2000, [100, 2000], variant="cfr")
    early, late = res["checkpoints"]
    assert max(late["cce_gap"]) < max(early["cce_gap"])
    assert max(late["cce_gap"]) < 5e-3


def test_fictitious_play_two_player(kuhn2):
    res = run_fictitious_play(kuhn2, 2000, [2000])
    last = res["checkpoints"][-1]
    assert sum(last["gains"]) < 0.02
    assert last["ev"][0] == pytest.approx(-1 / 18, abs=0.01)


def test_fictitious_play_matches_openspiel_xfp(kuhn3):
    from open_spiel.python.algorithms import fictitious_play

    ours = run_fictitious_play(kuhn3, 10, [10])["average"]
    xfp = fictitious_play.XFPSolver(kuhn3.game)
    for _ in range(10):
        xfp.iteration()
    np.testing.assert_allclose(ours, kuhn3.from_openspiel(xfp.average_policy()), atol=1e-12)
