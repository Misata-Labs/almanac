"""Sampling and summary statistics for distribution specifications.

Marginal and conditional entries describe a distribution family with
parameters. The verifier draws samples from that description and compares
summary statistics with the values the source publishes.
"""

from __future__ import annotations

import math
import random
from typing import Any, Mapping, Sequence

from almanac.models import Distribution, Statistic

DEFAULT_SAMPLE_SIZE = 200_000


def sample(distribution: Distribution, size: int = DEFAULT_SAMPLE_SIZE, seed: int = 0) -> list[Any]:
    """Draw ``size`` values from ``distribution`` using a seeded generator."""
    rng = random.Random(seed)
    params = distribution.parameters
    family = distribution.family
    if family == "categorical":
        categories = list(params["shares"].keys())
        weights = [float(params["shares"][c]) for c in categories]
        return rng.choices(categories, weights=weights, k=size)
    if family == "uniform":
        low, high = float(params["low"]), float(params["high"])
        return [rng.uniform(low, high) for _ in range(size)]
    if family == "normal":
        mean, std = float(params["mean"]), float(params["std"])
        return [rng.gauss(mean, std) for _ in range(size)]
    if family == "lognormal":
        mu, sigma = float(params["mu"]), float(params["sigma"])
        return [math.exp(rng.gauss(mu, sigma)) for _ in range(size)]
    if family == "empirical":
        values = [float(v) for v in params["values"]]
        weights = [float(w) for w in params.get("weights", [1.0] * len(values))]
        return rng.choices(values, weights=weights, k=size)
    raise ValueError(f"unsupported distribution family {family!r}")


def quantile(values: Sequence[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile of an empty sample")
    position = (len(ordered) - 1) * p
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarise(values: Sequence[Any], stat: Statistic) -> float:
    """Evaluate a named statistic over sampled ``values``."""
    if stat.name == "share":
        (category,) = stat.args
        return sum(1 for v in values if str(v) == category) / len(values)
    if stat.name == "sum_of_shares":
        return 1.0
    numeric = [float(v) for v in values]
    if stat.name == "mean":
        return sum(numeric) / len(numeric)
    if stat.name == "std":
        mean = sum(numeric) / len(numeric)
        return math.sqrt(sum((v - mean) ** 2 for v in numeric) / (len(numeric) - 1))
    if stat.name == "median":
        return quantile(numeric, 0.5)
    if stat.name == "quantile":
        (p,) = stat.args
        return quantile(numeric, float(p))
    if stat.name == "min":
        return min(numeric)
    if stat.name == "max":
        return max(numeric)
    raise ValueError(f"unsupported distribution statistic {stat.name!r}")


def declared_share_total(distribution: Distribution) -> float:
    if distribution.family != "categorical":
        raise ValueError("share totals apply to categorical distributions only")
    return float(sum(float(v) for v in distribution.parameters["shares"].values()))


def series_statistic(series: Mapping[str, float], stat: Statistic, columns: Mapping[str, Mapping[str, float]] | None = None) -> float:
    """Evaluate a statistic over a temporal series keyed by period label.

    ``columns`` maps a column name to its own period-keyed series, answering
    ``column[name,period]`` for the extra columns a temporal entry carries.
    """
    if stat.name == "value":
        (period,) = stat.args
        return series[period]
    if stat.name == "column":
        name, period = stat.args
        return (columns or {})[name][period]
    if stat.name == "ratio":
        numerator, denominator = stat.args
        return series[numerator] / series[denominator]
    values = list(series.values())
    if stat.name == "mean":
        return sum(values) / len(values)
    if stat.name == "min":
        return min(values)
    if stat.name == "max":
        return max(values)
    if stat.name == "count":
        return float(len(values))
    raise ValueError(f"unsupported series statistic {stat.name!r}")
