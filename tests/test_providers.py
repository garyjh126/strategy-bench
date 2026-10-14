"""Offline tests for provider plumbing: response parsing, error classification, budgets, concurrency."""

import httpx
import pytest

from strategybench.adapters.base import Completion
from strategybench.adapters.mock import MockTextClient, policy_lookup
from strategybench.adapters.providers import (
    QuotaExhausted,
    RetryableError,
    _raise_for_http,
    parse_gemini_response,
    parse_openai_response,
    with_backoff,
)
from strategybench.adapters.registry import load_models
from strategybench.analysis.metrics import solve_equilibrium
from strategybench.baselines.scripted import uniform_policy
from strategybench.estimation.direct import BudgetExceeded
from strategybench.games import get_game_spec
from strategybench.prompts import DEFAULT_TEMPLATES
from strategybench.runner import RunConfig, run_direct

SPEC = get_game_spec("kuhn")
TEMPLATE = DEFAULT_TEMPLATES["kuhn"]


def test_parse_gemini_skips_thought_parts_and_counts_thought_tokens():
    c = parse_gemini_response(
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "hmm", "thought": True}, {"text": "BET"}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 226, "candidatesTokenCount": 1, "thoughtsTokenCount": 40},
        }
    )
    assert c.text == "BET" and c.input_tokens == 226 and c.output_tokens == 41


def test_parse_gemini_blocked_response_is_empty_text():
    c = parse_gemini_response({"promptFeedback": {"blockReason": "OTHER"}, "usageMetadata": {}})
    assert c.text == ""


def test_parse_openai_response():
    c = parse_openai_response(
        {
            "choices": [{"message": {"content": "CHECK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 217, "completion_tokens": 1},
        }
    )
    assert (c.text, c.input_tokens, c.output_tokens) == ("CHECK", 217, 1)


def _resp(status, body="", headers=None):
    return httpx.Response(status, text=body, headers=headers or {})


def test_http_error_classification():
    _raise_for_http("x", _resp(200))
    with pytest.raises(QuotaExhausted):
        _raise_for_http("gemini", _resp(429, '{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}'))
    with pytest.raises(RetryableError) as e:
        _raise_for_http("gemini", _resp(429, '{"quotaId": "PerMinute"}', {"retry-after": "7"}))
    assert e.value.retry_after == 7.0
    # Retry-After may also be an HTTP date (RFC 9110); that is still a retryable rate limit.
    with pytest.raises(RetryableError) as e:
        _raise_for_http("deepseek", _resp(429, "slow down", {"retry-after": "Wed, 21 Oct 2015 07:28:00 GMT"}))
    assert e.value.retry_after is None or e.value.retry_after >= 0
    with pytest.raises(RetryableError) as e:
        _raise_for_http("deepseek", _resp(429, "slow down", {"retry-after": "soon"}))
    assert e.value.retry_after is None
    with pytest.raises(QuotaExhausted):
        _raise_for_http("deepseek", _resp(402, "Insufficient Balance"))
    with pytest.raises(RetryableError):
        _raise_for_http("deepseek", _resp(503))
    with pytest.raises(RuntimeError):
        _raise_for_http("deepseek", _resp(400, "bad request"))


def test_backoff_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = iter([RetryableError("x"), RetryableError("y"), Completion(text="BET")])

    def call():
        item = next(calls)
        if isinstance(item, Exception):
            raise item
        return item

    c = with_backoff(call)
    assert c.text == "BET" and c.extra["transport_retries"] == 2


def test_models_yaml_loads():
    models = load_models()
    assert {"claude-haiku-4.5", "gemini-3.5-flash-lite", "deepseek-flash"} <= set(models)
    haiku = models["claude-haiku-4.5"]
    assert haiku.cost(1_000_000, 0) == pytest.approx(1.0)


@pytest.fixture(scope="module")
def eq():
    return solve_equilibrium("kuhn_poker", 2000)


def _client():
    game = SPEC.load()
    return MockTextClient(
        "u", policy_lookup(SPEC, TEMPLATE, uniform_policy(game)), vocabulary=SPEC.vocabulary()
    )


def test_cost_cap_aborts(eq):
    cfg = RunConfig(n_samples=10, n_boot=0, max_cost=0.01)
    with pytest.raises(BudgetExceeded):
        run_direct(SPEC, TEMPLATE, _client(), cfg, equilibrium=eq, cost_fn=lambda i, o: 0.001)


def test_concurrency_gives_identical_results(eq):
    serial = run_direct(SPEC, TEMPLATE, _client(), RunConfig(n_samples=30, n_boot=0), equilibrium=eq)
    parallel = run_direct(
        SPEC, TEMPLATE, _client(), RunConfig(n_samples=30, n_boot=0, concurrency=8), equilibrium=eq
    )
    assert serial["metrics"] == parallel["metrics"]
    assert serial["reliability"]["attempts"] == parallel["reliability"]["attempts"]
