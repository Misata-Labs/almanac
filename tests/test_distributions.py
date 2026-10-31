from __future__ import annotations

import pytest

from almanac.distributions import quantile, sample, series_statistic, summarise
from almanac.models import Distribution, Statistic


def test_categorical_sampling_reproduces_shares():
    dist = Distribution(family="categorical", parameters={"shares": {"a": 0.7, "b": 0.3}})
    values = sample(dist, 50_000, seed=1)
    assert abs(summarise(values, Statistic.parse("share[a]")) - 0.7) < 0.01


def test_normal_sampling_reproduces_moments():
    dist = Distribution(family="normal", parameters={"mean": 10, "std": 2})
    values = sample(dist, 50_000, seed=2)
    assert abs(summarise(values, Statistic.parse("mean")) - 10) < 0.05
    assert abs(summarise(values, Statistic.parse("std")) - 2) < 0.05
    assert abs(summarise(values, Statistic.parse("median")) - 10) < 0.05


def test_lognormal_and_uniform_and_empirical():
    assert all(v > 0 for v in sample(Distribution(family="lognormal", parameters={"mu": 0, "sigma": 1}), 1000))
    uniform = sample(Distribution(family="uniform", parameters={"low": 1, "high": 2}), 1000)
    assert 1 <= min(uniform) and max(uniform) <= 2
    empirical = sample(Distribution(family="empirical", parameters={"values": [5, 7], "weights": [1, 0]}), 100)
    assert set(empirical) == {5.0}


def test_sampling_is_deterministic_for_a_seed():
    dist = Distribution(family="normal", parameters={"mean": 0, "std": 1})
    assert sample(dist, 100, seed=7) == sample(dist, 100, seed=7)


def test_quantile_interpolates():
    assert quantile([1, 2, 3, 4], 0.5) == 2.5
    with pytest.raises(ValueError):
        quantile([], 0.5)


def test_unknown_statistic_is_rejected():
    with pytest.raises(ValueError):
        summarise([1.0, 2.0], Statistic.parse("mode"))


def test_series_statistics():
    series = {"2025-01": 10.0, "2025-02": 20.0}
    assert series_statistic(series, Statistic.parse("value[2025-02]")) == 20.0
    assert series_statistic(series, Statistic.parse("ratio[2025-02,2025-01]")) == 2.0
    assert series_statistic(series, Statistic.parse("mean")) == 15.0
    assert series_statistic(series, Statistic.parse("count")) == 2
