"""Run a subject on a game in direct mode and write a results directory under runs/.

Phase 1 supports mock subjects only (scripted policies answering through the text
interface), so no API budget is spent.

Examples:
    uv run python scripts/run_benchmark.py --agent uniform --samples 200
    uv run python scripts/run_benchmark.py --agent cfr --client distribution
    uv run python scripts/run_benchmark.py --agent cfr --samples 100 --garbage-rate 0.1 --format-noise
    uv run python scripts/run_benchmark.py --agent uniform --samples 100 --dry-run
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from strategybench.adapters.cache import CallCache
from strategybench.adapters.mock import MockDistributionClient, MockTextClient, policy_lookup
from strategybench.analysis.metrics import solve_equilibrium
from strategybench.baselines.scripted import (
    first_action_policy,
    last_action_policy,
    mix_policies,
    uniform_policy,
)
from strategybench.estimation.direct import BudgetExceeded, dry_run_calls
from strategybench.games import get_game_spec
from strategybench.prompts import DEFAULT_TEMPLATES
from strategybench.runner import RunConfig, run_direct

AGENTS = ["uniform", "first-action", "last-action", "cfr", "cfr-noisy"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", default="kuhn")
    ap.add_argument("--agent", choices=AGENTS, default="uniform")
    ap.add_argument("--client", choices=["text", "distribution"], default="text")
    ap.add_argument("--samples", type=int, default=50, help="samples per infostate (text clients)")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--bootstrap", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--min-samples", type=int, default=1, help="fill rule threshold")
    ap.add_argument("--garbage-rate", type=float, default=0.0)
    ap.add_argument("--illegal-rate", type=float, default=0.0)
    ap.add_argument("--format-noise", action="store_true")
    ap.add_argument("--max-calls", type=int, default=None, help="hard cap on live calls")
    ap.add_argument("--cache", default="runs/cache.sqlite")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    spec = get_game_spec(args.game)
    template = DEFAULT_TEMPLATES[args.game]

    if args.dry_run:
        n_info, lo, hi = dry_run_calls(spec, args.samples, args.retries)
        print(f"{spec.name}: {n_info} infostates x {args.samples} samples")
        print(f"calls: {lo} (no retries) to {hi} (every sample retried {args.retries}x)")
        print("estimated cost: $0.00 (mock subject)")
        return 0

    game = spec.load()
    eq = solve_equilibrium(spec.load_string)
    policies = {
        "uniform": lambda: uniform_policy(game),
        "first-action": lambda: first_action_policy(game),
        "last-action": lambda: last_action_policy(game),
        "cfr": lambda: eq.policy,
        "cfr-noisy": lambda: mix_policies(game, eq.policy, uniform_policy(game), 0.8),
    }
    lookup = policy_lookup(spec, template, policies[args.agent]())
    if args.client == "text":
        client = MockTextClient(
            args.agent,
            lookup,
            seed=args.seed,
            garbage_rate=args.garbage_rate,
            vocabulary=spec.vocabulary(),
            illegal_rate=args.illegal_rate,
            format_noise=args.format_noise,
        )
    else:
        client = MockDistributionClient(args.agent, lookup)

    config = RunConfig(
        n_samples=args.samples,
        max_retries=args.retries,
        n_boot=args.bootstrap,
        seed=args.seed,
        min_samples=args.min_samples,
        max_calls=args.max_calls,
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out) / f"{stamp}_{spec.name}_{client.model_id}_{args.client}"
    cache = None if args.no_cache else CallCache(args.cache)
    try:
        result = run_direct(spec, template, client, config, out_dir, cache, eq)
    except BudgetExceeded as e:
        print(f"ABORTED: {e}", file=sys.stderr)
        return 2
    finally:
        if cache:
            cache.close()

    m, ci, rel = result["metrics"], result["ci95"], result["reliability"]

    def fmt(name: str, value: float) -> str:
        lo_hi = ci.get(name)
        return f"{value:.4f}" + (f"  [{lo_hi[0]:.4f}, {lo_hi[1]:.4f}]" if lo_hi else "")

    unit = result["payoff_unit"]
    print(f"{spec.name} | {client.model_id} ({result['subject_kind']}) | prompt {result['prompt_version']}")
    print(f"  M1 exploitability ({unit}/hand):   {fmt('exploitability', m['exploitability_norm'])}")
    if result["bias"]:
        b = result["bias"]
        print(
            f"     bootstrap bias {b['exploitability_bootstrap_bias'] / spec.unit_size:+.4f} -> "
            f"bias-corrected {b['exploitability_bias_corrected'] / spec.unit_size:.4f}"
        )
    for seat in range(2):
        print(f"  M2 BR gain, subject seat {seat + 1}:    {fmt(f'br_gain_{seat}', m['br_gain_norm'][seat])}")
    for seat in range(2):
        print(
            f"  M3 loss vs eq, subject seat {seat + 1}: {fmt(f'h2h_loss_{seat}', m['h2h_loss_norm'][seat])}"
        )
    print(
        f"  M4 parse-fail {rel['parse_failure_rate']:.3f} | illegal {rel['illegal_action_rate']:.3f} | "
        f"retry {rel['retry_rate']:.3f} | failed samples {rel['sample_failure_rate']:.3f}"
    )
    print(
        f"     coverage {result['coverage']} | filled {result['filled']['count']}/{result['filled']['of']} | "
        f"live calls {rel['live_calls']}, cache hits {rel['cache_hits']}"
    )
    print(f"  equilibrium seat values: {[round(v, 5) for v in result['equilibrium']['values']]}")
    print(f"  results: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
