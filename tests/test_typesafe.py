"""Offline tests for the TypeSafe (Jev) client: request shape, parsing, retries, and a full run."""

import json

import httpx
import pytest

from strategybench.adapters.cache import CallCache
from strategybench.adapters.mock import MockDistributionClient, policy_lookup
from strategybench.adapters.providers import TypeSafeClient, parse_typesafe_response
from strategybench.adapters.registry import build_client, load_models
from strategybench.analysis.metrics import solve_equilibrium
from strategybench.baselines.scripted import uniform_policy
from strategybench.estimation.infostates import enumerate_infostates
from strategybench.games import get_game_spec
from strategybench.prompts import DEFAULT_TEMPLATES
from strategybench.runner import RunConfig, run_direct

SPEC = get_game_spec("kuhn")
TEMPLATE = DEFAULT_TEMPLATES["kuhn"]
KEY = "test-key-not-real"


@pytest.fixture(scope="module")
def eq():
    return solve_equilibrium("kuhn_poker", 2000)


def _client(monkeypatch, handler) -> TypeSafeClient:
    monkeypatch.setenv("TYPESAFE_API_KEY", KEY)
    monkeypatch.setattr("time.sleep", lambda s: None)
    client = TypeSafeClient("jev-1.13.0", {})
    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def _answer(probs, model="jev-1.13.0", tokens=300):
    top = max(probs, key=probs.get)
    return {
        "model": model,
        "answers": {"action": {"type": "choice", "choice": top, "probabilities": probs, "confidence": 0.8}},
        "usage": {"input_tokens": tokens, "output_tokens": 30},
    }


def _first_prompt():
    return _prompts()[0]


def test_parse_response_reads_probabilities_usage_and_answering_version():
    reply = parse_typesafe_response(_answer({"BET": 0.88, "PASS": 0.12}, model="jev-1.13.0"))
    assert reply.probs == {"BET": 0.88, "PASS": 0.12}
    assert (reply.input_tokens, reply.output_tokens) == (300, 30)
    assert reply.extra == {"model": "jev-1.13.0", "choice": "BET", "confidence": 0.8}


def test_request_offers_exactly_the_legal_labels_and_sends_the_key(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        labels = seen["body"]["questions"]["action"]["criteria"]
        return httpx.Response(200, json=_answer({lab: 1 / len(labels) for lab in labels}))

    prompt = _first_prompt()
    reply = _client(monkeypatch, handler).distribution(prompt)

    body = seen["body"]
    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
    assert seen["auth"] == f"Bearer {KEY}"
    assert body["model"] == "jev-1.13.0"
    q = body["questions"]["action"]
    assert q["type"] == "choice"
    assert list(q["criteria"]) == list(prompt.labels)
    assert prompt.system in body["state"] and prompt.user in body["state"]
    assert KEY not in json.dumps(body)
    assert set(reply.probs) == set(prompt.labels)


def test_overload_is_retried(monkeypatch):
    statuses = iter([529, 429, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        if status != 200:
            return httpx.Response(status, text="busy")
        return httpx.Response(200, json=_answer({"BET": 0.5, "PASS": 0.5}))

    reply = _client(monkeypatch, handler).distribution(_first_prompt())
    assert reply.extra["transport_retries"] == 2


def test_models_yaml_entry_is_a_pinned_distribution_subject(monkeypatch):
    jev = load_models()["jev-1.13"]
    assert jev.is_distribution and jev.model == "jev-1.13.0"
    assert jev.cost(1_000_000, 1_000_000) == pytest.approx(0.042)  # output tokens are free
    monkeypatch.setenv("TYPESAFE_API_KEY", KEY)
    assert isinstance(build_client(jev), TypeSafeClient)


def test_full_run_matches_the_returned_policy_logs_tokens_and_reruns_free(monkeypatch, tmp_path, eq):
    """A fake Jev that answers with the uniform policy: the run's exploitability must equal the
    uniform policy's, token cost must be recorded, and a rerun must come entirely from the cache."""
    lookup = policy_lookup(SPEC, TEMPLATE, uniform_policy(SPEC.load()))
    hash_by_state = {f"{p.system}\n\n{p.user}": p.hash for p in _prompts()}

    def handler(request: httpx.Request) -> httpx.Response:
        state = json.loads(request.content)["state"]
        return httpx.Response(200, json=_answer(lookup[hash_by_state[state]]))

    jev = load_models()["jev-1.13"]
    cache = CallCache(tmp_path / "cache.sqlite")
    first = run_direct(
        SPEC, TEMPLATE, _client(monkeypatch, handler), RunConfig(), tmp_path / "a", cache, eq, jev.cost
    )
    mock = MockDistributionClient("uniform", lookup)
    reference = run_direct(SPEC, TEMPLATE, mock, RunConfig(), None, None, eq)
    assert first["metrics"]["exploitability"] == pytest.approx(reference["metrics"]["exploitability"])
    rel = first["reliability"]
    assert rel["live_calls"] == 12 and rel["parse_failures"] == 0
    assert rel["input_tokens"] == 12 * 300
    assert first["cost_usd_estimated"] == pytest.approx(12 * 300 * 0.042 / 1e6)

    lines = [json.loads(line) for line in (tmp_path / "a" / "calls.jsonl").read_text().splitlines()]
    assert all(line["extra"]["model"] == "jev-1.13.0" for line in lines)

    def no_calls(request):
        raise AssertionError("rerun must not call the API")

    again = run_direct(SPEC, TEMPLATE, _client(monkeypatch, no_calls), RunConfig(), None, cache, eq, jev.cost)
    assert again["metrics"] == first["metrics"]
    assert again["reliability"]["cache_hits"] == 12 and again["reliability"]["live_calls"] == 0
    assert again["cost_usd_estimated"] == first["cost_usd_estimated"] and again["cost_usd_live"] == 0
    cache.close()


def _prompts():
    return [TEMPLATE.render(SPEC, i.state) for i in enumerate_infostates(SPEC.load()) if not i.forced]
