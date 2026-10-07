"""Versioned prompt templates.

The system prompt holds the game rules; the user message holds the situation and the
enumerated legal actions. Both seats use the same template; only the situation text
(which names the seat) differs.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, replace

import pyspiel

from strategybench.adapters.base import Prompt
from strategybench.games.base import GameSpec

_USER_TEMPLATE = """{situation}

Legal actions:
{action_list}

Reply with exactly one of: {label_csv}. Do not write anything else."""


@dataclass(frozen=True)
class PromptTemplate:
    version: str
    system: str
    #: Robustness ablation: list the legal actions in a shuffled (but fixed per infostate) order.
    shuffle_labels: bool = False

    def shuffled(self) -> PromptTemplate:
        return replace(self, version=f"{self.version}+shuffled", shuffle_labels=True)

    def render(self, spec: GameSpec, state: pyspiel.State) -> Prompt:
        situation = spec.render_infostate(state)
        labels = tuple(spec.action_labels(state).values())
        if self.shuffle_labels:
            seed = int.from_bytes(hashlib.sha256(situation.encode()).digest()[:8], "little")
            order = list(labels)
            random.Random(seed).shuffle(order)
            labels = tuple(order)
        user = _USER_TEMPLATE.format(
            situation=situation,
            action_list="\n".join(f"- {lab}" for lab in labels),
            label_csv=", ".join(labels),
        )
        return Prompt(system=self.system, user=user, labels=labels, version=self.version)
