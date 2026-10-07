"""Versioned prompt templates.

The system prompt holds the game rules; the user message holds the situation and the
enumerated legal actions. Both seats use the same template; only the situation text
(which names the seat) differs.
"""

from __future__ import annotations

from dataclasses import dataclass

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

    def render(self, spec: GameSpec, state: pyspiel.State) -> Prompt:
        labels = tuple(spec.action_labels(state).values())
        user = _USER_TEMPLATE.format(
            situation=spec.render_infostate(state),
            action_list="\n".join(f"- {lab}" for lab in labels),
            label_csv=", ".join(labels),
        )
        return Prompt(system=self.system, user=user, labels=labels, version=self.version)
