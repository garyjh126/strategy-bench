"""Data for the strategy-viewer mockup: an invented Kuhn subject, scored exactly.

The subject's action frequencies (and its sample counts) are made up. Everything that follows
from them is computed with the project's own code: best responses, per-visit edges,
contributions (strategybench.analysis.breakdown), the CFR+ reference (solve_equilibrium, read
from the cache in runs/equilibria) and the seat values.

    uv run python docs/proposals/mockup/make_data.py docs/proposals/mockup/data.json
"""

import json
import math
import sys

import pyspiel
from open_spiel.python import policy as policy_lib

from strategybench.analysis.breakdown import br_breakdown
from strategybench.analysis.metrics import exact_seat_values, solve_equilibrium

GAME = pyspiel.load_game("kuhn_poker")
CARDS = ["Jack", "Queen", "King"]
N = 200

# Invented counts of the aggressive action (BET or CALL) out of N samples, per infostate.
# Player 1: first to act, and facing check-bet. Player 2: after a check, and facing a bet.
AGGRESSIVE = {
    "0": 72, "1": 38, "2": 106,          # P1 opens: J bluffs 36%, Q 19%, K 53%
    "0pb": 20, "1pb": 76, "2pb": 192,    # P1 facing check-bet: calls J 10%, Q 38%, K 96%
    "0p": 90, "1p": 30, "2p": 170,       # P2 after a check: bets J 45%, Q 15%, K 85%
    "0b": 12, "1b": 52, "2b": 194,       # P2 facing a bet: calls J 6%, Q 26%, K 97%
}  # fmt: skip

NODES = {  # public history -> (acting player, labels for actions 0 and 1, name)
    "": (0, ["CHECK", "BET"], "Player 1 to act"),
    "p": (1, ["CHECK", "BET"], "Player 1 checked"),
    "b": (1, ["FOLD", "CALL"], "Player 1 bet"),
    "pb": (0, ["FOLD", "CALL"], "Player 1 checked, Player 2 bet"),
}
POT = {"": 2, "p": 2, "b": 3, "pb": 3}  # chips in the pot when the decision is made


def wilson(k, n, z=1.96):
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def subject_policy():
    pol = policy_lib.TabularPolicy(GAME)
    for key, row in pol.state_lookup.items():
        p = AGGRESSIVE[key] / N
        pol.action_probability_array[row] = [1 - p, p]
    return pol


def main(out_path):
    subject = subject_policy()
    eq = solve_equilibrium("kuhn_poker", 2000, "runs/equilibria")
    seats = br_breakdown(GAME, subject, eq.policy, eq.values)
    seat = seats[0]  # the subject as Player 1
    resp = {r.key: r for r in seat.responder}
    subj = {s.key: s for s in seat.subject}
    total_active = seat.active

    def eq_probs(key):
        return [float(x) for x in eq.policy.action_probability_array[eq.policy.state_lookup[key]]]

    nodes = []
    for hist, (player, labels, name) in NODES.items():
        cells = []
        for card in range(3):
            key = f"{card}{hist}"
            cell = {"card": CARDS[card], "key": key, "equilibrium": eq_probs(key)}
            if player == 0:
                s = subj[key]
                k = AGGRESSIVE[key]
                lo, hi = wilson(k, N)
                cell.update(
                    role="subject",
                    estimated=[1 - k / N, k / N],
                    counts=[N - k, k],
                    ci_aggressive=[lo, hi],
                    reach=s.reach,
                    distance=s.distance,
                )
            else:
                r = resp[key]
                cell.update(
                    role="responder",
                    best_response=r.best_response,
                    values=[r.values[0], r.values[1]],
                    eq_mix_value=r.eq_mix_value,
                    edge=r.edge,
                    reach=r.reach,
                    contribution=r.contribution,
                    share=r.contribution / total_active if total_active > 0 else 0.0,
                )
            cells.append(cell)
        nodes.append({"history": hist, "player": player, "labels": labels, "name": name, "pot": POT[hist],
                      "cells": cells})  # fmt: skip

    # Overall frequencies at each node, each strategy averaged over the hands it holds there under
    # its own play (the other seat at equilibrium).
    def own_reach(policy_p1, policy_p2):
        reach = {}

        def walk(state, p):
            if state.is_terminal() or p == 0:
                return
            if state.is_chance_node():
                for a, q in state.chance_outcomes():
                    walk(state.child(a), p * q)
                return
            key = state.information_state_string()
            reach[key] = reach.get(key, 0.0) + p
            pol = policy_p1 if state.current_player() == 0 else policy_p2
            for a, q in pol.action_probabilities(state).items():
                walk(state.child(a), p * q)

        walk(GAME.new_initial_state(), 1.0)
        return reach

    reach_subject = own_reach(subject, eq.policy)
    reach_eq = own_reach(eq.policy, eq.policy)
    for node in nodes:
        keys = [c["key"] for c in node["cells"]]
        for name, reach, probs in (
            ("overall_equilibrium", reach_eq, [c["equilibrium"] for c in node["cells"]]),
            (
                "overall_estimated" if node["player"] == 0 else "overall_best_response",
                reach_subject,
                [c["estimated"] if node["player"] == 0 else [float(c["best_response"] == a) for a in (0, 1)]
                 for c in node["cells"]],
            ),
        ):  # fmt: skip
            w = [reach.get(k, 0.0) for k in keys]
            total = sum(w)
            node[name] = [sum(wi * p[a] for wi, p in zip(w, probs, strict=True)) / total for a in (0, 1)]
        node["reached"] = sum(reach_subject.get(k, 0.0) for k in keys)

    values = exact_seat_values(GAME, subject, eq.policy)
    out = {
        "note": "Invented subject frequencies; everything else computed exactly from them.",
        "subject_seat": 0,
        "unit": "ante",
        "gain": seat.gain,
        "passive": seat.passive,
        "active": seat.active,
        "game_value_p1": eq.values[0],
        "subject_value_vs_eq_p1": values[0],
        "eq_exploitability": None,
        "nodes": nodes,
    }
    with open(out_path, "w") as f:
        json.dump(out, f, indent=1)
    print(f"gain {seat.gain:.4f} = passive {seat.passive:.4f} + active {seat.active:.4f}")
    for n in nodes:
        for c in n["cells"]:
            extra = (
                f"BR {n['labels'][c['best_response']]} edge {c['edge']:.3f} contrib {c['contribution']:.4f}"
                if c["role"] == "responder"
                else f"est {c['estimated'][1]:.2f} eq {c['equilibrium'][1]:.3f} dist {c['distance']:.3f}"
            )
            print(f"{n['history'] or 'root':4s} {c['card']:6s} reach {c['reach']:.3f} {extra}")


if __name__ == "__main__":
    main(sys.argv[1])
