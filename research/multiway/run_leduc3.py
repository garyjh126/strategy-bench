"""Time-boxed three-player Leduc poker run for docs/research/multiway.md (stretch goal).

Three-player Leduc (OpenSpiel `leduc_poker(players=3)`, 8-card deck, two betting rounds)
has 25,800 infostates, so it uses OpenSpiel's C++ solvers and best responses directly:
external-sampling MCCFR with two seeds and a short CFR+ run, with per-player best-response
gains and seat values at a few checkpoints. Writes results/leduc3.json.

    uv run python research/multiway/run_leduc3.py          # about 8 minutes
    uv run python research/multiway/run_leduc3.py --quick  # smoke test
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pyspiel

RESULTS = Path(__file__).parent / "results"
GAME = "leduc_poker(players=3)"


def evaluate(game, pol, use_state_policy: bool) -> dict:
    root = game.new_initial_state()
    t0 = time.time()
    ev = pyspiel.expected_returns(root, pol, -1, not use_state_policy)
    gains = []
    for p in range(game.num_players()):
        br = pyspiel.TabularBestResponse(game, p, pol)
        gains.append(br.value_from_state(root) - ev[p])
    return {
        "ev": list(ev),
        "gains": gains,
        "nash_conv": sum(gains),
        "eval_seconds": round(time.time() - t0, 1),
    }


def run_mccfr(game, seed: int, checkpoints: list[int]) -> dict:
    solver = pyspiel.ExternalSamplingMCCFRSolver(game, seed=seed)
    cps, t0, done = [], time.time(), 0
    for target in checkpoints:
        for _ in range(target - done):
            solver.run_iteration()
        done = target
        train = round(time.time() - t0, 1)
        cps.append(
            {
                "iteration": target,
                "train_seconds_so_far": train,
                **evaluate(game, solver.average_policy(), True),
            }
        )
        print(f"MCCFR seed {seed} @ {target}: gains {[round(g, 4) for g in cps[-1]['gains']]}", flush=True)
        t0 = time.time() - train
    return {
        "label": f"OpenSpiel ES-MCCFR, seed {seed}",
        "implementation": "OpenSpiel pyspiel.ExternalSamplingMCCFRSolver (simple averaging)",
        "checkpoints": cps,
    }


def run_cfr_plus(game, checkpoints: list[int]) -> dict:
    solver = pyspiel.CFRPlusSolver(game)
    cps, t0, done = [], time.time(), 0
    for target in checkpoints:
        for _ in range(target - done):
            solver.evaluate_and_update_policy()
        done = target
        train = round(time.time() - t0, 1)
        cps.append(
            {
                "iteration": target,
                "train_seconds_so_far": train,
                **evaluate(game, solver.tabular_average_policy(), False),
            }
        )
        print(f"CFR+ @ {target}: gains {[round(g, 4) for g in cps[-1]['gains']]}", flush=True)
        t0 = time.time() - train
    return {
        "label": "OpenSpiel CFR+",
        "implementation": "OpenSpiel pyspiel.CFRPlusSolver",
        "checkpoints": cps,
        # The solver's table has one entry per infostate.
        "num_infosets": len(solver.tabular_average_policy().policy_table()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    game = pyspiel.load_game(GAME)
    if args.quick:
        mccfr_cps, cfr_cps, seeds = [1000], [2], [0]
    else:
        mccfr_cps, cfr_cps, seeds = [10**4, 10**5, 10**6], [10, 30], [0, 1]
    t0 = time.time()
    runs = [run_mccfr(game, s, mccfr_cps) for s in seeds]
    runs.append(run_cfr_plus(game, cfr_cps))
    out = {
        "meta": {
            "game": GAME,
            "generated_by": "research/multiway/run_leduc3.py" + (" --quick" if args.quick else ""),
            "units": "chips per hand (ante 1, raises 2 then 4)",
            "total_seconds": round(time.time() - t0, 1),
        },
        "runs": runs,
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"leduc3{'_quick' if args.quick else ''}.json").write_text(json.dumps(out, indent=1))
    print("written")


if __name__ == "__main__":
    main()
