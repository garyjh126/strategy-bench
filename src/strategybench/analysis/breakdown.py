"""Where a best responder gains: an exact per-infostate decomposition of M2.

Fix the subject's strategy σ̂ in seat ``i`` and let the other seat ``j`` move from its
equilibrium strategy σ* to a best response BR against σ̂. The change in ``j``'s value
telescopes over ``j``'s information states (a performance-difference identity):

    u_j(BR, σ̂) - u_j(σ*, σ̂) = Σ_I  π_j*(I) · [ v(I, BR(I)) - Σ_a σ*(I, a) · v(I, a) ]

where ``v(I, a) = Σ_{h in I} π_-j(h) · q(h, a)`` is the counterfactual value of action ``a``
at ``I`` when ``j`` best-responds afterwards, ``π_-j`` is the chance-and-subject reach and
``π_j*(I)`` is ``j``'s own reach under σ*. Every term is non-negative because BR(I)
maximises ``v(I, ·)``. The remaining part, ``u_j(σ*, σ̂) - v*_j``, is what the equilibrium
gains without adapting, which is exactly the subject's M3 loss in seat ``i``. Hence

    M2_i = M3_i + Σ_I contribution(I).

Dividing by the infostate's reach ``π_j*(I) · Σ_h π_-j(h)`` gives per-visit values: how often
the situation arises when the opponent plays the equilibrium, and how much more the best
response earns each time it does.

Values are in native payoff units. Two-player zero-sum games only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pyspiel
from open_spiel.python import policy as policy_lib
from open_spiel.python.algorithms import best_response

from strategybench.analysis.metrics import exact_seat_values, seat_mixture
from strategybench.estimation.strategy import reach_probabilities


@dataclass
class ResponderInfostate:
    """One information state of the best-responding seat."""

    key: str
    player: int
    #: Probability the infostate is reached (chance, subject σ̂, responder at equilibrium).
    reach: float
    #: Per-visit value to the responder of each legal action, best-responding afterwards
    #: (``nan`` when the subject never lets the infostate be reached).
    values: dict[int, float]
    equilibrium: dict[int, float]
    best_response: int
    #: Per-visit value of the equilibrium mix, ``Σ_a σ*(I, a) · values[a]``.
    eq_mix_value: float
    #: ``values[best_response] - eq_mix_value``.
    edge: float
    #: ``reach * edge`` (exact form above; 0 when unreached).
    contribution: float
    #: The history in the infostate where switching from the equilibrium mix to the best
    #: response gains most (reach-weighted), as an action sequence from the root.
    example_history: list[int]


@dataclass
class SubjectInfostate:
    """One information state of the subject's seat."""

    key: str
    player: int
    #: Probability the infostate is reached (chance, subject σ̂, opponent at equilibrium).
    reach: float
    estimated: dict[int, float]
    equilibrium: dict[int, float]
    #: Total variation distance between the estimated and equilibrium action distributions.
    distance: float


@dataclass
class SeatBreakdown:
    subject_seat: int
    #: Value to the responder of the best response against σ̂.
    br_value: float
    #: Value to the responder of the equilibrium strategy against σ̂.
    eq_value: float
    #: The responder seat's equilibrium game value.
    game_value: float
    responder: list[ResponderInfostate]
    subject: list[SubjectInfostate]

    @property
    def responder_seat(self) -> int:
        return 1 - self.subject_seat

    @property
    def passive(self) -> float:
        """What the equilibrium gains without adapting (equals M3 for the subject's seat)."""
        return self.eq_value - self.game_value

    @property
    def active(self) -> float:
        """What adapting to σ̂ adds; equals the sum of the contributions."""
        return self.br_value - self.eq_value

    @property
    def gain(self) -> float:
        """M2 for the subject's seat."""
        return self.br_value - self.game_value


def _own_reach(game: pyspiel.Game, player: int, policy: policy_lib.Policy) -> dict[str, float]:
    """``player``'s own contribution to the reach of each of its infostates under ``policy``."""
    reach: dict[str, float] = {}

    def walk(state: pyspiel.State, p: float) -> None:
        if state.is_terminal():
            return
        if state.is_chance_node():
            for action, _ in state.chance_outcomes():
                walk(state.child(action), p)
        elif state.current_player() == player:
            reach[state.information_state_string()] = p  # identical across the infostate (perfect recall)
            for action, q in policy.action_probabilities(state).items():
                walk(state.child(action), p * q)
        else:
            for action in state.legal_actions():
                walk(state.child(action), p)

    walk(game.new_initial_state(), 1.0)
    return reach


def _total_variation(a: dict[int, float], b: dict[int, float]) -> float:
    return 0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b))


def br_breakdown(
    game: pyspiel.Game,
    subject: policy_lib.Policy,
    equilibrium: policy_lib.Policy,
    game_values: list[float],
) -> list[SeatBreakdown]:
    """Per-seat decomposition of the best-response gain against ``subject`` (see module doc)."""
    if game.num_players() != 2 or game.get_type().utility != pyspiel.GameType.Utility.ZERO_SUM:
        raise ValueError("the breakdown is defined for two-player zero-sum games")
    root = game.new_initial_state()
    eq_vs_subject = exact_seat_values(game, equilibrium, subject)

    seats = []
    for seat in range(2):
        resp = 1 - seat
        br = best_response.BestResponsePolicy(game, resp, subject)
        br_value = float(br.value(root))
        own = _own_reach(game, resp, equilibrium)

        responder = []
        for key, nodes in br.infosets.items():
            state = nodes[0][0]
            legal = state.legal_actions()
            eq_probs = {a: float(p) for a, p in equilibrium.action_probabilities(state).items()}
            cf = sum(p for _, p in nodes)
            best = br.best_response_action(key)
            reach = own.get(key, 0.0) * cf
            if cf > 0:
                values = {a: sum(p * br.q_value(s, a) for s, p in nodes) / cf for a in legal}
                mix = sum(eq_probs.get(a, 0.0) * v for a, v in values.items())
                edge = values[best] - mix
            else:
                values = {a: math.nan for a in legal}
                mix = edge = math.nan
            if reach > 0:
                gains = [
                    p * (br.q_value(h, best) - sum(q * br.q_value(h, a) for a, q in eq_probs.items()))
                    for h, p in nodes
                ]
                example = nodes[max(range(len(nodes)), key=gains.__getitem__)][0]
            else:
                example = max(nodes, key=lambda node: node[1])[0]
            responder.append(
                ResponderInfostate(
                    key=key,
                    player=resp,
                    reach=reach,
                    values=values,
                    equilibrium=eq_probs,
                    best_response=best,
                    eq_mix_value=mix,
                    edge=edge,
                    contribution=reach * edge if reach > 0 else 0.0,
                    example_history=list(example.history()),
                )
            )

        mixed = seat_mixture(game, seat, subject, equilibrium)
        reach_all = reach_probabilities(game, mixed)
        subject_rows = []
        for key in mixed.states_per_player[seat]:
            state = mixed.states[mixed.state_lookup[key]]
            est = {a: float(p) for a, p in subject.action_probabilities(state).items()}
            ref = {a: float(p) for a, p in equilibrium.action_probabilities(state).items()}
            subject_rows.append(
                SubjectInfostate(
                    key=key,
                    player=seat,
                    reach=reach_all.get(key, 0.0),
                    estimated=est,
                    equilibrium=ref,
                    distance=_total_variation(est, ref),
                )
            )

        seats.append(
            SeatBreakdown(
                subject_seat=seat,
                br_value=br_value,
                eq_value=float(eq_vs_subject[resp]),
                game_value=float(game_values[resp]),
                responder=responder,
                subject=subject_rows,
            )
        )
    return seats
