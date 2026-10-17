"""Mock LLM clients with known, scripted behaviour.

They answer through exactly the same text interface as a real model, so the whole
pipeline (rendering, parsing, retries, estimation, metrics) can be checked against
known values without spending money. Behaviour is a deterministic function of
(seed, prompt hash, sample index, attempt), so runs are reproducible.
"""

from __future__ import annotations

import hashlib

import numpy as np
from open_spiel.python import policy as policy_lib

from strategybench.adapters.base import Completion, DistributionReply, Prompt
from strategybench.estimation.infostates import enumerate_infostates
from strategybench.games.base import GameSpec
from strategybench.prompts.base import PromptTemplate

LabelDist = dict[str, float]


def policy_lookup(
    spec: GameSpec, template: PromptTemplate, policy: policy_lib.Policy
) -> dict[str, LabelDist]:
    """Map each prompt hash to the policy's distribution over that prompt's labels."""
    table: dict[str, LabelDist] = {}
    for info in enumerate_infostates(spec.load()):
        prompt = template.render(spec, info.state)
        probs = policy.action_probabilities(info.state)
        labels = spec.action_labels(info.state)
        table[prompt.hash] = {labels[a]: float(probs.get(a, 0.0)) for a in info.legal_actions}
    return table


def _rng(*parts: object) -> np.random.Generator:
    digest = hashlib.sha256("|".join(map(str, parts)).encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "little"))


class MockTextClient:
    """Samples a label from a scripted policy, optionally emitting malformed output."""

    provider = "mock"

    def __init__(
        self,
        name: str,
        lookup: dict[str, LabelDist],
        seed: int = 0,
        garbage_rate: float = 0.0,
        vocabulary: frozenset[str] = frozenset(),
        illegal_rate: float = 0.0,
        format_noise: bool = False,
    ) -> None:
        self.model_id = f"mock-{name}"
        self.lookup = lookup
        self.seed = seed
        self.garbage_rate = garbage_rate
        self.vocabulary = vocabulary
        self.illegal_rate = illegal_rate
        self.format_noise = format_noise
        self.params = {
            "seed": seed,
            "garbage_rate": garbage_rate,
            "illegal_rate": illegal_rate,
            "format_noise": format_noise,
        }
        self.calls = 0

    def complete(self, prompt: Prompt, sample_index: int, attempt: int) -> Completion:
        self.calls += 1
        rng = _rng(self.seed, prompt.hash, sample_index, attempt)
        u = rng.random()
        if u < self.garbage_rate:
            return Completion(text="I think the best move here is probably to wait and see.")
        if u < self.garbage_rate + self.illegal_rate:
            # A real game label that is not legal at this decision point.
            illegal = sorted(self.vocabulary - set(prompt.labels))
            if illegal:
                return Completion(text=illegal[0])

        dist = self.lookup[prompt.hash]
        labels = list(dist)
        label = labels[rng.choice(len(labels), p=np.array([dist[lab] for lab in labels]))]
        if self.format_noise:
            label = rng.choice([label, label.lower(), f" {label}.", f"**{label}**", f'"{label}"'])
        return Completion(text=str(label))


class MockDistributionClient:
    """Returns the scripted policy's distribution directly (a stand-in for typed-choice models)."""

    provider = "mock"

    def __init__(self, name: str, lookup: dict[str, LabelDist]) -> None:
        self.model_id = f"mock-{name}"
        self.lookup = lookup
        self.params: dict[str, object] = {}
        self.calls = 0

    def distribution(self, prompt: Prompt) -> DistributionReply:
        self.calls += 1
        return DistributionReply(probs=dict(self.lookup[prompt.hash]))
