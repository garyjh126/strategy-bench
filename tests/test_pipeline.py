"""End-to-end tests: scripted policies answer through the text interface like an LLM would."""

import json

import numpy as np
import pytest

from strategybench.adapters.cache import CallCache
from strategybench.adapters.mock import MockDistributionClient, MockTextClient, policy_lookup
from strategybench.analysis.metrics import compute_metrics, solve_equilibrium
from strategybench.baselines.scripted import first_action_policy, last_action_policy, uniform_policy
from strategybench.estimation.direct import BudgetExceeded
from strategybench.games import get_game_spec
from strategybench.prompts import DEFAULT_TEMPLATES
from strategybench.runner import RunConfig, run_direct

SPEC = get_game_spec("kuhn")
TEMPLATE = DEFAULT_TEMPLATES["kuhn"]
GAME = SPEC.load()


@pytest.fixture(scope="module")
def eq():
    return solve_equilibrium("kuhn_poker", 2000)


def _text_client(policy, **kw):
    return MockTextClient("t", policy_lookup(SPEC, TEMPLATE, policy), vocabulary=SPEC.vocabulary(), **kw)


@pytest.mark.parametrize("make", [first_action_policy, last_action_policy])
def test_deterministic_agents_match_direct_computation(eq, make):
    policy = make(GAME)
    result = run_direct(
        SPEC, TEMPLATE, _text_client(policy), RunConfig(n_samples=5, n_boot=0), equilibrium=eq
    )
    direct = compute_metrics(GAME, policy, eq)
    assert result["metrics"]["exploitability"] == pytest.approx(direct.exploitability, abs=1e-12)
    assert result["metrics"]["h2h_loss"] == pytest.approx(direct.h2h_loss, abs=1e-12)


def test_uniform_agent_converges_to_openspiel_value(eq):
    result = run_direct(
        SPEC,
        TEMPLATE,
        _text_client(uniform_policy(GAME)),
        RunConfig(n_samples=4000, n_boot=0),
        equilibrium=eq,
    )
    assert result["metrics"]["exploitability"] == pytest.approx(11 / 24, abs=0.02)


def test_cfr_agent_via_distribution_client_is_unexploitable(eq):
    client = MockDistributionClient("cfr", policy_lookup(SPEC, TEMPLATE, eq.policy))
    result = run_direct(SPEC, TEMPLATE, client, RunConfig(), equilibrium=eq)
    assert result["metrics"]["exploitability"] < 1e-3
    assert client.calls == 12


def test_cfr_agent_via_text_sampling_approaches_zero(eq):
    result = run_direct(
        SPEC, TEMPLATE, _text_client(eq.policy), RunConfig(n_samples=5000, n_boot=0), equilibrium=eq
    )
    assert result["metrics"]["exploitability"] < 0.01


def test_reliability_counts_noise_and_retries(eq):
    client = _text_client(eq.policy, garbage_rate=0.2, illegal_rate=0.1, format_noise=True)
    result = run_direct(SPEC, TEMPLATE, client, RunConfig(n_samples=300, n_boot=0), equilibrium=eq)
    rel = result["reliability"]
    assert rel["parse_failure_rate"] == pytest.approx(0.2, abs=0.03)
    assert rel["illegal_action_rate"] == pytest.approx(0.1, abs=0.03)
    assert rel["attempts"] == rel["live_calls"]
    # P(all three attempts fail) = 0.3^3
    assert rel["sample_failure_rate"] == pytest.approx(0.027, abs=0.015)
    assert result["coverage"]["k=5"] == 1.0


def test_failed_infostates_are_filled_and_reported(eq):
    client = _text_client(eq.policy, garbage_rate=1.0)
    result = run_direct(
        SPEC, TEMPLATE, client, RunConfig(n_samples=3, max_retries=0, n_boot=0), equilibrium=eq
    )
    assert result["filled"]["count"] == 12
    assert result["metrics"]["exploitability"] == pytest.approx(11 / 24, abs=1e-9)  # uniform fill
    assert result["coverage"]["k=5"] == 0.0


def test_rerun_from_cache_is_identical_and_free(tmp_path, eq):
    cache = CallCache(tmp_path / "cache.sqlite")
    cfg = RunConfig(n_samples=20, n_boot=50, seed=1)
    first_client = _text_client(uniform_policy(GAME), garbage_rate=0.1)
    first = run_direct(SPEC, TEMPLATE, first_client, cfg, tmp_path / "a", cache, eq)
    second_client = _text_client(uniform_policy(GAME), garbage_rate=0.1)
    second = run_direct(SPEC, TEMPLATE, second_client, cfg, tmp_path / "b", cache, eq)
    assert second_client.calls == 0
    assert second["reliability"]["live_calls"] == 0
    for key in ("metrics", "ci95", "bias", "coverage", "filled"):
        assert first[key] == second[key]


def test_call_cap_aborts_then_resumes_from_cache(tmp_path, eq):
    cache = CallCache(tmp_path / "cache.sqlite")
    cfg = RunConfig(n_samples=10, n_boot=0, max_calls=50)
    with pytest.raises(BudgetExceeded):
        run_direct(SPEC, TEMPLATE, _text_client(uniform_policy(GAME)), cfg, None, cache, eq)
    cfg.max_calls = 100
    resumed = _text_client(uniform_policy(GAME))
    result = run_direct(SPEC, TEMPLATE, resumed, cfg, None, cache, eq)
    assert resumed.calls == 120 - 50
    assert result["reliability"]["cache_hits"] == 50


def test_results_directory_is_written(tmp_path, eq):
    run_direct(
        SPEC,
        TEMPLATE,
        _text_client(uniform_policy(GAME)),
        RunConfig(n_samples=3, n_boot=0),
        tmp_path,
        None,
        eq,
    )
    lines = (tmp_path / "calls.jsonl").read_text().splitlines()
    assert len(lines) == 36
    first = json.loads(lines[0])
    for field in ("model_id", "params", "prompt_hash", "user_prompt", "raw_output", "status", "sample_index"):
        assert field in first
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["prompt_version"] == "kuhn-v1" and "Kuhn poker" in manifest["system_prompt"]
    rows = json.loads((tmp_path / "strategy.json").read_text())
    assert len(rows) == 12 and np.isclose(sum(rows[0]["estimated"].values()), 1.0)
