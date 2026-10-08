"""Measure bootstrap interval coverage for exploitability by simulation (free; no subject calls).

For scripted strategies with a known exploitability, draw many independent datasets of N
samples per infostate, estimate the strategy and its exploitability (M1) exactly as a run
does, build bootstrap intervals for each dataset, and count how often each kind of interval
contains the true value:

* percentile: the 2.5% and 97.5% quantiles of the bootstrap replicates (used by runs so far)
* basic: the percentile interval reflected about the estimate, [2x - q97.5, 2x - q2.5],
  clipped at 0; it is centred on the bias-corrected estimate 2x - mean(replicates)

Sampling goes straight to action counts (the text interface is validated separately).

Examples:
    uv run python scripts/ci_coverage.py --game kuhn
    uv run python scripts/ci_coverage.py --game leduc --datasets 60 --bootstrap 100
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from open_spiel.python.algorithms import exploitability

from strategybench.analysis.bootstrap import percentile_ci
from strategybench.analysis.metrics import solve_equilibrium
from strategybench.baselines.scripted import mix_policies, uniform_policy
from strategybench.estimation.infostates import enumerate_infostates
from strategybench.estimation.strategy import resample_counts, strategy_from_counts
from strategybench.games import get_game_spec


def draw_counts(infos, policy, n: int, rng: np.random.Generator) -> dict[str, dict[int, int]]:
    counts = {}
    for info in infos:
        probs = policy.action_probabilities(info.state)
        actions = list(info.legal_actions)
        p = np.array([probs.get(a, 0.0) for a in actions])
        draws = rng.multinomial(n, p / p.sum())
        counts[info.key] = {a: int(d) for a, d in zip(actions, draws, strict=True) if d}
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", default="kuhn")
    ap.add_argument("--samples", type=int, default=200, help="samples per infostate (N)")
    ap.add_argument("--datasets", type=int, default=200, help="independent datasets per strategy")
    ap.add_argument("--bootstrap", type=int, default=200, help="bootstrap replicates per dataset")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--eq-cache", default="runs/equilibria")
    ap.add_argument("--out", default=None, help="results JSON (default runs/ci_coverage_<game>.json)")
    args = ap.parse_args()

    spec = get_game_spec(args.game)
    game = spec.load()
    infos = enumerate_infostates(game)
    eq = solve_equilibrium(spec.load_string, 2000, args.eq_cache)
    strategies = {
        "uniform": uniform_policy(game),
        "equilibrium": eq.policy,
        "80% equilibrium, 20% uniform": mix_policies(game, eq.policy, uniform_policy(game), 0.8),
    }

    def m1(counts):
        return float(exploitability.exploitability(game, strategy_from_counts(game, infos, counts).policy))

    rows = []
    for name, policy in strategies.items():
        start = time.time()
        truth = float(exploitability.exploitability(game, policy))
        est, corrected, hit_pct, hit_basic, outside = [], [], 0, 0, 0
        for d in range(args.datasets):
            rng = np.random.default_rng([args.seed, d])
            counts = draw_counts(infos, policy, args.samples, rng)
            x = m1(counts)
            reps = np.array([m1(resample_counts(counts, rng)) for _ in range(args.bootstrap)])
            lo, hi = percentile_ci(reps)
            basic = (max(0.0, 2 * x - hi), max(0.0, 2 * x - lo))
            est.append(x)
            corrected.append(max(0.0, 2 * x - float(reps.mean())))
            hit_pct += lo <= truth <= hi
            hit_basic += basic[0] <= truth <= basic[1]
            outside += not lo <= x <= hi
        n = args.datasets
        row = {
            "strategy": name,
            "true_m1": truth,
            "mean_estimate": float(np.mean(est)),
            "sd_estimate": float(np.std(est, ddof=1)),
            "mean_bias_corrected": float(np.mean(corrected)),
            "coverage_percentile": hit_pct / n,
            "coverage_basic": hit_basic / n,
            "percentile_excludes_estimate": outside / n,
        }
        rows.append(row)
        print(
            f"{name:30s} true {truth:.4f} | estimate {row['mean_estimate']:.4f} "
            f"(sd {row['sd_estimate']:.4f}) | bias-corrected {row['mean_bias_corrected']:.4f} | "
            f"coverage: percentile {row['coverage_percentile']:.0%}, basic {row['coverage_basic']:.0%} | "
            f"percentile interval excludes the estimate {row['percentile_excludes_estimate']:.0%} "
            f"[{time.time() - start:.0f}s]",
            flush=True,
        )

    out = Path(args.out or f"runs/ci_coverage_{spec.name}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    settings = {k: getattr(args, k) for k in ("game", "samples", "datasets", "bootstrap", "seed")}
    out.write_text(json.dumps({"settings": settings, "rows": rows}, indent=2))
    print(f"results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
