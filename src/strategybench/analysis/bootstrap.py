"""Bootstrap confidence intervals and bias correction.

Each replicate resamples the valid samples at every infostate (with replacement,
keeping that infostate's sample size), rebuilds the strategy and recomputes the metrics.

Exploitability and best-response gains are maxima over opponent strategies, so plug-in
estimates from noisy samples are biased upwards, most strongly near equilibrium, where the
best responder is indifferent almost everywhere. The replicates are biased upwards again, so
percentile intervals sit above the truth: in simulation they almost never cover an
equilibrium subject's true value (``scripts/ci_coverage.py``, see the methodology). For every
metric ``bootstrap_metrics`` therefore reports

* the bias-corrected estimate ``max(0, 2 * point - mean(replicates))``, and
* the basic (reflected) interval ``[2 * point - q_hi, 2 * point - q_lo]``, clipped at 0,
  which is centred on it and is the interval runs report,

and keeps the percentile interval and the bootstrap bias (mean of replicates minus point).
For metrics with little bias the two intervals nearly coincide.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pyspiel

from strategybench.analysis.metrics import Equilibrium, Metrics, compute_metrics
from strategybench.estimation.infostates import InfoState
from strategybench.estimation.strategy import resample_counts, strategy_from_counts

#: Metric keys used for intervals and corrections (seat-specific values carry the seat index).
METRIC_KEYS = ("exploitability", "br_gain_0", "br_gain_1", "h2h_loss_0", "h2h_loss_1")


def metric_values(m: Metrics) -> dict[str, float]:
    return {
        "exploitability": m.exploitability,
        "br_gain_0": m.br_gain[0],
        "br_gain_1": m.br_gain[1],
        "h2h_loss_0": m.h2h_loss[0],
        "h2h_loss_1": m.h2h_loss[1],
    }


def percentile_ci(values: list[float] | np.ndarray, level: float = 0.95) -> tuple[float, float]:
    alpha = (1.0 - level) / 2.0
    lo, hi = np.quantile(np.asarray(values), [alpha, 1.0 - alpha])
    return float(lo), float(hi)


def basic_ci(point: float, values: list[float] | np.ndarray, level: float = 0.95) -> tuple[float, float]:
    """Percentile interval reflected about the point estimate, clipped at 0."""
    lo, hi = percentile_ci(values, level)
    return max(0.0, 2 * point - hi), max(0.0, 2 * point - lo)


def bootstrap_statistic(
    counts: dict[str, dict[int, int]],
    statistic: Callable[[dict[str, dict[int, int]]], float],
    n_boot: int,
    rng: np.random.Generator,
    level: float = 0.95,
) -> tuple[float, float]:
    return percentile_ci([statistic(resample_counts(counts, rng)) for _ in range(n_boot)], level)


@dataclass
class BootstrapResult:
    """Per metric key (``METRIC_KEYS``), in native payoff units."""

    #: Basic intervals, clipped at 0 (the reported intervals).
    basic: dict[str, tuple[float, float]]
    percentile: dict[str, tuple[float, float]]
    #: ``max(0, 2 * point - mean(replicates))``.
    bias_corrected: dict[str, float]
    #: ``mean(replicates) - point``.
    bias: dict[str, float]


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
) -> BootstrapResult:
    """Intervals, bias and bias-corrected estimates for M1 and the per-seat M2 and M3 values."""
    point = metric_values(
        compute_metrics(game, strategy_from_counts(game, infostates, counts, min_samples).policy, eq)
    )
    reps: list[dict[str, float]] = []
    for _ in range(n_boot):
        strat = strategy_from_counts(game, infostates, resample_counts(counts, rng), min_samples)
        reps.append(metric_values(compute_metrics(game, strat.policy, eq, unit_size)))

    result = BootstrapResult({}, {}, {}, {})
    for key in METRIC_KEYS:
        values = np.array([r[key] for r in reps])
        mean = float(values.mean())
        result.basic[key] = basic_ci(point[key], values, level)
        result.percentile[key] = percentile_ci(values, level)
        result.bias[key] = mean - point[key]
        result.bias_corrected[key] = max(0.0, 2 * point[key] - mean)
    return result
