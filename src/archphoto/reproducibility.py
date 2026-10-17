"""Reproducibility / determinism utilities (PERFORMANCE_GOALS.md §2.3).

Hardware-independent mesh RESULTS require determinism: the same inputs and the
same algorithm version must produce the same geometry within a stated tolerance,
regardless of which machine computes it. This module provides:

  - :func:`set_global_seed` — fix random seeds so RANSAC / optimization paths are
    repeatable (a real source of non-determinism).
  - :class:`DeterminismSettings` — capture seed + code/engine/weight versions for
    provenance (feeds :class:`archphoto.runlog.record.RunRecord`).
  - :func:`compare_point_sequences` / :func:`compare_point_maps` — decide whether
    two results agree within a tolerance (the "reproducible within tolerance" test).

These operate on plain coordinate data, so they are testable without an engine or
real survey data. Bit-exact equality across different hardware is NOT guaranteed
(floating-point reduction order differs); tolerance-based agreement is the honest
target.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from math import sqrt
from typing import Iterable, Mapping, Sequence

Point3D = tuple[float, float, float]


def set_global_seed(seed: int) -> None:
    """Seed the RNGs that stochastic steps (RANSAC, optimization) draw from.

    Seeds the stdlib ``random`` module always, and ``numpy``'s global RNG when
    numpy is importable. Without a fixed seed, two runs on the same hardware can
    still differ, so this is a prerequisite for any reproducibility claim.
    """
    random.seed(seed)
    try:  # numpy is optional and not assumed present
        import numpy as _np  # type: ignore

        _np.random.seed(seed % (2**32))
    except Exception:
        pass


@dataclass
class DeterminismSettings:
    """Provenance needed to reproduce a run (05 §5 / PERFORMANCE §2.3)."""

    seed: int
    code_version: str = ""
    engine_version: str = ""
    weight_version: str = ""
    input_hashes: dict = field(default_factory=dict)

    def as_run_parameters(self) -> dict:
        """A dict suitable for ``RunRecord.parameters`` / provenance fields."""
        return {
            "seed": self.seed,
            "code_version": self.code_version,
            "engine_version": self.engine_version,
            "weight_version": self.weight_version,
            "input_hashes": dict(self.input_hashes),
        }


@dataclass
class ReproResult:
    """Outcome of a reproducibility comparison.

    ``within_tolerance`` is the pass/fail. ``max_deviation`` is the largest
    per-point Euclidean difference (in the data's unit). ``count_a`` / ``count_b``
    expose size mismatches. ``mismatches`` lists the offending indices/ids.
    """

    within_tolerance: bool
    max_deviation: float
    count_a: int
    count_b: int
    mismatches: list = field(default_factory=list)


def _dev(pa: Sequence[float], pb: Sequence[float]) -> float:
    return sqrt((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2 + (pa[2] - pb[2]) ** 2)


def compare_point_sequences(
    a: Iterable[Point3D], b: Iterable[Point3D], tol: float
) -> ReproResult:
    """Compare two ordered point lists within ``tol`` (same order assumed).

    A deterministic pipeline emits vertices in a stable order, so element-wise
    comparison is meaningful. Use :func:`compare_point_maps` when points are
    keyed by id instead of order.
    """
    la, lb = list(a), list(b)
    if len(la) != len(lb):
        return ReproResult(False, float("inf"), len(la), len(lb), [])
    max_dev = 0.0
    mismatches: list[int] = []
    for i, (pa, pb) in enumerate(zip(la, lb)):
        d = _dev(pa, pb)
        if d > max_dev:
            max_dev = d
        if d > tol:
            mismatches.append(i)
    return ReproResult(len(mismatches) == 0, max_dev, len(la), len(lb), mismatches)


def compare_point_maps(
    a: Mapping[str, Point3D], b: Mapping[str, Point3D], tol: float
) -> ReproResult:
    """Compare two id-keyed point sets within ``tol``.

    Missing or extra ids count as mismatches and force ``within_tolerance`` False.
    """
    keys_a, keys_b = set(a), set(b)
    if keys_a != keys_b:
        missing = sorted(keys_a ^ keys_b)
        return ReproResult(False, float("inf"), len(a), len(b), missing)
    max_dev = 0.0
    mismatches: list[str] = []
    for k in a:
        d = _dev(a[k], b[k])
        if d > max_dev:
            max_dev = d
        if d > tol:
            mismatches.append(k)
    return ReproResult(len(mismatches) == 0, max_dev, len(a), len(b), sorted(mismatches))
