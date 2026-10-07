"""Exploitation metrics for a fixed (estimated) strategy profile, two-player zero-sum games.

Conventions (seat ``i`` is OpenSpiel player ``i``; "Player 1" in prompts is seat 0):

* M1 ``exploitability``: OpenSpiel's ``exploitability`` = NashConv / 2. In two-player
  zero-sum games this equals the mean of the two M2 gains below.
* M2 ``br_gain[i]``: when the subject sits in seat ``i``, how much more a best responder in
  the other seat earns than that seat's equilibrium value.
* M3 ``h2h_loss[i]``: the subject's expected shortfall in seat ``i`` against the
  equilibrium strategy, relative to the equilibrium value of seat ``i``. Computed exactly.

All values are in native payoff units per hand; ``*_norm`` divides by the game's unit size.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pyspiel
from open_spiel.python import policy as policy_lib
from open_spiel.python.algorithms import best_response, expected_game_score, exploitability

from strategybench.baselines.cfr import solve_cfr


@dataclass
class Equilibrium:
    policy: policy_lib.TabularPolicy
    #: Expected value of each seat when both play the equilibrium.
    values: list[float]
    exploitability: float


def solve_equilibrium(load_string: str, iterations: int = 2000) -> Equilibrium:
    result = solve_cfr(load_string, iterations=iterations, eval_every=iterations, plus=True)
    return Equilibrium(result.average_policy, result.game_value, result.final_exploitability)


@dataclass
class Metrics:
    exploitability: float
    br_value: list[float]
    br_gain: list[float]
    h2h_value: list[float]
    h2h_loss: list[float]
    unit_size: float = 1.0

    def as_dict(self) -> dict[str, object]:
        d = asdict(self)
        u = self.unit_size
        d["exploitability_norm"] = self.exploitability / u
        d["br_gain_norm"] = [g / u for g in self.br_gain]
        d["h2h_loss_norm"] = [x / u for x in self.h2h_loss]
        return d


def seat_mixture(
    game: pyspiel.Game, seat: int, subject: policy_lib.Policy, other: policy_lib.Policy
) -> policy_lib.TabularPolicy:
    """Profile where ``seat`` plays ``subject`` and every other seat plays ``other``."""
    mixed = policy_lib.TabularPolicy(game)
    for player, keys in enumerate(mixed.states_per_player):
        src = subject if player == seat else other
        for key in keys:
            mixed.policy_for_key(key)[:] = src.policy_for_key(key)
    return mixed


def compute_metrics(
    game: pyspiel.Game, policy: policy_lib.TabularPolicy, eq: Equilibrium, unit_size: float = 1.0
) -> Metrics:
    if game.num_players() != 2 or game.get_type().utility != pyspiel.GameType.Utility.ZERO_SUM:
        raise ValueError("metrics are defined for two-player zero-sum games")

    root = game.new_initial_state()
    br_value = [best_response.BestResponsePolicy(game, p, policy).value(root) for p in range(2)]
    br_gain = [br_value[1 - i] - eq.values[1 - i] for i in range(2)]

    h2h_value = []
    for seat in range(2):
        mixed = seat_mixture(game, seat, policy, eq.policy)
        h2h_value.append(float(expected_game_score.policy_value(root, [mixed, mixed])[seat]))
    h2h_loss = [eq.values[i] - h2h_value[i] for i in range(2)]

    return Metrics(
        exploitability=float(exploitability.exploitability(game, policy)),
        br_value=[float(v) for v in br_value],
        br_gain=[float(g) for g in br_gain],
        h2h_value=h2h_value,
        h2h_loss=[float(x) for x in h2h_loss],
        unit_size=unit_size,
    )
