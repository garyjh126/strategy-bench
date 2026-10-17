"""LLM client interfaces.

Two kinds of subject are supported:

* ``TextClient``: returns free text that must be parsed into one action label. Its
  behavioural strategy is estimated by sampling N times per information state.
* ``DistributionClient``: returns a probability per offered label in one call (e.g. a
  typed "choice" model). Its strategy is read directly, with no sampling error.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Prompt:
    system: str
    user: str
    #: Legal action labels, in the order they were shown to the model.
    labels: tuple[str, ...]
    version: str

    @property
    def hash(self) -> str:
        payload = json.dumps([self.version, self.system, self.user, self.labels])
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass
class Completion:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_s: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class TextClient(Protocol):
    provider: str
    model_id: str
    #: Sampling/request parameters actually sent (part of the cache key and the leaderboard row).
    params: dict[str, Any]

    def complete(self, prompt: Prompt, sample_index: int | str, attempt: int) -> Completion: ...


@dataclass
class DistributionReply:
    #: Probability for each label in ``prompt.labels``.
    probs: dict[str, float]
    input_tokens: int | None = None
    output_tokens: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class DistributionClient(Protocol):
    provider: str
    model_id: str
    params: dict[str, Any]

    def distribution(self, prompt: Prompt) -> DistributionReply: ...
