"""Abstract game specification.

A ``GameSpec`` is the only game-specific code the pipeline needs: how to load the
OpenSpiel game, how to describe an information state in plain language, and how
to label the legal actions. Estimation and analysis code never look inside it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from types import MappingProxyType

import pyspiel

from strategybench.adapters.parser import ParseResult, parse_label


class GameSpec(ABC):
    #: Registry key, e.g. "kuhn".
    name: str
    #: OpenSpiel load string, e.g. "kuhn_poker".
    load_string: str
    #: Name of the normalisation unit, e.g. "ante" or "big blind".
    payoff_unit: str
    #: Native payoff units per normalisation unit.
    unit_size: float = 1.0
    #: Optional display name and one-sentence rules summary for reports (default: ``name``).
    title: str = ""
    summary: str = ""
    #: Optional: what one complete play of the game is called in reports ("hand", "round").
    episode: str = "hand"
    #: Optional: names for scripted reference subjects in this game's terms, by agent
    #: (e.g. ``{"first-action": ...}``). Agents not listed keep the report's default names.
    reference_names: Mapping[str, str] = MappingProxyType({})

    def load(self) -> pyspiel.Game:
        return pyspiel.load_game(self.load_string)

    @abstractmethod
    def action_labels(self, state: pyspiel.State) -> dict[int, str]:
        """Map each legal action id at ``state`` to its label (e.g. ``{0: "CHECK", 1: "BET"}``)."""

    @abstractmethod
    def vocabulary(self) -> frozenset[str]:
        """Every label the game can ever use. Lets the parser tell illegal from unparseable."""

    @abstractmethod
    def render_infostate(self, state: pyspiel.State) -> str:
        """Describe the current player's situation: seat, private information, public history."""

    def short_label(self, state: pyspiel.State) -> str:
        """One-line description of the current player's infostate, for charts and lists.

        Optional: the default joins the lines of ``render_infostate``. Never shown to the subject.
        """
        return " \u00b7 ".join(self.render_infostate(state).splitlines())

    def describe_chance(self, state: pyspiel.State, action: int) -> str:
        """Describe a chance outcome (e.g. a card being dealt) for replays.

        Optional: the default is OpenSpiel's own string. Never shown to the subject.
        """
        return state.action_to_string(state.current_player(), action)

    def parse_action(self, state: pyspiel.State, text: str) -> ParseResult:
        labels = self.action_labels(state)
        result = parse_label(text, legal=list(labels.values()), vocabulary=self.vocabulary())
        if result.label is not None:
            result.action = next(a for a, lab in labels.items() if lab == result.label)
        return result
