"""Strategy explorer: every decision infostate of a game, a run's strategy next to the CFR profile.

Rows are sorted by reach: the probability that the situation arises when every seat plays the
run's estimated strategy (chance included), the same weighting the project uses for coverage.
Without a run, reach is measured under the CFR profile, or uniform play if there is none.
"""

from __future__ import annotations

import threading
from typing import Any

from sbgui.catalog import GameEntry, seat_name
from sbgui.policies import OpenSpielPolicy, RunPolicy, SeatPolicy, TablePolicy, UniformPolicy
from sbgui.profiles import Profile
from sbgui.runs import RunInfo, RunStrategy
from strategybench.estimation.infostates import enumerate_infostates
from strategybench.estimation.strategy import reach_probabilities

MAX_PAGE = 200
_cache: dict[tuple[str, str | None, bool], list[dict[str, Any]]] = {}
_lock = threading.Lock()


def _distance(a: dict[str, float], b: dict[str, float]) -> float:
    return 0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b))


def build_rows(
    entry: GameEntry, run: RunInfo | None, strategy: RunStrategy | None, profile: Profile | None
) -> list[dict[str, Any]]:
    key = (entry.key, run.run_id if run else None, profile is not None)
    with _lock:
        if key in _cache:
            return _cache[key]

    game = entry.game
    run_policy = RunPolicy(strategy, entry.action_labels) if strategy is not None else None
    table = TablePolicy(profile.table) if profile is not None else None
    weighting: SeatPolicy = run_policy or table or UniformPolicy()
    everyone = dict.fromkeys(range(game.num_players()), weighting)
    reach = reach_probabilities(game, OpenSpielPolicy(game, everyone))

    rows = []
    for info in enumerate_infostates(game):
        state = info.state
        labels = entry.action_labels(state)
        row: dict[str, Any] = {
            "key": info.key,
            "player": info.player,
            "seat": seat_name(info.player),
            "short": entry.short_label(state),
            "situation": entry.situation(state)[0],
            "reach": reach.get(info.key, 0.0),
            "forced": len(info.legal_actions) == 1,
            "labels": [labels[a] for a in info.legal_actions],
        }
        if run_policy is not None:
            decision = run_policy.decide(state)
            record = strategy.lookup(info.player, info.key)
            row["run"] = {labels[a]: decision.probs.get(a, 0.0) for a in info.legal_actions}
            row["support"] = record.support if record else 0
            row["note"] = decision.note
        if table is not None:
            decision = table.decide(state)
            row["cfr"] = {labels[a]: decision.probs.get(a, 0.0) for a in info.legal_actions}
        if "run" in row and "cfr" in row:
            row["distance"] = _distance(row["run"], row["cfr"])
        rows.append(row)
    rows.sort(key=lambda r: (-r["reach"], r["player"], r["key"]))
    with _lock:
        _cache[key] = rows
    return rows


def page(
    rows: list[dict[str, Any]],
    player: int | None = None,
    query: str = "",
    hide_forced: bool = True,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    query = query.strip().lower()
    selected = [
        r
        for r in rows
        if (player is None or r["player"] == player)
        and not (hide_forced and r["forced"])
        and (not query or query in r["short"].lower() or query in r["key"].lower())
    ]
    limit = max(1, min(limit, MAX_PAGE))
    offset = max(0, offset)
    return {
        "total": len(rows),
        "matched": len(selected),
        "offset": offset,
        "rows": selected[offset : offset + limit],
    }
