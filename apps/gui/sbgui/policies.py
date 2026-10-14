"""What a non-human seat plays: uniform random, a CFR profile, or a run's estimated strategy.

Every policy answers ``decide(state)`` with a ``Decision`` (action probabilities plus a note
when it had to fall back to uniform), or ``None`` when it cannot answer yet (a CFR profile
that is still being computed). Fallbacks are always reported, never silent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pyspiel
from open_spiel.python import policy as policy_lib

from sbgui.runs import RunStrategy


@dataclass
class Decision:
    probs: dict[int, float]
    #: Why the policy fell back to uniform, if it did.
    note: str | None = None


def uniform(state: pyspiel.State) -> dict[int, float]:
    legal = state.legal_actions()
    return {a: 1.0 / len(legal) for a in legal}


class SeatPolicy(Protocol):
    def decide(self, state: pyspiel.State) -> Decision | None: ...


class UniformPolicy:
    def decide(self, state: pyspiel.State) -> Decision:
        return Decision(uniform(state))


class TablePolicy:
    """A tabular policy keyed by OpenSpiel information-state string (a CFR profile)."""

    def __init__(self, table: dict[str, dict[int, float]]) -> None:
        self.table = table

    def decide(self, state: pyspiel.State) -> Decision:
        probs = self.table.get(state.information_state_string())
        if probs is None or set(probs) - set(state.legal_actions()):
            return Decision(uniform(state), "situation missing from the CFR profile: played uniformly")
        return Decision(dict(probs))


class PendingTablePolicy:
    """A CFR profile seat whose profile is fetched from the manager on every move."""

    def __init__(self, fetch) -> None:
        self._fetch = fetch

    def decide(self, state: pyspiel.State) -> Decision | None:
        profile = self._fetch()
        if profile is None:
            return None
        return TablePolicy(profile.table).decide(state)


class RunPolicy:
    """A run's estimated strategy (``strategy.json``: per infostate, probabilities by label)."""

    def __init__(self, strategy: RunStrategy, labels) -> None:
        self.strategy = strategy
        #: ``labels(state) -> {action: label}`` (the game's GameSpec labels).
        self._labels = labels

    def decide(self, state: pyspiel.State) -> Decision:
        record = self.strategy.lookup(state.current_player(), state.information_state_string())
        if record is None:
            return Decision(uniform(state), "situation not in the run: played uniformly")
        if record.filled:
            return Decision(uniform(state), "no valid samples in the run here: uniform, as in its metrics")
        labels = self._labels(state)
        try:
            probs = {a: float(record.estimated[label]) for a, label in labels.items()}
        except KeyError:
            return Decision(uniform(state), "run labels do not match this situation: played uniformly")
        total = sum(probs.values())
        if total <= 0:
            return Decision(uniform(state), "run probabilities sum to zero: played uniformly")
        return Decision({a: p / total for a, p in probs.items()})


class OpenSpielPolicy(policy_lib.Policy):
    """Adapter so OpenSpiel algorithms (best response, reach) can use a seat policy.

    Seats without a fixed policy (humans, or a profile not ready yet) play uniformly here;
    callers only use this where those seats are never consulted or say so.
    """

    def __init__(self, game: pyspiel.Game, seats: dict[int, SeatPolicy]) -> None:
        super().__init__(game, list(range(game.num_players())))
        self.seats = seats

    def action_probabilities(self, state: pyspiel.State, player_id: int | None = None) -> dict[int, float]:
        seat = self.seats.get(state.current_player())
        decision = seat.decide(state) if seat is not None else None
        return decision.probs if decision is not None else uniform(state)
