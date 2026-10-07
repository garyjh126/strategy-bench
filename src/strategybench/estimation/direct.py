"""``direct`` collection mode: query the subject at every reachable information state.

For a text client each infostate is sampled ``n_samples`` times (fresh context each time).
A sample whose reply fails to parse, or names an illegal action, is retried up to
``max_retries`` times with the same prompt; every attempt is counted and logged, and a
sample that never yields a legal action is recorded as failed (never substituted).
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from strategybench.adapters.base import DistributionClient, TextClient
from strategybench.adapters.cache import CallCache, cache_key
from strategybench.adapters.parser import ParseStatus
from strategybench.estimation.infostates import InfoState, enumerate_infostates
from strategybench.games.base import GameSpec
from strategybench.prompts.base import PromptTemplate


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class CallBudget:
    """Hard cap on live (non-cached) calls. Cached replies are free and never counted."""

    max_calls: int | None = None
    used: int = 0

    def charge(self) -> None:
        if self.max_calls is not None and self.used >= self.max_calls:
            raise BudgetExceeded(f"call cap of {self.max_calls} reached; rerun to resume from cache")
        self.used += 1


class CallLog:
    """Append-only JSONL log with one line per attempt."""

    def __init__(self, path: str | Path | None) -> None:
        self._fh = None
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(path, "a")  # noqa: SIM115 - closed explicitly by close()

    def write(self, record: dict[str, Any]) -> None:
        if self._fh:
            self._fh.write(json.dumps(record) + "\n")
            self._fh.flush()

    def close(self) -> None:
        if self._fh:
            self._fh.close()


@dataclass
class Reliability:
    """M4 counters."""

    samples: int = 0
    attempts: int = 0
    parse_failures: int = 0
    illegal: int = 0
    samples_retried: int = 0
    samples_failed: int = 0
    live_calls: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def rates(self) -> dict[str, float]:
        a, s = max(self.attempts, 1), max(self.samples, 1)
        return {
            "parse_failure_rate": self.parse_failures / a,
            "illegal_action_rate": self.illegal / a,
            "retry_rate": self.samples_retried / s,
            "sample_failure_rate": self.samples_failed / s,
        }


@dataclass
class Collection:
    infostates: list[InfoState]
    #: Text clients: valid sample counts per infostate key and action.
    counts: dict[str, dict[int, int]] = field(default_factory=dict)
    #: Distribution clients: returned probabilities per infostate key and action.
    probabilities: dict[str, dict[int, float]] = field(default_factory=dict)
    reliability: Reliability = field(default_factory=Reliability)
    kind: str = "sampled"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def dry_run_calls(spec: GameSpec, n_samples: int, max_retries: int) -> tuple[int, int, int]:
    """(infostates, minimum calls, worst-case calls including every retry)."""
    n_info = len(enumerate_infostates(spec.load()))
    return n_info, n_info * n_samples, n_info * n_samples * (max_retries + 1)


def collect_text(
    spec: GameSpec,
    template: PromptTemplate,
    client: TextClient,
    n_samples: int,
    max_retries: int = 2,
    cache: CallCache | None = None,
    log: CallLog | None = None,
    budget: CallBudget | None = None,
) -> Collection:
    log = log or CallLog(None)
    budget = budget or CallBudget()
    infostates = enumerate_infostates(spec.load())
    out = Collection(infostates=infostates, kind="sampled")
    rel = out.reliability

    for info in infostates:
        prompt = template.render(spec, info.state)
        counts: dict[int, int] = defaultdict(int)
        for sample_index in range(n_samples):
            rel.samples += 1
            ok = False
            for attempt in range(max_retries + 1):
                key = cache_key(
                    client.provider, client.model_id, client.params, prompt.hash, sample_index, attempt
                )
                record = cache.get(key) if cache else None
                from_cache = record is not None
                if record is None:
                    budget.charge()
                    start = time.perf_counter()
                    completion = client.complete(prompt, sample_index, attempt)
                    record = {
                        "text": completion.text,
                        "input_tokens": completion.input_tokens,
                        "output_tokens": completion.output_tokens,
                        "latency_s": time.perf_counter() - start,
                        "timestamp": _now(),
                        "extra": completion.extra,
                    }
                    if cache:
                        cache.put(key, record)
                    rel.live_calls += 1
                    rel.input_tokens += completion.input_tokens or 0
                    rel.output_tokens += completion.output_tokens or 0
                else:
                    rel.cache_hits += 1

                rel.attempts += 1
                parsed = spec.parse_action(info.state, record["text"])
                if parsed.status is ParseStatus.PARSE_FAILURE:
                    rel.parse_failures += 1
                elif parsed.status is ParseStatus.ILLEGAL:
                    rel.illegal += 1

                log.write(
                    {
                        "provider": client.provider,
                        "model_id": client.model_id,
                        "params": client.params,
                        "prompt_version": prompt.version,
                        "prompt_hash": prompt.hash,
                        "infostate": info.key,
                        "player": info.player,
                        "user_prompt": prompt.user,
                        "sample_index": sample_index,
                        "attempt": attempt,
                        "raw_output": record["text"],
                        "status": parsed.status.value,
                        "parsed_label": parsed.label,
                        "action": parsed.action,
                        "input_tokens": record["input_tokens"],
                        "output_tokens": record["output_tokens"],
                        "latency_s": record["latency_s"],
                        "timestamp": record["timestamp"],
                        "from_cache": from_cache,
                    }
                )

                if parsed.status is ParseStatus.OK:
                    counts[parsed.action] += 1
                    ok = True
                    break
            if attempt > 0:
                rel.samples_retried += 1
            if not ok:
                rel.samples_failed += 1
        out.counts[info.key] = dict(counts)
    return out


def collect_distribution(
    spec: GameSpec,
    template: PromptTemplate,
    client: DistributionClient,
    cache: CallCache | None = None,
    log: CallLog | None = None,
    budget: CallBudget | None = None,
) -> Collection:
    """One call per infostate; the returned probabilities are the strategy (no sampling error)."""
    log = log or CallLog(None)
    budget = budget or CallBudget()
    infostates = enumerate_infostates(spec.load())
    out = Collection(infostates=infostates, kind="distribution")
    rel = out.reliability

    for info in infostates:
        prompt = template.render(spec, info.state)
        key = cache_key(client.provider, client.model_id, client.params, prompt.hash, 0, 0)
        record = cache.get(key) if cache else None
        from_cache = record is not None
        if record is None:
            budget.charge()
            start = time.perf_counter()
            dist = client.distribution(prompt)
            record = {"dist": dist, "latency_s": time.perf_counter() - start, "timestamp": _now()}
            if cache:
                cache.put(key, record)
            rel.live_calls += 1
        else:
            rel.cache_hits += 1
        rel.samples += 1
        rel.attempts += 1

        dist = record["dist"]
        labels = spec.action_labels(info.state)
        valid = (
            set(dist) == set(labels.values())
            and all(p >= 0 for p in dist.values())
            and abs(sum(dist.values()) - 1.0) < 1e-6
        )
        if valid:
            out.probabilities[info.key] = {a: float(dist[lab]) for a, lab in labels.items()}
        else:
            rel.parse_failures += 1
            rel.samples_failed += 1
        log.write(
            {
                "provider": client.provider,
                "model_id": client.model_id,
                "params": client.params,
                "prompt_version": prompt.version,
                "prompt_hash": prompt.hash,
                "infostate": info.key,
                "player": info.player,
                "user_prompt": prompt.user,
                "distribution": dist,
                "status": "ok" if valid else "invalid_distribution",
                "latency_s": record["latency_s"],
                "timestamp": record["timestamp"],
                "from_cache": from_cache,
            }
        )
    return out
