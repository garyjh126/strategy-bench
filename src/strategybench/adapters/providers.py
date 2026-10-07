"""Real provider clients (text subjects).

Each client sends the system prompt and user message, returns the reply text and token
usage, and handles transport problems itself:

* rate limits, overload and server errors are retried with exponential backoff
  (these transport retries are logged in ``Completion.extra`` and are separate from the
  parse retries counted in M4);
* a daily quota or an empty balance raises ``QuotaExhausted`` so the run stops cleanly and
  can resume from the cache later.

API keys are read from the environment only and never logged.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from collections.abc import Callable
from typing import Any

import anthropic
import httpx

from strategybench.adapters.base import Completion, Prompt


class QuotaExhausted(RuntimeError):
    """The provider refuses further calls for now (daily quota, empty balance)."""


class RetryableError(RuntimeError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip().strip("\"'")
    if not value:
        raise RuntimeError(f"{name} is not set (add it to .env)")
    return value


class RateLimiter:
    """Spaces call starts at least ``60 / rpm`` seconds apart across threads."""

    def __init__(self, rpm: float | None) -> None:
        self.interval = 60.0 / rpm if rpm else 0.0
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        if not self.interval:
            return
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next)
            self._next = start + self.interval
        time.sleep(max(0.0, start - now))


def with_backoff(
    call: Callable[[], Completion], max_tries: int = 6, base: float = 2.0, cap: float = 60.0
) -> Completion:
    for attempt in range(max_tries):
        try:
            completion = call()
            completion.extra["transport_retries"] = attempt
            return completion
        except RetryableError as e:
            if attempt == max_tries - 1:
                raise
            delay = e.retry_after or min(cap, base * 2**attempt) * (0.5 + random.random())
            time.sleep(delay)
    raise AssertionError("unreachable")


class _BaseClient:
    provider = ""

    def __init__(self, model: str, params: dict[str, Any], rpm: float | None = None) -> None:
        self.model_id = model
        self.params = dict(params)
        self._limiter = RateLimiter(rpm)

    def complete(self, prompt: Prompt, sample_index: int, attempt: int) -> Completion:
        def once() -> Completion:
            self._limiter.wait()
            start = time.perf_counter()
            completion = self._call(prompt)
            completion.latency_s = time.perf_counter() - start
            return completion

        return with_backoff(once)

    def _call(self, prompt: Prompt) -> Completion:
        raise NotImplementedError


class AnthropicClient(_BaseClient):
    """Claude via the official SDK. Sampling parameters (where a model still accepts them)
    go through ``extra_body`` because SDK 1.x removed them from the method signature."""

    provider = "anthropic"
    _SDK_ARGS = {"max_tokens"}

    def __init__(self, model: str, params: dict[str, Any], rpm: float | None = None) -> None:
        super().__init__(model, params, rpm)
        self._client = anthropic.Anthropic(api_key=_require_env("ANTHROPIC_API_KEY"), max_retries=0)

    def _call(self, prompt: Prompt) -> Completion:
        sdk = {k: v for k, v in self.params.items() if k in self._SDK_ARGS}
        extra = {k: v for k, v in self.params.items() if k not in self._SDK_ARGS}
        try:
            r = self._client.messages.create(
                model=self.model_id,
                system=prompt.system,
                messages=[{"role": "user", "content": prompt.user}],
                extra_body=extra or None,
                **sdk,
            )
        except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as e:
            raise RetryableError(str(e)) from e
        except anthropic.APIStatusError as e:
            if e.status_code in (529,):
                raise RetryableError(str(e)) from e
            if e.status_code == 402 or "credit balance" in str(e).lower():
                raise QuotaExhausted(f"anthropic: {e.message}") from e
            raise
        text = "".join(b.text for b in r.content if b.type == "text")
        return Completion(
            text=text,
            input_tokens=r.usage.input_tokens,
            output_tokens=r.usage.output_tokens,
            extra={"stop_reason": r.stop_reason},
        )


def _raise_for_http(provider: str, r: httpx.Response) -> None:
    if r.status_code == 200:
        return
    body = r.text[:2000]
    if r.status_code == 429:
        if "PerDay" in body or "per day" in body.lower():
            raise QuotaExhausted(f"{provider}: daily quota reached; rerun later to resume from cache")
        retry_after = r.headers.get("retry-after")
        raise RetryableError(f"{provider}: rate limited", float(retry_after) if retry_after else None)
    if r.status_code == 402:
        raise QuotaExhausted(f"{provider}: insufficient balance")
    if r.status_code >= 500:
        raise RetryableError(f"{provider}: HTTP {r.status_code}")
    raise RuntimeError(f"{provider}: HTTP {r.status_code}: {body[:300]}")


class GeminiClient(_BaseClient):
    """Gemini via the generateContent REST endpoint. ``params`` is the generationConfig."""

    provider = "gemini"
    _URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, model: str, params: dict[str, Any], rpm: float | None = None) -> None:
        super().__init__(model, params, rpm)
        self._key = _require_env("GEMINI_API_KEY")
        self._http = httpx.Client(timeout=120)

    def _call(self, prompt: Prompt) -> Completion:
        try:
            r = self._http.post(
                self._URL.format(model=self.model_id),
                headers={"x-goog-api-key": self._key},
                json={
                    "systemInstruction": {"parts": [{"text": prompt.system}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt.user}]}],
                    "generationConfig": self.params,
                },
            )
        except httpx.TransportError as e:
            raise RetryableError(f"gemini: {type(e).__name__}") from e
        _raise_for_http("gemini", r)
        return parse_gemini_response(r.json())


def parse_gemini_response(d: dict[str, Any]) -> Completion:
    usage = d.get("usageMetadata", {})
    candidates = d.get("candidates") or []
    parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return Completion(
        text=text,
        input_tokens=usage.get("promptTokenCount"),
        output_tokens=(usage.get("candidatesTokenCount") or 0) + (usage.get("thoughtsTokenCount") or 0),
        extra={
            "finish_reason": candidates[0].get("finishReason") if candidates else None,
            "thoughts_tokens": usage.get("thoughtsTokenCount"),
            "prompt_feedback": d.get("promptFeedback"),
        },
    )


class OpenAICompatibleClient(_BaseClient):
    """Any /chat/completions endpoint (DeepSeek, local servers). ``params`` go in the body."""

    def __init__(
        self,
        model: str,
        params: dict[str, Any],
        base_url: str,
        key_env: str | None,
        provider: str,
        rpm: float | None = None,
    ) -> None:
        super().__init__(model, params, rpm)
        self.provider = provider
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {_require_env(key_env)}"} if key_env else {}
        self._http = httpx.Client(timeout=300)

    def _call(self, prompt: Prompt) -> Completion:
        body = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            **self.params,
        }
        try:
            r = self._http.post(self._url, headers=self._headers, json=body)
        except httpx.TransportError as e:
            raise RetryableError(f"{self.provider}: {type(e).__name__}") from e
        _raise_for_http(self.provider, r)
        return parse_openai_response(r.json())


def parse_openai_response(d: dict[str, Any]) -> Completion:
    choice = (d.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    usage = d.get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    return Completion(
        text=message.get("content") or "",
        input_tokens=usage.get("prompt_tokens"),
        output_tokens=usage.get("completion_tokens"),
        extra={
            "finish_reason": choice.get("finish_reason"),
            "reasoning_tokens": details.get("reasoning_tokens"),
            "usage": json.loads(json.dumps(usage)),
        },
    )
