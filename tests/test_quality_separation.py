"""Synthetic tests for GCP-constraint vs independent-evaluation separation (T07).

SYNTHETIC only (AGENTS.md: keep separate from real-data tests). These prove the
05 §2 rule: points that fit the model (constraint/alignment) can never be reused
as independent evaluation, and CHECK points never enter the solve.
"""

from __future__ import annotations

import pytest

from archphoto.geom import LengthUnit, SpatialFrame
from archphoto.quality import (
    PointUsageLedger,
    apply_gcp_constraint,
    evaluate_check,
)
from archphoto.sensing import ControlPoint, ControlRole


def _frame() -> SpatialFrame:
    return SpatialFrame(crs_id="LOCAL:t", unit=LengthUnit.MILLIMETER)


def _pt(pid: str, role: ControlRole, x: float, y: float, z: float) -> ControlPoint:
    return ControlPoint(pid, role, x, y, z, _frame())


def test_gcp_constraint_applies_and_marks_ledger() -> None:
    ledger = PointUsageLedger()
    gcp = [_pt("GCP-01", ControlRole.GCP, 0, 0, 0), _pt("SC-01", ControlRole.SCALE, 1, 0, 0)]
    report = apply_gcp_constraint(gcp, ledger, model={"GCP-01": (0.0, 0.0, 0.5)})
    assert set(report.applied) == {"GCP-01", "SC-01"}
    assert ledger.constraint == {"GCP-01", "SC-01"}
    # GCP residual is reported but is a ConstraintReport, not independent accuracy.
    assert "GCP-01" in report.residuals and report.residuals["GCP-01"][2] == 0.5


def test_apply_constraint_rejects_check_points() -> None:
    ledger = PointUsageLedger()
    with pytest.raises(ValueError):
        apply_gcp_constraint([_pt("CHK-01", ControlRole.CHECK, 0, 0, 0)], ledger)


def test_evaluate_check_computes_residuals() -> None:
    ledger = PointUsageLedger()
    checks = [
        _pt("CHK-01", ControlRole.CHECK, 10.0, 10.0, 10.0),
        _pt("CHK-02", ControlRole.CHECK, 0.0, 0.0, 0.0),
    ]
    model = {"CHK-01": (11.0, 10.0, 10.0), "CHK-02": (0.0, 3.0, 4.0)}
    v = evaluate_check(model, checks, ledger)
    assert v.residuals["CHK-01"] == (1.0, 0.0, 0.0)
    assert v.distances["CHK-01"] == pytest.approx(1.0)
    assert v.distances["CHK-02"] == pytest.approx(5.0)  # 3-4-5 triangle
    assert v.stats["count"] == 2 and v.stats["max"] == pytest.approx(5.0)
    assert ledger.evaluation == {"CHK-01", "CHK-02"}


def test_evaluate_check_rejects_gcp_role() -> None:
    with pytest.raises(ValueError):
        evaluate_check({"GCP-01": (0, 0, 0)}, [_pt("GCP-01", ControlRole.GCP, 0, 0, 0)])


def test_fitted_point_cannot_be_reused_for_evaluation() -> None:
    ledger = PointUsageLedger()
    gcp = _pt("P-01", ControlRole.GCP, 0, 0, 0)
    apply_gcp_constraint([gcp], ledger)
    # Reusing the same point as an independent check must be refused.
    with pytest.raises(ValueError):
        evaluate_check({"P-01": (0, 0, 0)}, [_pt("P-01", ControlRole.CHECK, 0, 0, 0)], ledger)


def test_aligned_point_cannot_be_reused_for_evaluation() -> None:
    ledger = PointUsageLedger()
    ledger.mark_alignment("CHK-09")
    with pytest.raises(ValueError):
        evaluate_check({"CHK-09": (0, 0, 0)}, [_pt("CHK-09", ControlRole.CHECK, 0, 0, 0)], ledger)
