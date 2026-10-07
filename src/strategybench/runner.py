"""Run one subject on one game and write the results directory.

Outputs (under ``out_dir``):
  manifest.json      configuration, prompt version and system prompt, library versions
  calls.jsonl        direct mode: one line per attempt (raw output, parse status, tokens, cache flag)
  strategy.json      direct mode: per-infostate estimated strategy, support and equilibrium strategy
  metrics.json       direct mode: M1-M4, bootstrap CIs, coverage and filled fraction
  play.json          play mode: per-seat results and, after a direct run, the exact-vs-simulated check
  play_calls.jsonl   play mode: one line per attempt
  hands.jsonl        play mode: one line per hand (cards, every action, subject payoff)
"""

from __future__ import annotations

import importlib.metadata
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from strategybench.adapters.base import DistributionClient, TextClient
from strategybench.adapters.cache import CallCache
from strategybench.analysis.bootstrap import bootstrap_metrics
from strategybench.analysis.metrics import (
    Equilibrium,
    compute_metrics,
    exact_seat_values,
    solve_equilibrium,
)
from strategybench.baselines.scripted import uniform_policy
from strategybench.estimation.direct import (
    CallBudget,
    CallLog,
    Collection,
    collect_distribution,
    collect_text,
)
from strategybench.estimation.play import PlayResult, play_match
from strategybench.estimation.strategy import (
    EstimatedStrategy,
    coverage,
    resample_counts,
    strategy_from_counts,
    strategy_from_probabilities,
)
from strategybench.games.base import GameSpec
from strategybench.prompts.base import PromptTemplate


@dataclass
class RunConfig:
    n_samples: int = 50
    max_retries: int = 2
    n_boot: int = 200
    seed: int = 0
    min_samples: int = 1
    coverage_k: int = 5
    max_calls: int | None = None
    max_cost: float | None = None
    concurrency: int = 1
    eq_iterations: int = 2000
    eq_cache_dir: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _versions() -> dict[str, str]:
    return {pkg: importlib.metadata.version(pkg) for pkg in ("strategybench", "open_spiel", "numpy")}


def run_direct(
    spec: GameSpec,
    template: PromptTemplate,
    client: TextClient | DistributionClient,
    config: RunConfig,
    out_dir: str | Path | None = None,
    cache: CallCache | None = None,
    equilibrium: Equilibrium | None = None,
    cost_fn: Callable[[int, int], float] | None = None,
    return_internals: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], Collection, EstimatedStrategy]:
    out = Path(out_dir) if out_dir else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    game = spec.load()
    eq = equilibrium or solve_equilibrium(spec.load_string, config.eq_iterations, config.eq_cache_dir)
    log = CallLog(out / "calls.jsonl" if out else None)
    budget = CallBudget(config.max_calls, config.max_cost, cost_fn)

    try:
        if isinstance(client, TextClient):
            col = collect_text(
                spec,
                template,
                client,
                config.n_samples,
                config.max_retries,
                cache,
                log,
                budget,
                config.concurrency,
            )
            strat = strategy_from_counts(game, col.infostates, col.counts, config.min_samples)
        else:
            col = collect_distribution(spec, template, client, cache, log, budget)
            strat = strategy_from_probabilities(game, col.infostates, col.probabilities)
    finally:
        log.close()

    metrics = compute_metrics(game, strat.policy, eq, spec.unit_size)
    cis: dict[str, tuple[float, float]] = {}
    bias: dict[str, float] = {}
    if col.kind == "sampled" and config.n_boot > 0:
        rng = np.random.default_rng(config.seed)
        cis, bias = bootstrap_metrics(
            game, col.infostates, col.counts, eq, config.n_boot, rng, spec.unit_size, config.min_samples
        )

    coverage_k = config.coverage_k if col.kind == "sampled" else 1
    result = {
        "game": spec.name,
        "provider": client.provider,
        "model_id": client.model_id,
        "params": client.params,
        "prompt_version": template.version,
        "mode": "direct",
        "subject_kind": col.kind,
        "n_samples": config.n_samples if col.kind == "sampled" else None,
        "payoff_unit": spec.payoff_unit,
        "metrics": metrics.as_dict(),
        "ci95": cis,
        "bias": bias,
        "equilibrium": {"values": eq.values, "exploitability": eq.exploitability},
        "reliability": {**asdict(col.reliability), **col.reliability.rates()},
        "cost_usd_estimated": budget.spent if cost_fn else None,
        "coverage": {f"k={coverage_k}": coverage(game, strat, coverage_k)},
        "filled": {"count": len(strat.filled), "of": len(col.infostates), "keys": strat.filled},
        "run_date": datetime.now(UTC).date().isoformat(),
    }

    if out:
        manifest = {
            "config": asdict(config),
            "game": spec.name,
            "openspiel_game": spec.load_string,
            "prompt_version": template.version,
            "system_prompt": template.system,
            "provider": client.provider,
            "model_id": client.model_id,
            "params": client.params,
            "versions": _versions(),
            "created": datetime.now(UTC).isoformat(),
        }
        strategy_rows = []
        for info in col.infostates:
            labels = spec.action_labels(info.state)
            est, ref = strat.policy.policy_for_key(info.key), eq.policy.policy_for_key(info.key)
            strategy_rows.append(
                {
                    "infostate": info.key,
                    "player": info.player,
                    "situation": spec.render_infostate(info.state),
                    "support": strat.support[info.key],
                    "filled": info.key in strat.filled,
                    "estimated": {labels[a]: float(est[a]) for a in info.legal_actions},
                    "equilibrium": {labels[a]: float(ref[a]) for a in info.legal_actions},
                }
            )
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
        (out / "strategy.json").write_text(json.dumps(strategy_rows, indent=2))
        (out / "metrics.json").write_text(json.dumps(result, indent=2))
    if return_internals:
        return result, col, strat
    return result


def opponent_policy(name: str, spec: GameSpec, eq: Equilibrium):
    if name == "equilibrium":
        return eq.policy
    if name == "uniform":
        return uniform_policy(spec.load())
    raise ValueError(f"unknown opponent {name!r} (choose equilibrium or uniform)")


def run_play(
    spec: GameSpec,
    template: PromptTemplate,
    client: TextClient | DistributionClient,
    config: RunConfig,
    n_hands: int,
    opponent: str = "equilibrium",
    out_dir: str | Path | None = None,
    cache: CallCache | None = None,
    equilibrium: Equilibrium | None = None,
    cost_fn: Callable[[int, int], float] | None = None,
    direct: tuple[Collection, EstimatedStrategy] | None = None,
) -> dict[str, Any]:
    """Play ``n_hands`` against ``opponent``; with ``direct`` internals, also cross-check the
    simulated per-seat value against the exact value of the direct-mode estimate."""
    out = Path(out_dir) if out_dir else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    eq = equilibrium or solve_equilibrium(spec.load_string, config.eq_iterations, config.eq_cache_dir)
    opp = opponent_policy(opponent, spec, eq)
    log = CallLog(out / "play_calls.jsonl" if out else None)
    hand_log = CallLog(out / "hands.jsonl" if out else None)
    budget = CallBudget(config.max_calls, config.max_cost, cost_fn)
    try:
        play = play_match(
            spec,
            template,
            client,
            opp,
            opponent,
            n_hands,
            config.seed,
            config.max_retries,
            cache,
            log,
            hand_log,
            budget,
            config.concurrency,
        )
    finally:
        log.close()
        hand_log.close()

    result: dict[str, Any] = {
        "game": spec.name,
        "model_id": client.model_id,
        "mode": "play",
        "play": play.as_dict(),
        "reliability": {**asdict(play.reliability), **play.reliability.rates()},
        "cost_usd_estimated": budget.spent if cost_fn else None,
    }
    if direct is not None:
        result["cross_check"] = cross_check(spec, direct[0], direct[1], opp, play, config)
    if out:
        (out / "play.json").write_text(json.dumps(result, indent=2))
    return result


def cross_check(
    spec: GameSpec,
    col: Collection,
    strat: EstimatedStrategy,
    opponent: Any,
    play: PlayResult,
    config: RunConfig,
) -> list[dict[str, Any]]:
    """Compare, per seat, the exact value of the direct-mode estimate against the opponent with
    the simulated play-mode mean. The two agree when their difference is within 1.96 combined
    standard errors (simulation error plus the estimate's bootstrap error)."""
    game = spec.load()
    exact = exact_seat_values(game, strat.policy, opponent)
    se_exact = [0.0, 0.0]
    if col.kind == "sampled" and config.n_boot > 0:
        rng = np.random.default_rng(config.seed + 1)
        reps = np.array(
            [
                exact_seat_values(
                    game,
                    strategy_from_counts(
                        game, col.infostates, resample_counts(col.counts, rng), config.min_samples
                    ).policy,
                    opponent,
                )
                for _ in range(config.n_boot)
            ]
        )
        se_exact = [float(x) for x in reps.std(axis=0, ddof=1)]

    rows = []
    for seat in range(2):
        sim, se_sim = play.seat_mean[seat], play.seat_stderr[seat]
        se = float(np.hypot(se_sim, se_exact[seat]))
        diff = sim - exact[seat]
        rows.append(
            {
                "seat": seat,
                "exact": exact[seat],
                "exact_se": se_exact[seat],
                "simulated": sim,
                "simulated_se": se_sim,
                "difference": diff,
                "z": diff / se if se > 0 else float("nan"),
                "agree": bool(abs(diff) <= 1.96 * se),
            }
        )
    return rows
