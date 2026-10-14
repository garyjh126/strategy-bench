"""Demonstrate the proposed multiway StrategyBench metric on three-player Kuhn poker.

A subject strategy sits in one seat; the other two seats play a fixed reference profile.
For each (subject, seat, reference) the script reports:

* subject_ev: the subject's expected chips per hand in that seat.
* loss_vs_reference: what the reference strategy would have earned in that seat, minus
  subject_ev (the multiway analogue of M3, head-to-head loss vs equilibrium).
* seat_regret: best-response value in that seat against the two reference opponents, minus
  subject_ev (always >= 0; the subject's own best-response gain).
* opponent_gains: for each other seat, how much that player gains by switching from the
  reference to a best response with the third seat held fixed (the multiway analogue of
  M2), plus who pays for the largest of those gains (subject or bystander).
* punishment_loss: for each other seat, how much the subject loses if that opponent
  switches to the strategy that minimises the subject's value (third seat fixed). This is
  subject-centred: a selfish best responder's gain can come from the bystander instead.
* self_play_gains: every seat played by the subject; each player's best-response gain
  (the analogue of M1 when the subject plays all seats, as StrategyBench does in 2-player).

Writes results/kuhn3_seat_metric.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import kuhn3_family as fam
import numpy as np
import pyspiel
from open_spiel.python import policy as policy_lib
from tabular import GameTree

RESULTS = Path(__file__).parent / "results"
SEATS = ("P1", "P2", "P3")


def scripted(tree: GameTree, rule) -> np.ndarray:
    """Flat profile from rule(card, facing_bet) -> probability of the aggressive action."""
    sigma = np.zeros(tree.num_seqs)
    for info, k in enumerate(tree.infoset_keys):
        card, history = int(k[0]), k[1:]
        p = rule(card, "b" in history)
        first = tree.infoset_first_seq[info]
        sigma[first], sigma[first + 1] = 1 - p, p
    return sigma


def splice(tree: GameTree, base: np.ndarray, seat: int, other: np.ndarray) -> np.ndarray:
    return np.where(tree.seq_player == seat, other, base)


def main() -> None:
    tree = GameTree(pyspiel.load_game("kuhn_poker(players=3)"))
    solver = pyspiel.CFRPlusSolver(tree.game)
    for _ in range(5000):
        solver.evaluate_and_update_policy()
    cfr_plus = tree.from_openspiel(
        policy_lib.pyspiel_policy_to_python_policy(tree.game, solver.tabular_average_policy())
    )
    beta0 = fam.member("c11=0", {"b11": 0.0, "b21": 0.0, "b32": 0.0, "c33": 0.5})
    beta14 = fam.member("c11=0", {"b11": 0.25, "b21": 0.25, "b32": 15 / 16, "c33": 0.0})
    # Table 4 of Szafron et al.: player 2 plays this c11 = 1/2 member's strategy.
    table4 = fam.member("c11=1/2", {"b11": 0.25, "b21": 0.0, "b23": 0.125, "b32": 0.0, "c33": 0.5})
    references = {
        "family beta=0": fam.to_sigma(tree, beta0),
        "family beta=1/4": fam.to_sigma(tree, beta14),
        "CFR+ (OpenSpiel, 5000 iterations)": cfr_plus,
    }
    subjects = {
        "uniform random": tree.uniform(),
        "always bet or call": scripted(tree, lambda card, facing: 1.0),
        "passive (never bet, call only with the Ace)": scripted(
            tree, lambda card, facing: float(facing and card == 3)
        ),
        "equilibrium strategy from another member (c11=1/2, beta=1/4)": fam.to_sigma(tree, table4),
    }
    ref_info = {}
    for rname, ref in references.items():
        g = tree.gains(ref)
        ref_info[rname] = {"gains": g["gains"].tolist(), "ev": g["ev"].tolist()}
    rows = []
    for sname, subj in subjects.items():
        for seat in range(3):
            for rname, ref in references.items():
                prof = splice(tree, ref, seat, subj)
                reach, chance = tree.reach(prof)
                ev = tree.values(prof)[0]
                gains = tree.gains(prof)["gains"]
                opp = [j for j in range(3) if j != seat]
                j_star = max(opp, key=lambda j: gains[j])
                _, choice = tree.best_response_value(j_star, tree.opponent_weights(reach, chance, j_star))
                exploited = splice(tree, prof, j_star, tree.pure_from_choice(choice, j_star))
                ev_x = tree.values(exploited)[0]
                bystander = [j for j in opp if j != j_star][0]
                # Punishment: the opponent deviation that minimises the subject's value.
                punish = {}
                for j in opp:
                    v, _ = tree.best_response_value(
                        j, tree.opponent_weights(reach, chance, j), utility=-tree.terminal_returns[:, seat]
                    )
                    punish[SEATS[j]] = float(ev[seat] + v)
                rows.append(
                    {
                        "subject": sname,
                        "seat": SEATS[seat],
                        "reference": rname,
                        "subject_ev": float(ev[seat]),
                        "reference_ev": ref_info[rname]["ev"][seat],
                        "loss_vs_reference": ref_info[rname]["ev"][seat] - float(ev[seat]),
                        "seat_regret": float(gains[seat]),
                        "opponent_gains": {SEATS[j]: float(gains[j]) for j in opp},
                        "max_opponent_gain": float(gains[j_star]),
                        "max_gain_opponent": SEATS[j_star],
                        "paid_by_subject": float(ev[seat] - ev_x[seat]),
                        "paid_by_bystander": float(ev[bystander] - ev_x[bystander]),
                        "bystander": SEATS[bystander],
                        "punishment_loss": punish,
                        "max_punishment_loss": max(punish.values()),
                    }
                )
    self_play = {}
    for sname, subj in subjects.items():
        g = tree.gains(subj)
        self_play[sname] = {"gains": g["gains"].tolist(), "ev": g["ev"].tolist()}
    out = {
        "meta": {
            "game": "kuhn_poker(players=3)",
            "generated_by": "research/multiway/seat_metric.py",
            "units": "chips per hand (ante 1)",
            "note": "best responses break ties by the first legal action (pass), so 'paid_by' "
            "splits describe one best response; others may split the gain differently",
        },
        "references": ref_info,
        "rows": rows,
        "self_play": self_play,
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "kuhn3_seat_metric.json").write_text(json.dumps(out, indent=1))
    print("written", len(rows), "rows")
    for r in rows:
        if r["subject"].startswith(("uniform", "equilibrium")):
            print(
                f"{r['subject'][:22]:22s} {r['seat']} {r['reference'][:16]:16s} ev {r['subject_ev']:+.4f} "
                f"loss {r['loss_vs_reference']:+.4f} regret {r['seat_regret']:.4f} "
                f"maxopp {r['max_opponent_gain']:.4f} ({r['max_gain_opponent']}) "
                f"paid subj {r['paid_by_subject']:+.4f} byst {r['paid_by_bystander']:+.4f} "
                f"punish {r['max_punishment_loss']:.4f}"
            )


if __name__ == "__main__":
    main()
