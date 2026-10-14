"""Run a subject on a game in direct mode and write a results directory under runs/.

Subjects are either mock agents (--agent, scripted policies answering through the text
interface, free) or real models defined in models.yaml (--model). API keys are read from
.env. Paid models require --max-cost; always run with --dry-run first.

Examples:
    uv run python scripts/run_benchmark.py --model deepseek-flash --samples 200 --dry-run
    uv run python scripts/run_benchmark.py --model deepseek-flash --samples 200 --max-cost 1.00
    uv run python scripts/run_benchmark.py --agent uniform --samples 200
    uv run python scripts/run_benchmark.py --game leduc --agent cfr-noisy --mode both --hands 20000
    uv run python scripts/run_benchmark.py --agent cfr --client distribution
    uv run python scripts/run_benchmark.py --agent cfr --samples 100 --garbage-rate 0.1 --format-noise
    uv run python scripts/run_benchmark.py --agent uniform --samples 100 --dry-run
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from strategybench.adapters.cache import CallCache
from strategybench.adapters.mock import MockDistributionClient, MockTextClient, policy_lookup
from strategybench.adapters.providers import QuotaExhausted
from strategybench.adapters.registry import build_client, load_models
from strategybench.analysis.metrics import solve_equilibrium
from strategybench.baselines.scripted import (
    first_action_policy,
    last_action_policy,
    mix_policies,
    uniform_policy,
)
from strategybench.estimation.direct import BudgetExceeded, dry_run_calls, mean_prompt_tokens
from strategybench.estimation.play import expected_subject_decisions
from strategybench.games import get_game_spec
from strategybench.prompts import get_template
from strategybench.runner import RunConfig, opponent_policy, run_direct, run_play

AGENTS = ["uniform", "first-action", "last-action", "cfr", "cfr-noisy"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--game", default="kuhn")
    who = ap.add_mutually_exclusive_group()
    who.add_argument("--agent", choices=AGENTS, help="mock subject")
    who.add_argument("--model", help="real subject: a name from models.yaml")
    ap.add_argument("--models-file", default="models.yaml")
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
    ap.add_argument("--max-cost", type=float, default=None, help="hard cap on estimated USD spend")
    ap.add_argument("--concurrency", type=int, default=None, help="parallel calls (default from models.yaml)")
    ap.add_argument("--cache", default="runs/cache.sqlite")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--out", default="runs")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prompt", default=None, help="prompt version, e.g. kuhn-v1-para or kuhn-v1+shuffled")
    ap.add_argument("--mode", choices=["direct", "play", "both"], default="direct")
    ap.add_argument("--hands", type=int, default=10000, help="hands in play mode (seats alternate)")
    ap.add_argument("--opponent", choices=["equilibrium", "uniform"], default="equilibrium")
    ap.add_argument("--eq-cache", default="runs/equilibria", help="directory for solved equilibria")
    args = ap.parse_args()

    spec = get_game_spec(args.game)
    template = get_template(args.game, args.prompt)
    model_spec = None
    if args.model:
        models = load_models(args.models_file)
        if args.model not in models:
            ap.error(f"unknown model {args.model!r}; models.yaml has {sorted(models)}")
        model_spec = models[args.model]
    elif args.agent is None:
        args.agent = "uniform"

    eq = solve_equilibrium(spec.load_string, 2000, args.eq_cache)

    if args.dry_run:
        n_info, n_forced, lo, hi = dry_run_calls(spec, args.samples, args.retries)
        if args.mode == "play":
            lo = hi = 0
        else:
            skipped = f" ({n_forced} forced infostates are not queried)" if n_forced else ""
            print(f"{spec.name}: {n_info} infostates x {args.samples} samples{skipped}")
        if args.mode != "direct":
            game = spec.load()
            per_hand = expected_subject_decisions(
                game, uniform_policy(game), opponent_policy(args.opponent, spec, eq)
            )
            play_calls = round(per_hand * args.hands)
            print(
                f"play: {args.hands} {spec.episode}s x ~{per_hand:.2f} subject decisions per {spec.episode} "
                "(under uniform play)"
            )
            lo, hi = lo + play_calls, hi + play_calls * (args.retries + 1)
        print(f"calls: {lo} (no retries) to {hi} (every sample retried {args.retries}x)")
        if model_spec is None:
            print("estimated cost: $0.00 (mock subject)")
        else:
            tokens_in = mean_prompt_tokens(spec, template)
            per_call = model_spec.cost(round(tokens_in), model_spec.est_output_tokens)
            print(
                f"model {model_spec.name} ({model_spec.provider}/{model_spec.model}), "
                f"params {model_spec.params}"
            )
            print(f"~{tokens_in:.0f} input + ~{model_spec.est_output_tokens} output tokens per call")
            print(
                f"estimated cost: ${per_call * lo:.4f} to ${per_call * hi:.4f}  [{model_spec.price_source}]"
            )
        return 0

    if model_spec is not None:
        if (model_spec.price_input or model_spec.price_output) and args.max_cost is None:
            ap.error(
                f"{model_spec.name} is a paid model: pass --max-cost (run --dry-run first for an estimate)"
            )
        load_dotenv()
        client = build_client(model_spec)
        cost_fn = model_spec.cost
        concurrency = args.concurrency or model_spec.concurrency
        client_kind = "text"
    else:
        game = spec.load()
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
        cost_fn, concurrency, client_kind = None, args.concurrency or 1, args.client

    config = RunConfig(
        n_samples=args.samples,
        max_retries=args.retries,
        n_boot=args.bootstrap,
        seed=args.seed,
        min_samples=args.min_samples,
        max_calls=args.max_calls,
        max_cost=args.max_cost,
        concurrency=concurrency,
        eq_cache_dir=args.eq_cache,
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out) / f"{stamp}_{spec.name}_{client.model_id}_{client_kind}"
    cache = None if args.no_cache else CallCache(args.cache)
    result = play_result = None
    try:
        if args.mode in ("direct", "both"):
            result, col, strat = run_direct(
                spec, template, client, config, out_dir, cache, eq, cost_fn, return_internals=True
            )
        if args.mode in ("play", "both"):
            direct = (col, strat) if args.mode == "both" else None
            play_result = run_play(
                spec, template, client, config, args.hands, args.opponent, out_dir, cache, eq, cost_fn, direct
            )
    except (BudgetExceeded, QuotaExhausted) as e:
        print(f"ABORTED: {e}", file=sys.stderr)
        print(
            f"Completed calls are cached in {args.cache}; rerun the same command to resume.", file=sys.stderr
        )
        return 2
    finally:
        if cache:
            cache.close()

    if result is not None:
        print_direct(spec, client, result)
    if play_result is not None:
        print_play(spec, play_result)
    print(f"  results: {out_dir}")
    return 0


def print_direct(spec, client, result) -> None:
    m, ci, rel = result["metrics"], result["ci95"], result["reliability"]
    corrected, u = result.get("bias_corrected") or {}, spec.unit_size

    def fmt(name: str, plug_in: float) -> str:
        """Bias-corrected estimate [basic 95% interval] (plug-in), or the plug-in value alone."""
        if name not in corrected:
            return f"{plug_in:.4f}"
        lo, hi = ci[name]
        return f"{corrected[name] / u:.4f}  [{lo / u:.4f}, {hi / u:.4f}]  (plug-in {plug_in:.4f})"

    unit = result["payoff_unit"]
    print(f"{spec.name} | {client.model_id} ({result['subject_kind']}) | prompt {result['prompt_version']}")
    if corrected:
        print("  values: bias-corrected estimate [basic 95% bootstrap interval] (plug-in estimate)")
    print(f"  M1 exploitability ({unit}/{spec.episode}):   {fmt('exploitability', m['exploitability_norm'])}")
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
    if result.get("cost_usd_estimated") is not None:
        print(
            f"  tokens in/out {rel['input_tokens']}/{rel['output_tokens']} | "
            f"estimated cost ${result['cost_usd_estimated']:.4f} "
            f"(spent in this invocation ${result['cost_usd_live']:.4f})"
        )
    print(f"  equilibrium seat values: {[round(v, 5) for v in result['equilibrium']['values']]}")


def print_play(spec, result) -> None:
    p, rel, ep = result["play"], result["reliability"], spec.episode
    print(f"  play vs {p['opponent']}: {p['n_hands']} {ep}s, seed {p['seed']}")
    for seat in range(2):
        lo, hi = p["seat_ci95"][seat]
        print(
            f"     subject seat {seat + 1}: mean {p['seat_mean'][seat]:+.4f}  [{lo:+.4f}, {hi:+.4f}]  "
            f"({p['seat_hands'][seat]} {ep}s)"
        )
    print(
        f"     subject decisions {p['subject_decisions']} | fallbacks {p['fallbacks']} | "
        f"parse-fail {rel['parse_failure_rate']:.3f} | live calls {rel['live_calls']}"
    )
    for row in result.get("cross_check", []):
        verdict = "agree" if row["agree"] else "DISAGREE"
        print(
            f"     cross-check seat {row['seat'] + 1}: exact {row['exact']:+.4f} vs simulated "
            f"{row['simulated']:+.4f} (z = {row['z']:+.2f}) -> {verdict}"
        )


if __name__ == "__main__":
    sys.exit(main())
