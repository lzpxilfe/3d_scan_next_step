"""Synthetic tests for input preflight checks. SYNTHETIC only."""

from __future__ import annotations

from types import SimpleNamespace

from archphoto.geom import LengthUnit, SpatialFrame
from archphoto.preflight import preflight_control
from archphoto.sensing import ControlPoint, ControlRole, PhotoObservation


def _frame(crs: str = "LOCAL:t", unit=LengthUnit.MILLIMETER):
    return SpatialFrame(crs_id=crs, unit=unit)


def test_clean_input_has_no_error() -> None:
    pts = [
        ControlPoint("GCP-01", ControlRole.GCP, 0, 0, 0, _frame()),
        ControlPoint("CHK-01", ControlRole.CHECK, 1, 1, 1, _frame()),
    ]
    obs = [PhotoObservation("GCP-01", "P-01", 10.0, 20.0)]
    issues = preflight_control(pts, obs)
    assert [i for i in issues if i.severity == "error"] == []


def test_missing_crs_and_unknown_role_flagged() -> None:
    # ControlPoint/SpatialFrame enforce contracts at construction, so preflight
    # guards against deserialized / untyped objects that bypassed validation.
    bad_point = SimpleNamespace(
        point_id="P-01",
        role=ControlRole.UNKNOWN,
        frame=SimpleNamespace(crs_id="", unit=None),
    )
    codes = {i.code for i in preflight_control([bad_point])}
    assert "missing_crs" in codes
    assert "missing_unit" in codes
    assert "unknown_role" in codes


def test_missing_check_point_warns() -> None:
    pts = [ControlPoint("GCP-01", ControlRole.GCP, 0, 0, 0, _frame())]
    issues = preflight_control(pts)
    assert any(i.code == "no_check_point" and i.severity == "warning" for i in issues)


def test_duplicate_and_orphan_observation_flagged() -> None:
    pts = [ControlPoint("GCP-01", ControlRole.GCP, 0, 0, 0, _frame())]
    pts.append(ControlPoint("GCP-01", ControlRole.GCP, 0, 0, 0, _frame()))
    obs = [PhotoObservation("NOPE", "P-01", 0.0, 0.0)]
    codes = {i.code for i in preflight_control(pts, obs)}
    assert "duplicate_id" in codes
    assert "orphan_observation" in codes


def test_inconsistent_frame_across_points_flagged() -> None:
    pts = [
        ControlPoint("GCP-01", ControlRole.GCP, 0, 0, 0, _frame("LOCAL:a", LengthUnit.METER)),
        ControlPoint("CHK-01", ControlRole.CHECK, 1, 1, 1, _frame("LOCAL:a", LengthUnit.MILLIMETER)),
    ]
    issues = preflight_control(pts)
    assert any(i.code == "inconsistent_frame" and i.severity == "error" for i in issues)
