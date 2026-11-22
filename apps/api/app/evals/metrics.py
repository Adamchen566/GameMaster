"""Small, dependency-free statistics for the evaluation report."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence


def rate(hits: int, total: int) -> float | None:
    """A share between 0 and 1, or None when there was nothing to count."""
    return hits / total if total else None


def share(flags: Iterable[bool]) -> float | None:
    values = list(flags)
    return rate(sum(values), len(values))


def percentile(values: Sequence[float], percent: float) -> float | None:
    """Nearest-rank percentile: the smallest value with at least `percent`% at or below it."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percent / 100 * len(ordered)))
    return ordered[rank - 1]


def wilson_interval(hits: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% confidence interval for a proportion; honest for small samples and for 0% or 100%."""
    if total == 0:
        return None
    p = hits / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)
