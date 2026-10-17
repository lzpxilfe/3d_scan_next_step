"""Synthetic tests for dimension measurement. SYNTHETIC only."""

from __future__ import annotations

import pytest

from archphoto.archaeo.measure import Measurement, length_residual, measure_distance
from archphoto.geom import LengthUnit, SpatialFrame


def _frame() -> SpatialFrame:
    return SpatialFrame(crs_id="LOCAL:t", unit=LengthUnit.MILLIMETER)


def test_measure_distance_is_metric_and_derived() -> None:
    m = measure_distance((0, 0, 0), (3, 4, 0), _frame())
    assert m.value == pytest.approx(5.0)
    assert m.unit is LengthUnit.MILLIMETER
    assert m.derived is True  # computed from the model, not a tape measure


def test_length_residual_signed() -> None:
    m = Measurement(value=5.0, unit=LengthUnit.MILLIMETER, point_a=(0, 0, 0), point_b=(3, 4, 0))
    assert length_residual(m, 4.0) == pytest.approx(1.0)
    assert length_residual(m, 6.0) == pytest.approx(-1.0)
