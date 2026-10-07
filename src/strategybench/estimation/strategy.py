"""Turn collected samples into a behavioural strategy, and measure coverage.

Fill rule: an infostate with fewer than ``min_samples`` valid samples is played uniformly
over its legal actions. Filled infostates are always reported, never hidden.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyspiel
from open_spiel.python import policy as policy_lib

from strategybench.estimation.infostates import InfoState


@dataclass
class EstimatedStrategy:
    policy: policy_lib.TabularPolicy
    #: Number of valid samples behind each infostate (0 for filled ones).
    support: dict[str, int]
    filled: list[str]


def strategy_from_counts(
    game: pyspiel.Game,
    infostates: list[InfoState],
    counts: dict[str, dict[int, int]],
    min_samples: int = 1,
) -> EstimatedStrategy:
    policy = policy_lib.TabularPolicy(game)
    support, filled = {}, []
    for info in infostates:
        row = policy.policy_for_key(info.key)
        row[:] = 0.0
        c = counts.get(info.key, {})
        n = sum(c.values())
        support[info.key] = n
        if n >= min_samples:
            for action, k in c.items():
                row[action] = k / n
        else:
            filled.append(info.key)
            row[list(info.legal_actions)] = 1.0 / len(info.legal_actions)
    return EstimatedStrategy(policy, support, filled)


def strategy_from_probabilities(
    game: pyspiel.Game, infostates: list[InfoState], probabilities: dict[str, dict[int, float]]
) -> EstimatedStrategy:
    policy = policy_lib.TabularPolicy(game)
    support, filled = {}, []
    for info in infostates:
        row = policy.policy_for_key(info.key)
        row[:] = 0.0
        probs = probabilities.get(info.key)
        if probs is None:
            filled.append(info.key)
            support[info.key] = 0
            row[list(info.legal_actions)] = 1.0 / len(info.legal_actions)
        else:
            support[info.key] = 1
            for action, p in probs.items():
                row[action] = p
    return EstimatedStrategy(policy, support, filled)


def reach_probabilities(game: pyspiel.Game, policy: policy_lib.Policy) -> dict[str, float]:
    """Total probability (chance x both players) of reaching each decision infostate."""
    reach: dict[str, float] = {}

    def walk(state: pyspiel.State, p: float) -> None:
        if state.is_terminal() or p == 0.0:
            return
        if state.is_chance_node():
            outcomes = state.chance_outcomes()
        else:
            key = state.information_state_string()
            reach[key] = reach.get(key, 0.0) + p
            outcomes = list(policy.action_probabilities(state).items())
        for action, q in outcomes:
            walk(state.child(action), p * q)

    walk(game.new_initial_state(), 1.0)
    return reach


def coverage(
    game: pyspiel.Game, strategy: EstimatedStrategy, k: int = 1, policy: policy_lib.Policy | None = None
) -> float:
    """Reach-weighted fraction of infostates with at least ``k`` valid samples.

    Reach is measured under ``policy`` (default: the estimated strategy itself).
    """
    reach = reach_probabilities(game, policy or strategy.policy)
    total = sum(reach.values())
    if total == 0:
        return float("nan")
    covered = sum(r for key, r in reach.items() if strategy.support.get(key, 0) >= k)
    return float(covered / total)


def resample_counts(counts: dict[str, dict[int, int]], rng: np.random.Generator) -> dict[str, dict[int, int]]:
    """One bootstrap draw: resample each infostate's valid samples with replacement."""
    out = {}
    for key, c in counts.items():
        n = sum(c.values())
        if n == 0:
            out[key] = {}
            continue
        actions = list(c)
        draws = rng.multinomial(n, np.array([c[a] for a in actions]) / n)
        out[key] = {a: int(d) for a, d in zip(actions, draws, strict=True) if d}
    return out
