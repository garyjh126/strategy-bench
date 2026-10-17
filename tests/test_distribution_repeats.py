"""Distribution subjects whose replies vary between calls (as Jev's do): direct mode averages
``n_calls`` replies per infostate and bootstraps over them; play mode plays the same average."""

import json

import numpy as np
import pytest

from strategybench.adapters.base import DistributionReply, Prompt
from strategybench.adapters.cache import CallCache
from strategybench.adapters.mock import policy_lookup
from strategybench.analysis.metrics import compute_metrics, solve_equilibrium
from strategybench.baselines.scripted import uniform_policy
from strategybench.games import get_game_spec
from strategybench.prompts import DEFAULT_TEMPLATES
from strategybench.report.runs import RunRecord
from strategybench.runner import RunConfig, run_direct, run_play

SPEC = get_game_spec("kuhn")
TEMPLATE = DEFAULT_TEMPLATES["kuhn"]
GAME = SPEC.load()


@pytest.fixture(scope="module")
def eq():
    return solve_equilibrium("kuhn_poker", 2000)


class NoisyDistributionClient:
    """Replies are Dirichlet draws centred on a scripted policy (``concentration`` sets the noise)."""

    provider = "mock"

    def __init__(self, lookup: dict[str, dict[str, float]], concentration: float, seed: int = 0) -> None:
        self.model_id = "mock-noisy"
        self.params = {"concentration": concentration, "seed": seed}
        self.lookup = lookup
        self.concentration = concentration
        self.rng = np.random.default_rng(seed)
        self.calls = 0

    def distribution(self, prompt: Prompt) -> DistributionReply:
        self.calls += 1
        truth = self.lookup[prompt.hash]
        labels = list(truth)
        draw = self.rng.dirichlet([self.concentration * truth[lab] + 1e-3 for lab in labels])
        return DistributionReply(probs=dict(zip(labels, map(float, draw), strict=True)), input_tokens=200)


def _uniform_lookup():
    return policy_lookup(SPEC, TEMPLATE, uniform_policy(GAME))


def test_replies_are_averaged_and_bootstrapped(tmp_path, eq):
    client = NoisyDistributionClient(_uniform_lookup(), concentration=20)
    result = run_direct(SPEC, TEMPLATE, client, RunConfig(n_calls=20, n_boot=100), tmp_path, None, eq)

    assert client.calls == 12 * 20 and result["n_samples"] == 20
    assert result["reliability"]["live_calls"] == 240 and result["reliability"]["parse_failures"] == 0

    # The strategy at each infostate is the mean of its logged replies.
    lines = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    rows = {r["infostate"]: r for r in json.loads((tmp_path / "strategy.json").read_text())}
    for key in {line["infostate"] for line in lines}:
        replies = [line["distribution"] for line in lines if line["infostate"] == key]
        assert len(replies) == 20 and rows[key]["support"] == 20
        for label, p in rows[key]["estimated"].items():
            assert p == pytest.approx(np.mean([r[label] for r in replies]))

    # A real interval around an estimate near the true (uniform) value.
    true = compute_metrics(GAME, uniform_policy(GAME), eq).exploitability
    lo, hi = result["ci95"]["exploitability"]
    assert 0 < hi - lo < 0.2
    assert abs(result["bias_corrected"]["exploitability"] - true) < 0.05


def test_more_calls_resume_from_the_cache(tmp_path, eq):
    cache = CallCache(tmp_path / "cache.sqlite")
    lookup = _uniform_lookup()
    run_direct(
        SPEC, TEMPLATE, NoisyDistributionClient(lookup, 20), RunConfig(n_calls=5, n_boot=0), None, cache, eq
    )
    more = NoisyDistributionClient(lookup, 20)
    result = run_direct(SPEC, TEMPLATE, more, RunConfig(n_calls=8, n_boot=0), None, cache, eq)
    assert result["reliability"]["cache_hits"] == 12 * 5
    assert more.calls == result["reliability"]["live_calls"] == 12 * 3
    cache.close()


def test_play_mode_plays_the_direct_average_without_new_calls(tmp_path, eq):
    cache = CallCache(tmp_path / "cache.sqlite")
    client = NoisyDistributionClient(_uniform_lookup(), concentration=20)
    cfg = RunConfig(n_calls=10, n_boot=50)
    _, col, strat = run_direct(SPEC, TEMPLATE, client, cfg, None, cache, eq, return_internals=True)
    calls_after_direct = client.calls
    play = run_play(SPEC, TEMPLATE, client, cfg, 4000, "equilibrium", None, cache, eq, None, (col, strat))
    assert client.calls == calls_after_direct
    assert all(row["agree"] for row in play["cross_check"])
    cache.close()


@pytest.mark.parametrize(
    ("kind", "n_samples", "exact"),
    [
        ("distribution", None, True),
        ("distribution", 1, True),
        ("distribution", 20, False),
        ("sampled", 200, False),
    ],
)
def test_only_single_call_distribution_runs_count_as_exact(kind, n_samples, exact):
    record = RunRecord(
        run_id="r", path=None, manifest={}, metrics={"subject_kind": kind, "n_samples": n_samples}
    )
    assert record.is_exact is exact
