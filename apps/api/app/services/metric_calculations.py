"""Shared, deterministic helpers for transparent derived metrics.

The functions in this module deliberately return ``None`` when the available
observations are insufficient.  A missing platform field must never become a
real zero merely to make a chart or ranking easier to render.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def safe_rate(numerator: float | int | None, denominator: float | int | None) -> float | None:
    """Return a ratio only when both observations are present and usable."""
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def percentile_rank(
    value: float | int | None, values: Sequence[float | int | None]
) -> float | None:
    """Return a tie-aware 0..100 percentile rank.

    A single observation receives 50 rather than 100: one item is not enough
    evidence to call itself the best item in a population.
    """
    if value is None:
        return None
    valid = sorted(
        float(item)
        for item in values
        if item is not None and math.isfinite(float(item))
    )
    if not valid:
        return None
    if len(valid) == 1:
        return 50.0
    target = float(value)
    matching = [index for index, item in enumerate(valid) if item == target]
    if not matching:
        insertion = sum(1 for item in valid if item < target)
        return round(100.0 * insertion / (len(valid) - 1), 2)
    average_position = sum(matching) / len(matching)
    return round(100.0 * average_position / (len(valid) - 1), 2)


def sample_confidence(sample_size: int, *, target_size: int = 20) -> float:
    """Return a conservative 0..1 confidence factor for a finite sample."""
    if sample_size <= 0 or target_size <= 0:
        return 0.0
    return round(min(1.0, math.sqrt(sample_size / target_size)), 4)


def freshness_score(age_hours: float | None, *, half_life_hours: float) -> float | None:
    """Return an exponential freshness score on a 0..100 scale."""
    if age_hours is None or half_life_hours <= 0:
        return None
    return round(100.0 * math.pow(0.5, max(age_hours, 0.0) / half_life_hours), 2)


def ratio_score(ratio: float | None) -> float | None:
    """Map performance relative to a baseline to 0..100 on a log scale.

    0.5x -> 25, 1x -> 50, 2x -> 75 and 4x -> 100.  The log scale prevents a
    single extreme view count from dominating all other components.
    """
    if ratio is None or ratio <= 0:
        return None
    return round(min(100.0, max(0.0, 50.0 + 25.0 * math.log2(ratio))), 2)


def weighted_available_score(
    components: Mapping[str, tuple[float | None, float]],
    *,
    minimum_components: int = 2,
) -> tuple[float | None, dict[str, float]]:
    """Combine available 0..100 components and re-normalize their weights."""
    available = {
        key: (min(100.0, max(0.0, float(value))), float(weight))
        for key, (value, weight) in components.items()
        if value is not None and weight > 0
    }
    if len(available) < minimum_components:
        return None, {}
    total_weight = sum(weight for _, weight in available.values())
    if total_weight <= 0:
        return None, {}
    normalized = {key: weight / total_weight for key, (_, weight) in available.items()}
    score = sum(available[key][0] * weight for key, weight in normalized.items())
    return round(score, 2), {key: round(weight, 4) for key, weight in normalized.items()}
