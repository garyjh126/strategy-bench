"""Forced decisions (a single legal action) are not queried in direct mode.

Liar's Dice is the test game: after the highest bid, 2x3, only LIAR is legal, so 96 of its 192
infostates are forced. Kuhn and Leduc have none.
"""

import json

import pytest

from strategybench.adapters.mock import MockDistributionClient, MockTextClient, policy_lookup
from strategybench.analysis.metrics import compute_metrics, solve_equilibrium
from strategybench.baselines.scripted import first_action_policy, uniform_policy
from strategybench.estimation.direct import dry_run_calls
from strategybench.estimation.infostates import enumerate_infostates
from strategybench.estimation.strategy import coverage, strategy_from_counts
from strategybench.games import get_game_spec
from strategybench.prompts import DEFAULT_TEMPLATES
from strategybench.runner import RunConfig, run_direct

SPEC = get_game_spec("liars_dice")
TEMPLATE = DEFAULT_TEMPLATES["liars_dice"]
GAME = SPEC.load()
INFOS = enumerate_infostates(GAME)
FORCED = {i.key for i in INFOS if len(i.legal_actions) == 1}


@pytest.fixture(scope="module")
def eq():
    return solve_equilibrium(SPEC.load_string, 2000)


def _text_client(policy):
    return MockTextClient("t", policy_lookup(SPEC, TEMPLATE, policy), vocabulary=SPEC.vocabulary())


def test_the_game_has_96_forced_infostates():
    assert len(FORCED) == 96 and len(INFOS) == 192


def test_text_client_is_never_asked_at_a_forced_decision(tmp_path, eq):
    client = _text_client(uniform_policy(GAME))
    result = run_direct(SPEC, TEMPLATE, client, RunConfig(n_samples=3, n_boot=0), tmp_path, equilibrium=eq)
    assert client.calls == (192 - 96) * 3
    assert result["reliability"]["samples"] == (192 - 96) * 3
    assert result["forced"]["count"] == 96
    assert result["filled"]["count"] == 0
    logged = {json.loads(line)["infostate"] for line in (tmp_path / "calls.jsonl").read_text().splitlines()}
    assert logged.isdisjoint(FORCED)

    rows = {r["infostate"]: r for r in json.loads((tmp_path / "strategy.json").read_text())}
    assert {k for k, r in rows.items() if r["forced"]} == FORCED
    for key in FORCED:
        assert rows[key]["estimated"] == {"LIAR": 1.0}
        assert rows[key]["support"] == 0 and not rows[key]["filled"]


def test_distribution_client_is_never_asked_at_a_forced_decision(eq):
    client = MockDistributionClient("d", policy_lookup(SPEC, TEMPLATE, uniform_policy(GAME)))
    result = run_direct(SPEC, TEMPLATE, client, RunConfig(n_boot=0), equilibrium=eq)
    assert client.calls == 192 - 96
    assert result["forced"]["count"] == 96 and result["filled"]["count"] == 0


def test_skipping_forced_decisions_leaves_the_metrics_unchanged(eq):
    # A deterministic subject: every metric equals the direct computation on its own policy.
    policy = first_action_policy(GAME)
    config = RunConfig(n_samples=2, n_boot=0)
    result = run_direct(SPEC, TEMPLATE, _text_client(policy), config, equilibrium=eq)
    direct = compute_metrics(GAME, policy, eq)
    assert result["metrics"]["exploitability"] == pytest.approx(direct.exploitability, abs=1e-12)
    assert result["metrics"]["br_gain"] == pytest.approx(direct.br_gain, abs=1e-12)
    assert result["metrics"]["h2h_loss"] == pytest.approx(direct.h2h_loss, abs=1e-12)


def test_forced_decisions_are_played_with_certainty_and_count_as_covered():
    # No samples anywhere: every unforced infostate is filled, every forced one is certain.
    strat = strategy_from_counts(GAME, INFOS, {}, min_samples=1)
    assert sorted(strat.forced) == sorted(FORCED)
    assert set(strat.filled) == {i.key for i in INFOS} - FORCED
    for key in FORCED:
        assert strat.policy.policy_for_key(key).max() == 1.0
    full = {i.key: {i.legal_actions[0]: 5} for i in INFOS if i.key not in FORCED}
    assert coverage(GAME, strategy_from_counts(GAME, INFOS, full), k=5) == pytest.approx(1.0)


@pytest.mark.parametrize(
    "game, queried, forced", [("kuhn", 12, 0), ("leduc", 288, 0), ("liars_dice", 96, 96)]
)
def test_dry_run_counts_only_the_decisions_that_are_queried(game, queried, forced):
    n_queried, n_forced, lo, hi = dry_run_calls(get_game_spec(game), 200, 2)
    assert (n_queried, n_forced) == (queried, forced)
    assert (lo, hi) == (queried * 200, queried * 200 * 3)
