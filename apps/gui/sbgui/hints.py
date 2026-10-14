"""Best-response hint for two-player games: what each action is worth against the other seat.

At the human's information state ``I`` and for each legal action ``a``:

    v(I, a) = Σ_{h in I} π_-i(h) · q(h, a) / Σ_{h in I} π_-i(h)

where ``π_-i`` is the reach probability from chance and the other seat's fixed policy, and
``q`` is the value of playing ``a`` at history ``h`` and best-responding afterwards (OpenSpiel
``BestResponsePolicy``). This is the same per-visit value used in ``analysis/breakdown.py``.
It assumes the other seat keeps playing its policy and that you know that policy.
"""

from __future__ import annotations

from typing import Any

from open_spiel.python.algorithms import best_response

from sbgui.policies import OpenSpielPolicy
from sbgui.session import Session


def unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


def best_response_hint(session: Session) -> dict[str, Any]:
    entry = session.entry
    with session.lock:
        if entry.num_players != 2:
            return unavailable("Best-response values are offered for two-player games only.")
        if not entry.has_infostates:
            return unavailable("OpenSpiel gives no information states for this game.")
        if not entry.size.enumerable:
            return unavailable("This game is too large to compute a best response here.")
        if session.phase() != "human":
            return unavailable("Available when a human seat is to act.")
        state = session.state
        me = state.current_player()
        other = session.seats[1 - me]
        if other.kind == "human":
            return unavailable("The other seat is human, so there is no fixed policy to respond to.")
        if other.kind == "cfr" and session.profiles.get(entry) is None:
            return unavailable("Waiting for the CFR profile.")

        cache_key = (me, other.kind, other.run_id)
        br = session.hint_cache.get(cache_key)
        if br is None:
            fixed = OpenSpielPolicy(entry.game, {1 - me: other.policy})
            br = best_response.BestResponsePolicy(entry.game, me, fixed)
            session.hint_cache[cache_key] = br
        nodes = br.infosets.get(state.information_state_string(me), [])
        reach = sum(p for _, p in nodes)
        if reach <= 0:
            return unavailable(f"The {other.kind_name} seat never lets this situation arise.")
        labels = entry.action_labels(state)
        values = {a: sum(p * br.q_value(h, a) for h, p in nodes) / reach for a in state.legal_actions()}
        best = max(values.values())
        return {
            "available": True,
            "player": me,
            "against": {"seat": 1 - me, "kind_name": other.kind_name, "name": other.name},
            "unit": entry.unit,
            "unit_size": entry.unit_size,
            "values": [
                {"action": a, "label": labels[a], "value": v, "best": abs(v - best) <= 1e-12}
                for a, v in values.items()
            ],
        }
