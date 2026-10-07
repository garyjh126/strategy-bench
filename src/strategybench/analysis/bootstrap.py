"""Bootstrap confidence intervals.

Each replicate resamples the valid samples at every infostate (with replacement,
keeping that infostate's sample size), rebuilds the strategy and recomputes the metrics.
Intervals are percentile intervals.

Caveat (documented in the methodology): exploitability is a maximum over opponent
strategies, so plug-in estimates from noisy samples are biased upwards at small N, and
percentile intervals inherit that bias. ``bootstrap_metrics`` therefore also reports the
bootstrap bias estimate (mean of replicates minus the point estimate) and a bias-corrected
exploitability, ``max(0, 2 * point - mean)``.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pyspiel

from strategybench.analysis.metrics import Equilibrium, Metrics, compute_metrics
from strategybench.estimation.infostates import InfoState
from strategybench.estimation.strategy import resample_counts, strategy_from_counts


def percentile_ci(values: list[float] | np.ndarray, level: float = 0.95) -> tuple[float, float]:
    alpha = (1.0 - level) / 2.0
    lo, hi = np.quantile(np.asarray(values), [alpha, 1.0 - alpha])
    return float(lo), float(hi)


def bootstrap_statistic(
    counts: dict[str, dict[int, int]],
    statistic: Callable[[dict[str, dict[int, int]]], float],
    n_boot: int,
    rng: np.random.Generator,
    level: float = 0.95,
) -> tuple[float, float]:
    return percentile_ci([statistic(resample_counts(counts, rng)) for _ in range(n_boot)], level)


def bootstrap_metrics(
    game: pyspiel.Game,
    infostates: list[InfoState],
    counts: dict[str, dict[int, int]],
    eq: Equilibrium,
    n_boot: int,
    rng: np.random.Generator,
    unit_size: float = 1.0,
    min_samples: int = 1,
    level: float = 0.95,
) -> tuple[dict[str, tuple[float, float]], dict[str, float]]:
    """Percentile CIs for M1 and the per-seat M2 / M3 values, plus M1 bias diagnostics."""
    point = compute_metrics(game, strategy_from_counts(game, infostates, counts, min_samples).policy, eq)
    reps: list[Metrics] = []
    for _ in range(n_boot):
        strat = strategy_from_counts(game, infostates, resample_counts(counts, rng), min_samples)
        reps.append(compute_metrics(game, strat.policy, eq, unit_size))

    cis = {"exploitability": percentile_ci([m.exploitability for m in reps], level)}
    for seat in range(2):
        cis[f"br_gain_{seat}"] = percentile_ci([m.br_gain[seat] for m in reps], level)
        cis[f"h2h_loss_{seat}"] = percentile_ci([m.h2h_loss[seat] for m in reps], level)

    mean = float(np.mean([m.exploitability for m in reps]))
    bias = {
        "exploitability_bootstrap_bias": mean - point.exploitability,
        "exploitability_bias_corrected": max(0.0, 2 * point.exploitability - mean),
    }
    return cis, bias
