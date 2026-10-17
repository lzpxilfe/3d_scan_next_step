"""Synthetic input/coordinate tests (T05).

SYNTHETIC only — these exercise in-memory contracts and schema shapes. They are
NOT real-data tests and NOT survey validation (AGENTS.md keeps these separate).
No external dependency is used (jsonschema is intentionally not assumed).

Scope mirrors 05 §T05: units, axes, photo transforms, and CHECK-point exclusion.
Run:  PYTHONPATH=src python -m pytest tests -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from archphoto.geom import AxisOrder, LengthUnit, SpatialFrame, Transform3D, VerticalDatum
from archphoto.recon import PipelineConfig
from archphoto.recon.depth import DepthRepresentation
from archphoto.sensing import (
    ControlPoint,
    ControlRole,
    DerivedImage,
    PhotoObservation,
    ProcessingStep,
)
from archphoto.quality import validate_checkpoints

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "data" / "schemas"


def _frame() -> SpatialFrame:
    return SpatialFrame(crs_id="LOCAL:test", unit=LengthUnit.MILLIMETER)


# ---- units / CRS -----------------------------------------------------------

def test_crs_id_is_never_blank() -> None:
    with pytest.raises(ValueError):
        SpatialFrame(crs_id="", unit=LengthUnit.METER)


def test_unit_is_explicit_and_metric_flag() -> None:
    metric = SpatialFrame(crs_id="EPSG:5186", unit=LengthUnit.METER)
    imperial = SpatialFrame(crs_id="EPSG:2263", unit=LengthUnit.FOOT)
    assert metric.is_metric() is True
    assert imperial.is_metric() is False


def test_vertical_datum_and_axis_order_are_named() -> None:
    f = SpatialFrame(
        crs_id="LOCAL:s",
        unit=LengthUnit.METER,
        axis_order=AxisOrder.NORTH_EAST,
        vertical_datum=VerticalDatum.ORTHOMETRIC,
        geoid_model="KVD2021",
    )
    assert f.axis_order is AxisOrder.NORTH_EAST
    assert f.vertical_datum is VerticalDatum.ORTHOMETRIC
    assert f.geoid_model == "KVD2021"


# ---- axes / transform provenance ------------------------------------------

def test_transform_records_method_and_version() -> None:
    t = Transform3D(
        source=_frame(),
        target=_frame(),
        quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
        translation=(0.0, 0.0, 0.0),
        method="similarity-RANSAC",
        software_version="archphoto 0.0.1",
    )
    assert t.method == "similarity-RANSAC" and t.software_version


def test_transform_applies_rotation_and_translation() -> None:
    half = 0.7071067811865476  # 90° about Z
    t = Transform3D(_frame(), _frame(), (0, 0, half, half), (10.0, 0.0, 0.0))
    rx, ry, rz = t.apply((1.0, 0.0, 0.0))
    assert (rx, ry, rz) == pytest.approx((10.0, 1.0, 0.0))


def test_transform_converts_units() -> None:
    src = SpatialFrame(crs_id="LOCAL:a", unit=LengthUnit.MILLIMETER)
    dst = SpatialFrame(crs_id="LOCAL:b", unit=LengthUnit.METER)
    t = Transform3D(src, dst, (0, 0, 0, 1), (0.0, 0.0, 0.0))
    assert t.apply((1000.0, 2000.0, 500.0)) == pytest.approx((1.0, 2.0, 0.5))


def test_transform_axis_order_swap() -> None:
    src = SpatialFrame(crs_id="LOCAL:a", unit=LengthUnit.METER, axis_order=AxisOrder.NORTH_EAST)
    dst = SpatialFrame(crs_id="LOCAL:b", unit=LengthUnit.METER, axis_order=AxisOrder.EAST_NORTH)
    t = Transform3D(src, dst, (0, 0, 0, 1), (0, 0, 0))
    rx, ry, rz = t.apply((5.0, 7.0, 0.0))  # NE in -> EN out
    assert (rx, ry) == pytest.approx((7.0, 5.0))


def test_transform_refuses_mixed_vertical_datum() -> None:
    src = SpatialFrame(crs_id="LOCAL:a", unit=LengthUnit.METER, vertical_datum=VerticalDatum.ELLIPSOIDAL)
    dst = SpatialFrame(crs_id="LOCAL:b", unit=LengthUnit.METER, vertical_datum=VerticalDatum.ORTHOMETRIC)
    t = Transform3D(src, dst, (0, 0, 0, 1), (0, 0, 0))
    with pytest.raises(ValueError):
        t.apply((0.0, 0.0, 0.0))


# ---- photo transforms (derived image) -------------------------------------

def test_derived_image_links_source_and_scale() -> None:
    d = DerivedImage(
        derived_id="d1",
        source_photo_id="P-001",
        path="/tmp/d1.jpg",
        steps=(ProcessingStep.DOWNSCALE, ProcessingStep.UNDISTORT),
        scale_to_original=0.5,
    )
    assert d.source_photo_id == "P-001"
    assert d.scale_to_original == 0.5
    assert ProcessingStep.UNDISTORT in d.steps


# ---- CHECK-point exclusion (05 §2) ----------------------------------------

def test_check_role_never_calibrates() -> None:
    assert ControlRole.CHECK.used_in_calibration is False
    assert ControlRole.CHECK.is_independent_check is True
    assert ControlRole.GCP.used_in_calibration is True
    assert ControlRole.GCP.is_independent_check is False


def test_validate_checkpoints_rejects_gcp() -> None:
    gcp = ControlPoint("GCP-01", ControlRole.GCP, 0, 0, 0, _frame())
    with pytest.raises(ValueError):
        validate_checkpoints(model=None, check_points=[gcp])


def test_pipeline_rejects_gcp_check_overlap() -> None:
    with pytest.raises(ValueError):
        PipelineConfig(frame=_frame(), gcp_ids=("P1", "P2"), check_ids=("P2",))


def test_missing_height_is_not_defaulted() -> None:
    # z is required positionally; omitting it must fail rather than become 0.0.
    with pytest.raises(TypeError):
        ControlPoint("P", ControlRole.GCP, 1.0, 2.0, frame=_frame())  # type: ignore[call-arg]


# ---- schema shapes (pure Python, no jsonschema) ---------------------------

def _load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def test_control_schema_roles_exclude_unknown() -> None:
    schema = _load("control_points.schema.json")
    role = schema["properties"]["points"]["items"]["properties"]["role"]
    assert "unknown" not in role["enum"]
    assert {"gcp", "check", "scale", "check_length"} <= set(role["enum"])


def test_observations_schema_is_separate_from_geometry() -> None:
    schema = _load("observations.schema.json")
    props = schema["properties"]["observations"]["items"]["properties"]
    assert {"point_id", "photo_id", "x_px", "y_px"} <= set(props)
    assert "x" not in props and "z" not in props  # no world coords here


def test_run_record_schema_separates_process_and_validation() -> None:
    schema = _load("run_record.schema.json")
    req = set(schema["required"])
    assert {"run_id", "process_state", "validation_state"} <= req
    assert "passed" in schema["properties"]["validation_state"]["enum"]
    assert "succeeded" in schema["properties"]["process_state"]["enum"]


def test_depth_representation_is_explicit() -> None:
    assert DepthRepresentation.Z_DEPTH is not DepthRepresentation.RAY_DISTANCE
