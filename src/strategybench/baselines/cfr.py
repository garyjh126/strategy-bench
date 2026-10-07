"""CFR equilibrium solving via OpenSpiel.

Thin wrapper around ``open_spiel.python.algorithms.cfr`` that records the
exploitability trajectory and the equilibrium game value. No CFR logic is
re-implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pyspiel
from open_spiel.python import policy as policy_lib
from open_spiel.python.algorithms import cfr, expected_game_score, exploitability


@dataclass
class CFRResult:
    game_name: str
    iterations: int
    average_policy: policy_lib.TabularPolicy
    # (iteration, exploitability) pairs, exploitability = NashConv / num_players.
    exploitability_history: list[tuple[int, float]] = field(default_factory=list)
    # Expected payoff of each player when both play the average policy.
    game_value: list[float] = field(default_factory=list)

    @property
    def final_exploitability(self) -> float:
        return self.exploitability_history[-1][1]


def solve_cfr(
    game_name: str = "kuhn_poker",
    iterations: int = 1000,
    eval_every: int = 100,
    plus: bool = False,
) -> CFRResult:
    """Run (vanilla or CFR+) CFR on an OpenSpiel game and track exploitability."""
    if iterations < 1 or eval_every < 1:
        raise ValueError("iterations and eval_every must be positive")

    game = pyspiel.load_game(game_name)
    solver = cfr.CFRPlusSolver(game) if plus else cfr.CFRSolver(game)

    history: list[tuple[int, float]] = []
    for it in range(1, iterations + 1):
        solver.evaluate_and_update_policy()
        if it % eval_every == 0 or it == iterations:
            history.append((it, exploitability.exploitability(game, solver.average_policy())))

    avg = solver.average_policy()
    value = expected_game_score.policy_value(game.new_initial_state(), [avg] * game.num_players())
    return CFRResult(
        game_name=game_name,
        iterations=iterations,
        average_policy=avg,
        exploitability_history=history,
        game_value=[float(v) for v in value],
    )
