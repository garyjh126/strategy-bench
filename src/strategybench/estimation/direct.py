"""``direct`` collection mode: query the subject at every reachable information state.

For a text client each infostate is sampled ``n_samples`` times (fresh context each time).
A sample whose reply fails to parse, or names an illegal action, is retried up to
``max_retries`` times with the same prompt; every attempt is counted and logged, and a
sample that never yields a legal action is recorded as failed (never substituted).

Forced infostates (a single legal action) are never queried: the action is played with
certainty and the strategy marks them as forced (see ``estimation/strategy.py``).
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from strategybench.adapters.base import DistributionClient, Prompt, TextClient
from strategybench.adapters.cache import CallCache, cache_key
from strategybench.adapters.parser import ParseStatus, parse_label
from strategybench.estimation.infostates import InfoState, enumerate_infostates
from strategybench.games.base import GameSpec
from strategybench.prompts.base import PromptTemplate


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class CallBudget:
    """Hard caps on live (non-cached) calls and on their estimated cost.

    Cached replies are free and never counted. With concurrent workers the caps can be
    overshot by at most the number of calls already in flight.
    """

    max_calls: int | None = None
    max_cost: float | None = None
    #: (input_tokens, output_tokens) -> USD
    cost_fn: Callable[[int, int], float] | None = None
    used: int = 0
    spent: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def charge(self) -> None:
        with self._lock:
            if self.max_calls is not None and self.used >= self.max_calls:
                raise BudgetExceeded(f"call cap of {self.max_calls} reached; rerun to resume from cache")
            if self.max_cost is not None and self.spent >= self.max_cost:
                raise BudgetExceeded(
                    f"cost cap of ${self.max_cost:.2f} reached (${self.spent:.4f}); "
                    "rerun to resume from cache"
                )
            self.used += 1

    def record(self, input_tokens: int | None, output_tokens: int | None) -> None:
        if self.cost_fn is None:
            return
        with self._lock:
            self.spent += self.cost_fn(input_tokens or 0, output_tokens or 0)


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
    """M4 counters, plus the calls, tokens and cost behind the run.

    Tokens and cost cover every attempt the run used, whether it was made now or read from the
    cache, so a run resumed after a cap or rebuilt from the cache reports the same totals. What
    this invocation spent is ``CallBudget.spent``.
    """

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
    #: Estimated USD of every attempt used (0 without a cost function).
    cost_usd: float = 0.0

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


def dry_run_calls(spec: GameSpec, n_samples: int, max_retries: int) -> tuple[int, int, int, int]:
    """(queried infostates, forced infostates, minimum calls, worst-case calls with every retry)."""
    infos = enumerate_infostates(spec.load())
    queried = sum(not i.forced for i in infos)
    return queried, len(infos) - queried, queried * n_samples, queried * n_samples * (max_retries + 1)


def mean_prompt_tokens(spec: GameSpec, template: PromptTemplate, chars_per_token: float = 4.0) -> float:
    """Rough input-token estimate per call (characters / 4), for dry-run cost estimates only."""
    infos = [i for i in enumerate_infostates(spec.load()) if not i.forced]
    chars = [len(p.system) + len(p.user) for p in (template.render(spec, i.state) for i in infos)]
    return sum(chars) / len(chars) / chars_per_token


class TextQuerier:
    """Queries a text client for one sample: cache lookup, live call, strict parse, retries.

    Thread-safe; shared by ``direct`` collection and ``play`` mode.
    """

    def __init__(
        self,
        client: TextClient,
        vocabulary: frozenset[str],
        max_retries: int = 2,
        cache: CallCache | None = None,
        budget: CallBudget | None = None,
    ) -> None:
        self.client = client
        self.vocabulary = vocabulary
        self.max_retries = max_retries
        self.cache = cache
        self.budget = budget or CallBudget()
        self._cache_lock = threading.Lock()

    def sample(
        self,
        prompt: Prompt,
        labels: dict[int, str],
        infostate: str,
        player: int,
        sample_index: int | str,
    ) -> tuple[list[dict[str, Any]], int | None]:
        """All attempts for one sample. Returns (attempt records, legal action or None)."""
        client = self.client
        records = []
        for attempt in range(self.max_retries + 1):
            key = cache_key(
                client.provider, client.model_id, client.params, prompt.hash, sample_index, attempt
            )
            with self._cache_lock:
                record = self.cache.get(key) if self.cache else None
            from_cache = record is not None
            if record is None:
                self.budget.charge()
                start = time.perf_counter()
                completion = client.complete(prompt, sample_index, attempt)
                self.budget.record(completion.input_tokens, completion.output_tokens)
                record = {
                    "text": completion.text,
                    "input_tokens": completion.input_tokens,
                    "output_tokens": completion.output_tokens,
                    "latency_s": completion.latency_s or time.perf_counter() - start,
                    "timestamp": _now(),
                    "extra": completion.extra,
                }
                if self.cache:
                    with self._cache_lock:
                        self.cache.put(key, record)

            parsed = parse_label(record["text"], list(labels.values()), self.vocabulary)
            action = next((a for a, lab in labels.items() if lab == parsed.label), None)
            records.append(
                {
                    "provider": client.provider,
                    "model_id": client.model_id,
                    "params": client.params,
                    "prompt_version": prompt.version,
                    "prompt_hash": prompt.hash,
                    "infostate": infostate,
                    "player": player,
                    "user_prompt": prompt.user,
                    "sample_index": sample_index,
                    "attempt": attempt,
                    "raw_output": record["text"],
                    "status": parsed.status.value,
                    "parsed_label": parsed.label,
                    "action": action,
                    "input_tokens": record["input_tokens"],
                    "output_tokens": record["output_tokens"],
                    "latency_s": record["latency_s"],
                    "timestamp": record["timestamp"],
                    "extra": record.get("extra", {}),
                    "from_cache": from_cache,
                }
            )
            if parsed.status is ParseStatus.OK:
                return records, action
        return records, None


def tally(
    rel: Reliability,
    records: list[dict[str, Any]],
    action: int | None,
    cost_fn: Callable[[int, int], float] | None = None,
) -> None:
    """Add one sample's attempt records to the counters (``cost_fn``: tokens in, out -> USD)."""
    rel.samples += 1
    for r in records:
        rel.attempts += 1
        if r["from_cache"]:
            rel.cache_hits += 1
        else:
            rel.live_calls += 1
        tokens_in, tokens_out = r["input_tokens"] or 0, r["output_tokens"] or 0
        rel.input_tokens += tokens_in
        rel.output_tokens += tokens_out
        if cost_fn is not None:
            rel.cost_usd += cost_fn(tokens_in, tokens_out)
        if r["status"] == ParseStatus.PARSE_FAILURE.value:
            rel.parse_failures += 1
        elif r["status"] == ParseStatus.ILLEGAL.value:
            rel.illegal += 1
    if len(records) > 1:
        rel.samples_retried += 1
    if action is None:
        rel.samples_failed += 1


def collect_text(
    spec: GameSpec,
    template: PromptTemplate,
    client: TextClient,
    n_samples: int,
    max_retries: int = 2,
    cache: CallCache | None = None,
    log: CallLog | None = None,
    budget: CallBudget | None = None,
    concurrency: int = 1,
) -> Collection:
    log = log or CallLog(None)
    infostates = enumerate_infostates(spec.load())
    out = Collection(infostates=infostates, kind="sampled")
    querier = TextQuerier(client, spec.vocabulary(), max_retries, cache, budget)

    # Everything that touches OpenSpiel states is computed up front, on this thread.
    jobs = []
    for info in infostates:
        if info.forced:
            continue
        prompt = template.render(spec, info.state)
        labels = spec.action_labels(info.state)
        jobs.extend((prompt, labels, info.key, info.player, i) for i in range(n_samples))

    counts: dict[str, dict[int, int]] = {info.key: defaultdict(int) for info in infostates}
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(querier.sample, *job) for job in jobs]
        try:
            for future in as_completed(futures):
                records, action = future.result()
                for r in records:
                    log.write(r)
                tally(out.reliability, records, action, querier.budget.cost_fn)
                if action is not None:
                    counts[records[0]["infostate"]][action] += 1
        except BaseException:
            pool.shutdown(wait=True, cancel_futures=True)
            raise

    out.counts = {key: dict(c) for key, c in counts.items()}
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
        if info.forced:
            continue
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
