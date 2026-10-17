"""Dimension / distance measurement (고고학 산출물: 치수).

Computes metric distances between 3D points in a stated SpatialFrame, for
artifact dimensions, wall thickness, and independent length checks (05 §2
CHECK_LENGTH). A distance computed from the model is a DERIVED measurement, not a
direct tape measurement — that distinction is kept in :attr:`Measurement.derived`.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt

from archphoto.geom.crs import LengthUnit, SpatialFrame

Point3D = tuple[float, float, float]


@dataclass
class Measurement:
    """A distance between two 3D points, in ``unit``.

    ``derived=True`` means it was computed from the reconstructed model (not a
    direct field measurement). ``sigma`` is a propagated uncertainty if known;
    it is NOT the model's accuracy claim.
    """

    value: float
    unit: LengthUnit
    point_a: Point3D
    point_b: Point3D
    derived: bool = True
    sigma: float | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.value) or self.value < 0:
            raise ValueError("Measurement.value must be finite and >= 0")
        if not all(isfinite(c) for c in self.point_a) or not all(isfinite(c) for c in self.point_b):
            raise ValueError("Measurement endpoint coordinates must be finite")
        if self.sigma is not None and (not isfinite(self.sigma) or self.sigma < 0):
            raise ValueError("Measurement.sigma must be finite and >= 0")


def measure_distance(a: Point3D, b: Point3D, frame: SpatialFrame) -> Measurement:
    """Euclidean distance between ``a`` and ``b``, in ``frame`` units."""
    if not all(isfinite(c) for c in a) or not all(isfinite(c) for c in b):
        raise ValueError("measure_distance endpoints must be finite")
    d = sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2)
    return Measurement(value=d, unit=frame.unit, point_a=a, point_b=b, derived=True)


def length_residual(measured: Measurement, reference_value: float) -> float:
    """Signed residual ``measured - reference`` (frame units).

    Used to validate a model dimension against an independent reference length
    (CHECK_LENGTH). The reference must come from independent surveying, never
    from the same points used to fit the model.
    """
    if not isfinite(reference_value) or reference_value <= 0:
        raise ValueError("reference_value must be finite and positive")
    return measured.value - reference_value
