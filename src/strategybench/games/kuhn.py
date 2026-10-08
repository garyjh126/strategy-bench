"""Kuhn poker (OpenSpiel ``kuhn_poker``).

Three cards (J < Q < K), ante 1, one bet of size 1. OpenSpiel action 0 is "Pass"
(check, or fold when facing a bet) and action 1 is "Bet" (bet, or call when facing one).
"""

from __future__ import annotations

import pyspiel

from strategybench.games.base import GameSpec

_CARD_NAMES = {0: "Jack", 1: "Queen", 2: "King"}
_PASS, _BET = 0, 1


def _seat_name(player: int) -> str:
    return f"Player {player + 1}"


class KuhnSpec(GameSpec):
    name = "kuhn"
    load_string = "kuhn_poker"
    payoff_unit = "ante"
    unit_size = 1.0
    title = "Kuhn poker"
    summary = (
        "Three cards (Jack, Queen, King), one private card each and a single betting round "
        "with at most one bet."
    )

    def vocabulary(self) -> frozenset[str]:
        return frozenset({"CHECK", "BET", "FOLD", "CALL"})

    @staticmethod
    def _betting(state: pyspiel.State) -> list[int]:
        return list(state.history()[state.get_game().num_players() :])

    def _events(self, state: pyspiel.State) -> list[str]:
        events = []
        bet_made = False
        for i, action in enumerate(self._betting(state)):
            actor = _seat_name(i % 2)
            if action == _BET:
                events.append(f"{actor} called" if bet_made else f"{actor} bet")
                bet_made = True
            else:
                events.append(f"{actor} folded" if bet_made else f"{actor} checked")
        return events

    def action_labels(self, state: pyspiel.State) -> dict[int, str]:
        facing_bet = _BET in self._betting(state)
        names = {_PASS: "FOLD", _BET: "CALL"} if facing_bet else {_PASS: "CHECK", _BET: "BET"}
        return {a: names[a] for a in state.legal_actions()}

    def short_label(self, state: pyspiel.State) -> str:
        card = _CARD_NAMES[state.history()[state.current_player()]]
        return f"{card} \u00b7 {', '.join(self._events(state)) or 'first to act'}"

    def describe_chance(self, state: pyspiel.State, action: int) -> str:
        return f"{_seat_name(len(state.history()))} is dealt the {_CARD_NAMES[action]}"

    def render_infostate(self, state: pyspiel.State) -> str:
        player = state.current_player()
        card = state.history()[player]
        role = "you act first" if player == 0 else "you act second"

        events = self._events(state)
        return "\n".join(
            [
                f"You are {_seat_name(player)} ({role}).",
                f"Your card: {_CARD_NAMES[card]}.",
                f"Actions so far: {', '.join(events) if events else 'none'}.",
            ]
        )
