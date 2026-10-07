"""Scripted reference policies (game-agnostic).

In Kuhn poker, ``first-action`` is "always pass" (check/fold) and ``last-action`` is
"always bet" (bet/call).
"""

from __future__ import annotations

import pyspiel
from open_spiel.python import policy as policy_lib


def uniform_policy(game: pyspiel.Game) -> policy_lib.TabularPolicy:
    return policy_lib.TabularPolicy(game)  # TabularPolicy initialises to uniform over legal actions


def _indexed_action_policy(game: pyspiel.Game, pick: int) -> policy_lib.TabularPolicy:
    policy = policy_lib.TabularPolicy(game)
    for key, state in policy.state_lookup.items():
        legal = policy.legal_actions_mask[state]
        actions = [a for a, ok in enumerate(legal) if ok]
        row = policy.policy_for_key(key)
        row[:] = 0.0
        row[actions[pick]] = 1.0
    return policy


def first_action_policy(game: pyspiel.Game) -> policy_lib.TabularPolicy:
    return _indexed_action_policy(game, 0)


def last_action_policy(game: pyspiel.Game) -> policy_lib.TabularPolicy:
    return _indexed_action_policy(game, -1)


def mix_policies(
    game: pyspiel.Game, a: policy_lib.TabularPolicy, b: policy_lib.TabularPolicy, weight_a: float
) -> policy_lib.TabularPolicy:
    out = policy_lib.TabularPolicy(game)
    out.action_probability_array[:] = (
        weight_a * a.action_probability_array + (1 - weight_a) * b.action_probability_array
    )
    return out
