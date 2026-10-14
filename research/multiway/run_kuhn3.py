"""Three-player Kuhn poker experiments for docs/research/multiway.md.

Runs CFR, CFR+, linear CFR, fictitious play (our full-width solvers, from uniform and from
random initial strategies), OpenSpiel's C++ CFR / CFR+ and external-sampling MCCFR with
several seeds and both averaging modes; then checks the Szafron-Gibson-Sturtevant
equilibrium family and what happens at its unreached infostates. Writes
results/kuhn3_solvers.json, results/kuhn3_mccfr.json and results/kuhn3_family.json.
Everything is deterministic given the seeds.

    uv run python research/multiway/run_kuhn3.py                 # everything, about 20 minutes
    uv run python research/multiway/run_kuhn3.py --part mccfr    # one part: family, solvers, mccfr
    uv run python research/multiway/run_kuhn3.py --quick         # smoke test
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import kuhn3_family as fam
import numpy as np
import pyspiel
from open_spiel.python import policy as policy_lib
from tabular import GameTree, run_cfr, run_fictitious_play

RESULTS = Path(__file__).parent / "results"
GAME = "kuhn_poker(players=3)"
KEY_PARAMS = ["b11", "b21", "b23", "b32", "b33", "b41", "c11", "c21", "c33", "c34", "a33"]


def describe(tree: GameTree, sigma: np.ndarray) -> dict:
    """Gains, seat values and family diagnostics of a final profile."""
    g = tree.gains(sigma)
    p = fam.from_sigma(tree, sigma)
    dist = fam.distance(p)
    return {
        "gains": g["gains"].tolist(),
        "max_gain": float(g["gains"].max()),
        "nash_conv": float(g["gains"].sum()),
        "ev": g["ev"].tolist(),
        "beta": fam.beta(p),
        "family_predicted_ev": fam.predicted_ev(p),
        "closest_subfamily": dist["closest"],
        "on_path_violation": dist["on_path"],
        "worst_on_path_constraint": dist["worst_on_path"],
        "off_path_violation": dist["off_path"],
        "violation_per_subfamily": dist["per_subfamily"],
        "key_params": {k: p[k] for k in KEY_PARAMS},
        "params": p,
    }


def ours(tree, label, algo, variant, init_seed, iterations, checkpoints, alternating=True):
    init = None if init_seed is None else tree.random_strategy(np.random.default_rng(init_seed))
    t0 = time.time()
    if algo == "cfr":
        res = run_cfr(tree, iterations, checkpoints, variant=variant, init=init, alternating=alternating)
    else:
        res = run_fictitious_play(tree, iterations, checkpoints, init=init)
    return {
        "label": label,
        "implementation": "ours (research/multiway/tabular.py)",
        "algorithm": algo if algo == "fp" else variant,
        "updates": "simultaneous" if (algo == "fp" or not alternating) else "alternating",
        "init": "uniform" if init_seed is None else f"random (seed {init_seed})",
        "iterations": iterations,
        "checkpoints": res["checkpoints"],
        "final": describe(tree, res["average"]),
        "seconds": round(time.time() - t0, 1),
    }


def openspiel_cfr(tree, label, solver_cls, iterations, checkpoints):
    solver = solver_cls(tree.game)
    cps = []
    t0 = time.time()
    for t in range(1, iterations + 1):
        solver.evaluate_and_update_policy()
        if t in checkpoints:
            avg = policy_lib.pyspiel_policy_to_python_policy(tree.game, solver.tabular_average_policy())
            g = tree.gains(tree.from_openspiel(avg))
            cps.append({"iteration": t, "gains": g["gains"].tolist(), "ev": g["ev"].tolist()})
    avg = policy_lib.pyspiel_policy_to_python_policy(tree.game, solver.tabular_average_policy())
    return {
        "label": label,
        "implementation": f"OpenSpiel pyspiel.{solver_cls.__name__}",
        "algorithm": "cfr" if solver_cls is pyspiel.CFRSolver else "cfr+",
        "updates": "alternating",
        "init": "uniform",
        "iterations": iterations,
        "checkpoints": cps,
        "final": describe(tree, tree.from_openspiel(avg)),
        "seconds": round(time.time() - t0, 1),
    }


def openspiel_mccfr(tree, label, seed, iterations, checkpoints, full=False):
    avg = pyspiel.MCCFRAverageType.FULL if full else pyspiel.MCCFRAverageType.SIMPLE
    solver = pyspiel.ExternalSamplingMCCFRSolver(tree.game, seed=seed, avg_type=avg)
    cps = []
    t0 = time.time()
    for t in range(1, iterations + 1):
        solver.run_iteration()
        if t in checkpoints:
            g = tree.gains(tree.from_openspiel(solver.average_policy()))
            cps.append({"iteration": t, "gains": g["gains"].tolist(), "ev": g["ev"].tolist()})
    return {
        "label": label,
        "implementation": "OpenSpiel pyspiel.ExternalSamplingMCCFRSolver, "
        + ("full" if full else "simple")
        + " averaging",
        "algorithm": "es-mccfr",
        "updates": "alternating (one traversal per player)",
        "init": f"uniform, sampling seed {seed}",
        "iterations": iterations,
        "checkpoints": cps,
        "final": describe(tree, tree.from_openspiel(solver.average_policy())),
        "seconds": round(time.time() - t0, 1),
    }


def solver_runs(tree, quick: bool) -> list[dict]:
    full_t = 2000 if quick else 20000
    cps = [c for c in (10, 30, 100, 300, 1000, 3000, 10000, 20000) if c <= full_t]
    seeds = [1, 2] if quick else list(range(1, 11))
    runs = []
    for variant, name in (("cfr", "CFR"), ("cfr+", "CFR+"), ("linear", "Linear CFR")):
        for s in [None, *seeds]:
            lab = f"{name}, {'uniform' if s is None else f'random init {s}'}"
            runs.append(ours(tree, lab, "cfr", variant, s, full_t, cps))
            print(f"{lab}: max gain {runs[-1]['final']['max_gain']:.2e}", flush=True)
    for s in [None, *seeds[:5]]:
        lab = f"CFR simultaneous, {'uniform' if s is None else f'random init {s}'}"
        runs.append(ours(tree, lab, "cfr", "cfr", s, full_t, cps, alternating=False))
        print(f"{lab}: max gain {runs[-1]['final']['max_gain']:.2e}", flush=True)
    for s in [None, *seeds]:
        lab = f"Fictitious play, {'uniform' if s is None else f'random init {s}'}"
        runs.append(ours(tree, lab, "fp", None, s, full_t, cps))
        print(f"{lab}: max gain {runs[-1]['final']['max_gain']:.2e}", flush=True)
    runs.append(openspiel_cfr(tree, "OpenSpiel CFR", pyspiel.CFRSolver, full_t, cps))
    runs.append(openspiel_cfr(tree, "OpenSpiel CFR+", pyspiel.CFRPlusSolver, full_t, cps))
    return runs


def mccfr_runs(tree, quick: bool) -> list[dict]:
    """External-sampling MCCFR with OpenSpiel's two averaging modes.

    "Simple" averaging (the default, as in Pluribus) updates player i+1's average on player
    i's pass; OpenSpiel's source notes it is biased with more than two players. "Full"
    averaging adds an unbiased full-tree averaging pass, about 20 times slower per iteration
    here, so it gets fewer seeds and iterations."""
    simple_t, full_t = (10**4, 10**4) if quick else (10**6, 3 * 10**5)
    cps = (10**4, 10**5, 3 * 10**5, 10**6)
    runs = []
    for s in range(2 if quick else 10):
        lab = f"OpenSpiel ES-MCCFR (simple averaging), seed {s}"
        runs.append(openspiel_mccfr(tree, lab, s, simple_t, [c for c in cps if c <= simple_t]))
        print(f"{lab}: max gain {runs[-1]['final']['max_gain']:.2e}", flush=True)
    for s in range(2 if quick else 5):
        lab = f"OpenSpiel ES-MCCFR (full averaging), seed {s}"
        runs.append(openspiel_mccfr(tree, lab, s, full_t, [c for c in cps if c <= full_t], full=True))
        print(f"{lab}: max gain {runs[-1]['final']['max_gain']:.2e}", flush=True)
    return runs


def infoset_reach(tree, sigma) -> dict:
    """Probability of reaching each parameter's infostate under the profile."""
    reach, chance = tree.reach(sigma)
    node_reach = chance * reach.prod(axis=1)
    dec = tree.node_player >= 0
    per_info = np.bincount(tree.node_infoset[dec], weights=node_reach[dec], minlength=tree.num_infosets)
    return {name: float(per_info[tree.infoset_index[fam.key(name)]]) for name in fam.PARAMS}


def offpath_intervals(tree) -> dict:
    """For representative members, the range of each unreached parameter (others fixed)
    that keeps the profile an exact equilibrium. Every other player's gain is convex in an
    unreached parameter and the owner's gain does not depend on it, so the allowed set is
    an interval; it is located on a grid of 201 points (resolution 0.005)."""
    members = {
        "c11=0, beta=0 (b32=0, c33=1/2)": fam.member(
            "c11=0", {"b11": 0.0, "b21": 0.0, "b32": 0.0, "c33": 0.5}
        ),
        "c11=0, beta=1/8 (b11=b21=1/8, b32=1/4, c33=3/8)": fam.member(
            "c11=0", {"b11": 0.125, "b21": 0.125, "b32": 0.25, "c33": 0.375}
        ),
        "c11=0, beta=1/4 (b32=15/16, c33=0)": fam.member(
            "c11=0", {"b11": 0.25, "b21": 0.25, "b32": 15 / 16, "c33": 0.0}
        ),
        "c11=1/2, beta=1/8 (b21=1/16, b23=0, b32=1/4, c33=3/8)": fam.member(
            "c11=1/2", {"b11": 0.125, "b21": 0.0625, "b23": 0.0, "b32": 0.25, "c33": 0.375}
        ),
    }
    grid = np.linspace(0.0, 1.0, 201)
    out = {}
    for label, p in members.items():
        sigma = fam.to_sigma(tree, p)
        assert tree.gains(sigma)["gains"].max() < 1e-12
        rows = {}
        for name, r in infoset_reach(tree, sigma).items():
            if r > 0:
                continue
            ok = []
            for x in grid:
                q = dict(p)
                q[name] = float(x)
                ok.append(tree.gains(fam.to_sigma(tree, q))["gains"].max() <= 1e-12)
            ok = np.array(ok)
            rows[name] = {
                "family_value": p[name],
                "allowed_min": float(grid[ok].min()),
                "allowed_max": float(grid[ok].max()),
                "contiguous": bool(ok[ok.argmax() : len(ok) - ok[::-1].argmax()].all()),
            }
        out[label] = rows
    return out


def family_checks(tree, quick: bool) -> dict:
    rng = np.random.default_rng(2013)
    n = 50 if quick else 400
    out = {"members_per_subfamily": n, "subfamilies": {}, "off_path": {}}
    for sub in fam.SUBFAMILIES:
        gains, ev_err, prose = [], [], []
        evs = []
        off = {}
        for _ in range(n):
            free = fam.sample_free(sub, rng)
            p = fam.member(sub, free)
            sigma = fam.to_sigma(tree, p)
            g = tree.gains(sigma)
            gains.append(float(g["gains"].max()))
            ev_err.append(float(np.abs(g["ev"] - fam.predicted_ev(p)).max()))
            evs.append(g["ev"].tolist())
            if sub == "c11=1/2":
                prose.append(
                    float(tree.gains(fam.to_sigma(tree, fam.member(sub, free, True)))["gains"].max())
                )
            # Unreached infostates: push each parameter to 0 and to 1, one at a time.
            for name, r in infoset_reach(tree, sigma).items():
                if r > 0:
                    continue
                rec = off.setdefault(name, {"unreached": 0, "breaks": 0, "max_gain": 0.0})
                rec["unreached"] += 1
                worst = 0.0
                for v in (0.0, 1.0):
                    q = dict(p)
                    q[name] = v
                    worst = max(worst, float(tree.gains(fam.to_sigma(tree, q))["gains"].max()))
                if worst > 1e-9:
                    rec["breaks"] += 1
                rec["max_gain"] = max(rec["max_gain"], worst)
        evs = np.array(evs)
        out["subfamilies"][sub] = {
            "max_gain": max(gains),
            "max_ev_minus_formula": max(ev_err),
            "ev_min": evs.min(axis=0).tolist(),
            "ev_max": evs.max(axis=0).tolist(),
            "prose_b33_max_gain": max(prose) if prose else None,
        }
        out["off_path"][sub] = off
    # The two ends of the utility range (beta = 0 and beta = 1/4) and the paper's
    # "robust" choices (Section 6): P2 with b11 = b21, P3 with c11 = 0.
    lo = fam.member("c11=0", {"b11": 0.0, "b21": 0.0, "b32": 0.0, "c33": 0.5})
    hi = fam.member("c11=0", {"b11": 0.25, "b21": 0.25, "b32": 15 / 16, "c33": 0.0})
    ends = {}
    for name, p in (("beta=0", lo), ("beta=1/4", hi)):
        g = tree.gains(fam.to_sigma(tree, p))
        ends[name] = {"params": p, "gains": g["gains"].tolist(), "ev": g["ev"].tolist()}
    out["extremes"] = ends
    out["ev_range_formula"] = {
        "P1": [-fam.KAPPA * 0.75, -fam.KAPPA * 0.5],
        "P2": [-fam.KAPPA * 0.5, -fam.KAPPA * 0.5],
        "P3": [fam.KAPPA, fam.KAPPA * 1.25],
    }
    # Ganzfried (arXiv:2509.25618, Section 4) reports an exact equilibrium with the beta = 0
    # payoffs that matches the family except at two unreached infostates: player 1 folds the
    # King facing check-bet-fold (a33 = 0), and player 3 calls half the time with the King.
    # The text names the second parameter "c32" (situation 2, facing check-bet) but describes
    # it as "facing bet-fold" (situation 3, c33). Test both readings on beta = 0 members, for
    # which c33 must equal 1/2 - b32.
    variants = {
        "a33=0 only": {"a33": 0.0},
        "a33=0, c33=1/2 (as described: King facing bet-fold)": {"a33": 0.0, "c33": 0.5},
        "a33=0, c32=1/2 (as labelled: King facing check-bet)": {"a33": 0.0, "c32": 0.5},
        "c32=1/2 only": {"c32": 0.5},
        "a33=0, c32=1/4": {"a33": 0.0, "c32": 0.25},
        "a33=0, c32=1": {"a33": 0.0, "c32": 1.0},
    }
    rows = []
    for b32 in (0.0, 0.25, 0.5):
        base = fam.member("c11=0", {"b11": 0.0, "b21": 0.0, "b32": b32, "c33": 0.5 - b32})
        reach = infoset_reach(tree, fam.to_sigma(tree, base))
        for label, change in variants.items():
            q = dict(base)
            q.update(change)
            g = tree.gains(fam.to_sigma(tree, q))
            rows.append(
                {
                    "base": {"b32": b32, "c33": 0.5 - b32},
                    "variant": label,
                    "gains": g["gains"].tolist(),
                    "ev": g["ev"].tolist(),
                    "reach": {k: reach[k] for k in ("a33", "c32", "c33")},
                }
            )
    out["ganzfried_offpath_variants"] = rows
    out["offpath_intervals"] = offpath_intervals(tree)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--part", choices=["all", "family", "solvers", "mccfr"], default="all")
    args = ap.parse_args()
    RESULTS.mkdir(exist_ok=True)
    tree = GameTree(pyspiel.load_game(GAME))
    meta = {
        "game": GAME,
        "openspiel_version": pyspiel.__version__ if hasattr(pyspiel, "__version__") else "unknown",
        "generated_by": "research/multiway/run_kuhn3.py" + (" --quick" if args.quick else ""),
        "units": "chips per hand (ante 1)",
        "num_infosets": tree.num_infosets,
        "infosets_per_player": np.bincount(tree.infoset_player_arr).tolist(),
        "num_nodes": tree.num_nodes,
    }
    suffix = "_quick" if args.quick else ""
    if args.part in ("all", "family"):
        fam_out = {"meta": meta, **family_checks(tree, args.quick)}
        (RESULTS / f"kuhn3_family{suffix}.json").write_text(json.dumps(fam_out, indent=1))
        print("family checks written", flush=True)
    if args.part in ("all", "solvers"):
        runs = solver_runs(tree, args.quick)
        out = {"meta": meta, "runs": runs}
        (RESULTS / f"kuhn3_solvers{suffix}.json").write_text(json.dumps(out, indent=1))
        print("solver runs written")
    if args.part in ("all", "mccfr"):
        out = {"meta": meta, "runs": mccfr_runs(tree, args.quick)}
        (RESULTS / f"kuhn3_mccfr{suffix}.json").write_text(json.dumps(out, indent=1))
        print("MCCFR runs written")


if __name__ == "__main__":
    main()
