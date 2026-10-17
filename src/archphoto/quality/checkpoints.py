"""GCP constraint application vs independent CHECK-point evaluation.

PRINCIPLE (05 §2, AGENTS.md): the two are SEPARATE and enforced.
  - ``apply_gcp_constraint`` consumes ONLY calibration roles (GCP/SCALE/CONSTRAINT).
    Their residuals may be reported but are NOT independent accuracy.
  - ``evaluate_check`` consumes ONLY CHECK (or CHECK_LENGTH) points, and only
    those that did NOT take part in fitting the model (see PointUsageLedger).
    Its residuals are MODEL error in the frame's units — NOT survey error.

A residual here is the difference between a reconstructed 3D coordinate and the
surveyed coordinate. The ``model`` argument is any mapping ``point_id -> (x,y,z)``
of reconstructed coordinates in the SAME SpatialFrame/unit as the ControlPoints.
A real reconstruction would supply this; synthetic tests supply a dict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Mapping

from archphoto.quality.ledger import PointUsageLedger
from archphoto.sensing.control import ControlPoint, ControlRole

Point3D = tuple[float, float, float]
ModelMap = Mapping[str, Point3D]


@dataclass
class CheckValidation:
    """Residuals of the model against CHECK points (model error, not survey error).

    ``residuals`` maps point_id -> per-axis 3D residual (reconstructed - surveyed),
    in frame units. ``distances`` maps point_id -> Euclidean residual distance.
    ``stats`` holds summary stats (mean/median/max distance) once computed.
    """

    residuals: dict[str, Point3D] = field(default_factory=dict)
    distances: dict[str, float] = field(default_factory=dict)
    stats: dict = field(default_factory=dict)


@dataclass
class ConstraintReport:
    """Which GCP/scale/constraint points were applied to the solve.

    ``applied`` lists point ids used as constraints. ``residuals`` may report the
    post-solve residual at those points, but these are NOT independent accuracy.
    """

    applied: list[str] = field(default_factory=list)
    residuals: dict[str, Point3D] = field(default_factory=dict)


def apply_gcp_constraint(
    points: list[ControlPoint],
    ledger: PointUsageLedger,
    model: ModelMap | None = None,
) -> ConstraintReport:
    """Apply calibration-role points as constraints; refuse CHECK points.

    Only roles with ``used_in_calibration`` are accepted. CHECK/CHECK_LENGTH are
    rejected so they can never enter the solve. Applied points are recorded in
    the ledger so they cannot later be used for independent evaluation.
    """
    report = ConstraintReport()
    for p in points:
        if not p.role.used_in_calibration:
            raise ValueError(
                f"Point {p.point_id!r} has role {p.role.value!r}; CHECK points "
                "must not be used to constrain the model."
            )
        ledger.mark_constraint(p.point_id)
        report.applied.append(p.point_id)
        if model is not None and p.point_id in model:
            rx, ry, rz = _residual(model[p.point_id], p)
            report.residuals[p.point_id] = (rx, ry, rz)
    return report


def evaluate_check(
    model: ModelMap,
    check_points: list[ControlPoint],
    ledger: PointUsageLedger | None = None,
) -> CheckValidation:
    """Compute model-vs-CHECK residuals for INDEPENDENT validation only.

    Enforces:
      1. every point must be a CHECK (or CHECK_LENGTH) role;
      2. no point may have been used to fit the model (constraint/alignment).
    """
    ledger = ledger if ledger is not None else PointUsageLedger()
    out = CheckValidation()
    for p in check_points:
        if not p.role.is_independent_check:
            raise ValueError(
                f"Point {p.point_id!r} has role {p.role.value!r}; only CHECK "
                "points may be used for independent validation."
            )
        if p.point_id not in model:
            raise KeyError(f"No reconstructed coordinate for check point {p.point_id!r}")
        ledger.mark_evaluation(p.point_id)  # raises if the point fitted the model
        rx, ry, rz = _residual(model[p.point_id], p)
        out.residuals[p.point_id] = (rx, ry, rz)
        out.distances[p.point_id] = sqrt(rx * rx + ry * ry + rz * rz)
    out.stats = _stats(out.distances)
    return out


def validate_checkpoints(
    model: ModelMap,
    check_points: list[ControlPoint],
    ledger: PointUsageLedger | None = None,
) -> CheckValidation:
    """Backward-compatible entry point for independent CHECK evaluation.

    Delegates to :func:`evaluate_check`. The role check runs before any model
    access, so a GCP passed in is rejected with ValueError regardless of model.
    """
    return evaluate_check(model, check_points, ledger)


def _residual(reconstructed: Point3D, surveyed: ControlPoint) -> Point3D:
    return (
        reconstructed[0] - surveyed.x,
        reconstructed[1] - surveyed.y,
        reconstructed[2] - surveyed.z,
    )


def _stats(distances: dict[str, float]) -> dict:
    if not distances:
        return {}
    vals = sorted(distances.values())
    n = len(vals)
    mid = n // 2
    median = vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2
    return {
        "count": n,
        "mean": sum(vals) / n,
        "median": median,
        "max": vals[-1],
    }
