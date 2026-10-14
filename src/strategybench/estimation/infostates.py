"""Enumerate every decision information state of a game (generic over OpenSpiel games)."""

from __future__ import annotations

from dataclasses import dataclass, field

import pyspiel
from open_spiel.python.algorithms import get_all_states


@dataclass(frozen=True)
class InfoState:
    #: OpenSpiel information-state string (unique per player within a game).
    key: str
    player: int
    legal_actions: tuple[int, ...]
    #: One concrete history in this infostate, used only for rendering the prompt.
    state: pyspiel.State = field(compare=False, hash=False, repr=False)

    @property
    def forced(self) -> bool:
        """A single legal action: nothing to ask the subject, nothing to estimate."""
        return len(self.legal_actions) == 1


def enumerate_infostates(game: pyspiel.Game) -> list[InfoState]:
    states = get_all_states.get_all_states(
        game, depth_limit=-1, include_terminals=False, include_chance_states=False
    )
    seen: dict[tuple[int, str], InfoState] = {}
    for state in states.values():
        player = state.current_player()
        key = state.information_state_string(player)
        if (player, key) not in seen:
            seen[(player, key)] = InfoState(key, player, tuple(state.legal_actions()), state)
    return sorted(seen.values(), key=lambda s: (s.player, s.key))
