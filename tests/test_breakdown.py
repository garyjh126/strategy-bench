"""Best-response breakdown: hand-computed Kuhn values and the identity M2 = M3 + sum of contributions."""

import numpy as np
import pytest

from strategybench.analysis.breakdown import br_breakdown
from strategybench.analysis.metrics import compute_metrics, solve_equilibrium
from strategybench.baselines.scripted import first_action_policy, mix_policies, uniform_policy
from strategybench.games import get_game_spec

KUHN = get_game_spec("kuhn").load()
LEDUC_SPEC = get_game_spec("leduc")


@pytest.fixture(scope="module")
def eq():
    return solve_equilibrium("kuhn_poker", 2000)


def _by_key(rows):
    return {r.key: r for r in rows}


def test_always_pass_as_player_1(eq):
    # Subject P1 always checks (and would fold). P2's equilibrium after a check: K bets, Q checks,
    # J bets 1/3. Betting always wins the ante (+1), so per visit: J edge 1 - (1/3 - 2/3) = 4/3,
    # Q edge 1 - 0 = 1, K edge 0. Each card is dealt with probability 1/3.
    seat = br_breakdown(KUHN, first_action_policy(KUHN), eq.policy, eq.values)[0]
    rows = _by_key(seat.responder)
    assert rows["0p"].contribution == pytest.approx(4 / 9, abs=1e-3)
    assert rows["1p"].contribution == pytest.approx(1 / 3, abs=1e-3)
    assert rows["2p"].contribution == pytest.approx(0, abs=1e-3)
    assert rows["0p"].reach == pytest.approx(1 / 3)
    assert rows["0p"].values[1] == pytest.approx(1.0)  # BET: Player 1 folds
    assert rows["0p"].values[0] == pytest.approx(-1.0)  # CHECK: Jack loses the showdown
    assert rows["0p"].edge == pytest.approx(4 / 3, abs=1e-3)
    assert {rows[k].best_response for k in ("0p", "1p")} == {1}
    for key in ("0b", "1b", "2b"):  # Player 1 never bets, so these are never reached
        assert rows[key].reach == 0 and rows[key].contribution == 0
        assert np.isnan(rows[key].edge)
    assert seat.gain == pytest.approx(17 / 18, abs=1e-4)
    assert seat.passive == pytest.approx(1 / 6, abs=1e-3)
    assert seat.active == pytest.approx(7 / 9, abs=1e-3)


def test_always_pass_as_player_2(eq):
    # Best-responding P1 always bets. With equilibrium Jack-bet frequency alpha (K bets 3 alpha),
    # contributions are J: (2 - 2 alpha) / 3, Q: 1/3, K: 0, and M3 = 1/18 + 2 alpha / 3.
    alpha = eq.policy.policy_for_key("0")[1]
    seat = br_breakdown(KUHN, first_action_policy(KUHN), eq.policy, eq.values)[1]
    rows = _by_key(seat.responder)
    assert rows["0"].contribution == pytest.approx((2 - 2 * alpha) / 3, abs=1e-3)
    assert rows["1"].contribution == pytest.approx(1 / 3, abs=1e-3)
    assert rows["2"].contribution == pytest.approx(0, abs=1e-3)
    assert seat.passive == pytest.approx(1 / 18 + 2 * alpha / 3, abs=1e-3)
    assert seat.gain == pytest.approx(19 / 18, abs=1e-4)


def test_subject_rows(eq):
    alpha = eq.policy.policy_for_key("0")[1]
    seat = br_breakdown(KUHN, first_action_policy(KUHN), eq.policy, eq.values)[0]
    rows = _by_key(seat.subject)
    assert set(rows) == {"0", "1", "2", "0pb", "1pb", "2pb"}
    assert rows["0"].reach == pytest.approx(1 / 3)
    assert rows["0"].distance == pytest.approx(alpha)
    # Holding the Jack, P1 faces a bet after checking only when P2 has the King (P2 checks a Queen).
    assert rows["0pb"].reach == pytest.approx(1 / 3 * 1 / 2, abs=1e-3)


@pytest.mark.parametrize("game_name", ["kuhn", "leduc"])
@pytest.mark.parametrize("weight", [0.0, 0.5, 0.9])
def test_identity_m2_equals_m3_plus_contributions(game_name, weight):
    spec = get_game_spec(game_name)
    game = spec.load()
    eq_g = solve_equilibrium(spec.load_string, 2000, "runs/equilibria")
    subject = mix_policies(game, eq_g.policy, first_action_policy(game), weight)
    subject = mix_policies(game, subject, uniform_policy(game), 0.9)
    metrics = compute_metrics(game, subject, eq_g)
    for seat in br_breakdown(game, subject, eq_g.policy, eq_g.values):
        i = seat.subject_seat
        total = sum(r.contribution for r in seat.responder)
        assert total == pytest.approx(seat.active, abs=1e-9)
        assert seat.passive == pytest.approx(metrics.h2h_loss[i], abs=1e-9)
        assert seat.gain == pytest.approx(metrics.br_gain[i], abs=1e-9)
        assert min(r.contribution for r in seat.responder) >= -1e-12
        assert sum(r.reach for r in seat.subject) > 0


def test_equilibrium_subject_gives_nothing_away(eq):
    for seat in br_breakdown(KUHN, eq.policy, eq.policy, eq.values):
        assert max(r.contribution for r in seat.responder) < 1e-3
        assert abs(seat.passive) < 1e-4
        assert max(r.distance for r in seat.subject) == pytest.approx(0, abs=1e-12)
