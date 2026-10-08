"""Leduc poker: game spec, prompts and pipeline checks against OpenSpiel's direct computation."""

import collections

import pytest
from open_spiel.python.algorithms import exploitability

from strategybench.adapters.mock import MockDistributionClient, MockTextClient, policy_lookup
from strategybench.analysis.metrics import compute_metrics, solve_equilibrium
from strategybench.baselines.scripted import first_action_policy, last_action_policy, uniform_policy
from strategybench.estimation.infostates import enumerate_infostates
from strategybench.games import get_game_spec
from strategybench.prompts import DEFAULT_TEMPLATES
from strategybench.runner import RunConfig, run_direct

SPEC = get_game_spec("leduc")
TEMPLATE = DEFAULT_TEMPLATES["leduc"]
GAME = SPEC.load()
JACK, QUEEN, KING = 0, 1, 2
FOLD, CALL, RAISE = 0, 1, 2


@pytest.fixture(scope="module")
def eq():
    return solve_equilibrium(SPEC.load_string, 2000)


def _state(*history):
    s = GAME.new_initial_state()
    for a in history:
        s.apply_action(a)
    return s


def test_infostates_and_label_sets():
    infos = enumerate_infostates(GAME)
    assert len(infos) == 288
    prompts = [TEMPLATE.render(SPEC, i.state) for i in infos]
    assert len({p.hash for p in prompts}) == 288
    assert collections.Counter(p.labels for p in prompts) == {
        ("CHECK", "BET"): 96,
        ("FOLD", "CALL", "RAISE"): 96,
        ("FOLD", "CALL"): 96,
    }


def test_showdown_ranks():
    # Pair with the public card beats a higher card; otherwise higher rank wins.
    assert _state(JACK, KING, CALL, CALL, JACK, CALL, CALL).returns() == [1.0, -1.0]
    assert _state(JACK, KING, CALL, CALL, QUEEN, CALL, CALL).returns() == [-1.0, 1.0]


def test_render_round_two_facing_a_bet():
    s = _state(JACK, KING, RAISE, CALL, QUEEN, RAISE)
    assert SPEC.render_infostate(s) == (
        "You are Player 2 (you act second in each betting round).\n"
        "Your private card: King.\n"
        "Public card: Queen.\n"
        "Current round: 2 of 2.\n"
        "Round 1 betting: Player 1 bet 2, Player 2 called.\n"
        "Round 2 betting: Player 1 bet 4.\n"
        "Pot: 10 chips (you have put in 3, your opponent 7). To call: 4 chips."
    )
    assert SPEC.action_labels(s) == {FOLD: "FOLD", CALL: "CALL", RAISE: "RAISE"}


def test_render_hides_opponent_card_and_caps_raises():
    s = _state(QUEEN, KING, RAISE, RAISE)
    text = SPEC.render_infostate(s)
    assert "Queen" in text and "King" not in text and "Public card: not dealt yet." in text
    assert "Player 1 bet 2, Player 2 raised by 2" in text
    assert SPEC.action_labels(s) == {FOLD: "FOLD", CALL: "CALL"}


def test_equilibrium_value(eq):
    assert eq.values[0] == pytest.approx(-0.0856, abs=1e-3)
    assert eq.exploitability < 1e-3


@pytest.mark.parametrize("make", [first_action_policy, last_action_policy])
def test_deterministic_agents_match_direct_computation(eq, make):
    policy = make(GAME)
    client = MockTextClient("t", policy_lookup(SPEC, TEMPLATE, policy), vocabulary=SPEC.vocabulary())
    result = run_direct(SPEC, TEMPLATE, client, RunConfig(n_samples=2, n_boot=0), equilibrium=eq)
    direct = compute_metrics(GAME, policy, eq)
    assert result["metrics"]["exploitability"] == pytest.approx(direct.exploitability, abs=1e-12)
    assert result["metrics"]["h2h_loss"] == pytest.approx(direct.h2h_loss, abs=1e-12)
    assert result["coverage"]["k=5"] == 0.0  # only 2 samples each
    assert result["filled"]["count"] == 0


def test_uniform_via_distribution_client_matches_openspiel(eq):
    client = MockDistributionClient("u", policy_lookup(SPEC, TEMPLATE, uniform_policy(GAME)))
    result = run_direct(SPEC, TEMPLATE, client, RunConfig(), equilibrium=eq)
    expected = exploitability.exploitability(GAME, uniform_policy(GAME))
    assert result["metrics"]["exploitability"] == pytest.approx(expected, abs=1e-9)
    assert client.calls == 288


def test_equilibrium_via_distribution_client_is_unexploitable(eq):
    client = MockDistributionClient("cfr", policy_lookup(SPEC, TEMPLATE, eq.policy))
    result = run_direct(SPEC, TEMPLATE, client, RunConfig(), equilibrium=eq)
    assert result["metrics"]["exploitability"] < 1e-3


def test_replay_text():
    s = _state()
    assert SPEC.describe_chance(s, QUEEN) == "Player 1 is dealt a Queen"
    s = _state(QUEEN, KING, CALL, CALL)
    assert SPEC.describe_chance(s, KING) == "The public card is a King"
    s = _state(QUEEN, KING, CALL, RAISE)
    assert SPEC.short_label(s) == "Queen · R1: Player 1 checked, Player 2 bet 2"
    s = _state(QUEEN, KING, CALL, CALL, KING, RAISE)
    assert (
        SPEC.short_label(s)
        == "King, public King · R1: Player 1 checked, Player 2 checked · R2: Player 1 bet 4"
    )
