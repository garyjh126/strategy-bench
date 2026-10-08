"""Leduc poker (OpenSpiel ``leduc_poker`` with ``suit_isomorphism=True``).

Six cards (two each of Jack, Queen, King), ante 1, two betting rounds with one public card
dealt between them. Bets/raises are 2 chips in round 1 and 4 in round 2, with at most one
bet and one raise per round. A pair with the public card wins; otherwise the higher rank.

Suit isomorphism makes OpenSpiel deal ranks instead of suited cards, so information states
are exactly what the prompt describes (the subject is never told suits). This gives 288
decision infostates instead of 936, with the same equilibrium value.

OpenSpiel actions: 0 = Fold, 1 = Call (check when nothing is owed), 2 = Raise (bet when
nothing is owed).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pyspiel

from strategybench.games.base import GameSpec

_RANK_NAMES = {0: "Jack", 1: "Queen", 2: "King"}
_FOLD, _CALL, _RAISE = 0, 1, 2
_BET_SIZE = {1: 2, 2: 4}


def _seat_name(player: int) -> str:
    return f"Player {player + 1}"


@dataclass
class _Replay:
    private: list[int] = field(default_factory=list)
    public: int | None = None
    round: int = 1
    contributions: list[int] = field(default_factory=lambda: [1, 1])
    betting: dict[int, list[str]] = field(default_factory=lambda: {1: [], 2: []})


def _replay(state: pyspiel.State) -> _Replay:
    """Walk the history from the start, tracking cards, contributions and betting text."""
    r = _Replay()
    s = state.get_game().new_initial_state()
    for action in state.history():
        if s.is_chance_node():
            if len(r.private) < 2:
                r.private.append(action)
            else:
                r.public, r.round = action, 2
        else:
            p = s.current_player()
            owed = r.contributions[1 - p] - r.contributions[p]
            if action == _FOLD:
                text = "folded"
            elif action == _CALL:
                text = "called" if owed else "checked"
                r.contributions[p] += owed
            else:
                size = _BET_SIZE[r.round]
                text = f"raised by {size}" if owed else f"bet {size}"
                r.contributions[p] += owed + size
            r.betting[r.round].append(f"{_seat_name(p)} {text}")
        s.apply_action(action)
    return r


class LeducSpec(GameSpec):
    name = "leduc"
    load_string = "leduc_poker(suit_isomorphism=True)"
    payoff_unit = "ante"
    unit_size = 1.0
    title = "Leduc poker"
    summary = (
        "Six cards (two each of Jack, Queen, King), one private card each, a public card, and two "
        "betting rounds with at most one bet and one raise per round."
    )

    def vocabulary(self) -> frozenset[str]:
        return frozenset({"CHECK", "BET", "FOLD", "CALL", "RAISE"})

    def action_labels(self, state: pyspiel.State) -> dict[int, str]:
        r = _replay(state)
        p = state.current_player()
        facing = r.contributions[1 - p] > r.contributions[p]
        names = {_FOLD: "FOLD", _CALL: "CALL", _RAISE: "RAISE"} if facing else {_CALL: "CHECK", _RAISE: "BET"}
        return {a: names[a] for a in state.legal_actions()}

    def short_label(self, state: pyspiel.State) -> str:
        r = _replay(state)
        cards = _RANK_NAMES[r.private[state.current_player()]]
        if r.public is not None:
            cards += f", public {_RANK_NAMES[r.public]}"
        rounds = [f"R{n}: {', '.join(r.betting[n]) or 'first to act'}" for n in range(1, r.round + 1)]
        return " \u00b7 ".join([cards, *rounds])

    def describe_chance(self, state: pyspiel.State, action: int) -> str:
        dealt = len(_replay(state).private)
        if dealt < 2:
            return f"{_seat_name(dealt)} is dealt a {_RANK_NAMES[action]}"
        return f"The public card is a {_RANK_NAMES[action]}"

    def render_infostate(self, state: pyspiel.State) -> str:
        r = _replay(state)
        me = state.current_player()
        mine, theirs = r.contributions[me], r.contributions[1 - me]
        order = "you act first" if me == 0 else "you act second"
        lines = [
            f"You are {_seat_name(me)} ({order} in each betting round).",
            f"Your private card: {_RANK_NAMES[r.private[me]]}.",
            "Public card: " + ("not dealt yet." if r.public is None else f"{_RANK_NAMES[r.public]}."),
            f"Current round: {r.round} of 2.",
            f"Round 1 betting: {', '.join(r.betting[1]) or 'none'}.",
        ]
        if r.round == 2:
            lines.append(f"Round 2 betting: {', '.join(r.betting[2]) or 'none'}.")
        pot = f"Pot: {mine + theirs} chips (you have put in {mine}, your opponent {theirs})."
        if theirs > mine:
            pot += f" To call: {theirs - mine} chips."
        lines.append(pot)
        return "\n".join(lines)
