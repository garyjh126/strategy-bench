"""Liar's Dice (OpenSpiel ``liars_dice`` with one three-sided die per player).

Each player rolls one die (faces 1 to 3) and sees only their own. Player 1 must open with a
bid; the players then alternate, each either making a higher bid or calling Liar. A bid QxF
claims that at least Q of the two dice show face F. The highest face (3) is wild: it counts
towards a bid on any face, so a bid on face 3 counts only 3s. Bids rank by quantity, then by
face. When Liar is called the bidder wins if the bid is true and the caller wins otherwise;
the winner gets +1 and the loser -1.

OpenSpiel actions (default ``reset-face`` bidding rule): action ``(Q - 1) * 3 + (F - 1)`` bids
QxF and action 6 calls Liar. Liar is not legal on the opening move, and after the highest bid
(2x3) it is the only legal action, so 96 of the 192 decision infostates are forced.
"""

from __future__ import annotations

import pyspiel

from strategybench.games.base import GameSpec

SIDES = 3
#: Dice in the game: one per player.
DICE = 2
LIAR = DICE * SIDES


def _seat_name(player: int) -> str:
    return f"Player {player + 1}"


def _bid(action: int) -> tuple[int, int]:
    """(quantity, face) of a bid action."""
    return action // SIDES + 1, action % SIDES + 1


def _label(action: int) -> str:
    if action == LIAR:
        return "LIAR"
    quantity, face = _bid(action)
    return f"{quantity}x{face}"


def _true_if(action: int) -> str:
    """When a bid is true, in words (the wild face counts towards every other face)."""
    quantity, face = _bid(action)
    faces = f"{face}" if face == SIDES else f"{face} or {SIDES}"
    return f"both dice show {faces}" if quantity == DICE else f"at least one of the two dice shows {faces}"


def _dice_and_bids(state: pyspiel.State) -> tuple[list[int], list[int]]:
    """Faces rolled so far (by seat) and the bid actions made so far."""
    history = state.history()
    return [a + 1 for a in history[:DICE]], history[DICE:]


class LiarsDiceSpec(GameSpec):
    name = "liars_dice"
    load_string = "liars_dice(numdice=1,dice_sides=3)"
    payoff_unit = "point"
    unit_size = 1.0
    title = "Liar's Dice"
    summary = (
        "One three-sided die each, with 3s wild. Players take turns raising a bid on what the two "
        "dice show, or call LIAR on the last bid; the winner of the challenge takes 1 point."
    )

    def vocabulary(self) -> frozenset[str]:
        return frozenset(_label(a) for a in range(LIAR + 1))

    def action_labels(self, state: pyspiel.State) -> dict[int, str]:
        return {a: _label(a) for a in state.legal_actions()}

    def short_label(self, state: pyspiel.State) -> str:
        dice, bids = _dice_and_bids(state)
        made = ", ".join(f"P{i % 2 + 1} {_label(b)}" for i, b in enumerate(bids))
        return f"Die {dice[state.current_player()]} · {made or 'opening bid'}"

    def describe_chance(self, state: pyspiel.State, action: int) -> str:
        # Dice are rolled before any bid, one per seat in seat order.
        return f"{_seat_name(len(state.history()))} rolls a {action + 1}"

    def render_infostate(self, state: pyspiel.State) -> str:
        me = state.current_player()
        dice, bids = _dice_and_bids(state)
        made = ", ".join(f"{_seat_name(i % 2)} bid {_label(b)}" for i, b in enumerate(bids))
        lines = [
            f"You are {_seat_name(me)} (you bid {'first' if me == 0 else 'second'}).",
            f"Your die: {dice[me]}.",
            f"Bids so far: {made or 'none'}.",
        ]
        if bids:
            bidder = _seat_name((len(bids) - 1) % 2)
            lines.append(f"Current bid: {_label(bids[-1])} by {bidder} (true if {_true_if(bids[-1])}).")
        return "\n".join(lines)
