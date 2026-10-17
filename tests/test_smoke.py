"""Synthetic smoke tests for the scaffold's data contracts.

These are SYNTHETIC / unit tests. They exercise in-memory data structures and
invariants only. They are NOT real-data tests and NOT survey validation
(AGENTS.md: keep synthetic tests separate from real-data tests).

Run:  PYTHONPATH=src python -m pytest tests -q
"""

from __future__ import annotations

import pytest

import archphoto
from archphoto.geom import LengthUnit, SpatialFrame
from archphoto.recon import PipelineConfig
from archphoto.recon.depth import DepthRepresentation
from archphoto.runlog import ProcessState, RunRecord, ValidationState
from archphoto.sensing import ControlPoint, ControlRole, DerivedImage, PhotoObservation


def _frame() -> SpatialFrame:
    return SpatialFrame(crs_id="LOCAL:test", unit=LengthUnit.MILLIMETER)


def test_version_present() -> None:
    assert isinstance(archphoto.__version__, str) and archphoto.__version__


def test_spatial_frame_requires_crs() -> None:
    with pytest.raises(ValueError):
        SpatialFrame(crs_id="", unit=LengthUnit.METER)


def test_controlpoint_rejects_unknown_role() -> None:
    with pytest.raises(ValueError):
        ControlPoint("X1", ControlRole.UNKNOWN, 0.0, 0.0, 0.0, _frame())


def test_controlpoint_gcp_vs_check_flags() -> None:
    gcp = ControlPoint("GCP-01", ControlRole.GCP, 0.0, 0.0, 0.0, _frame())
    chk = ControlPoint("CHK-01", ControlRole.CHECK, 1.0, 1.0, 1.0, _frame())
    assert gcp.is_gcp and not gcp.is_check
    assert chk.is_check and not chk.is_gcp


def test_pipeline_config_rejects_gcp_check_overlap() -> None:
    with pytest.raises(ValueError):
        PipelineConfig(frame=_frame(), gcp_ids=("P1",), check_ids=("P1",))


def test_run_record_separates_process_and_validation() -> None:
    r = RunRecord(run_id="r1")
    r.mark_succeeded()
    # Processing succeeded but validation has not run: they stay distinct.
    assert r.is_processing_success is True
    assert r.is_survey_validated is False
    assert r.process_state is ProcessState.SUCCEEDED
    assert r.validation_state is ValidationState.NOT_RUN


def test_control_roles_separate_calibration_from_check() -> None:
    # 05 §2: only GCP/SCALE/CONSTRAINT constrain the model; CHECK* are independent.
    assert ControlRole.GCP.used_in_calibration is True
    assert ControlRole.SCALE.used_in_calibration is True
    assert ControlRole.CHECK.used_in_calibration is False
    assert ControlRole.CHECK_LENGTH.is_independent_check is True
    assert ControlRole.CHECK.is_independent_check is True
    assert ControlRole.GCP.is_independent_check is False


def test_pixel_observation_stays_separate_from_control_point() -> None:
    obs = PhotoObservation("GCP-01", "P-001", 1024.0, 768.0)
    assert obs.point_id == "GCP-01" and obs.photo_id == "P-001"
    with pytest.raises(ValueError):
        PhotoObservation("", "P-001", 0.0, 0.0)


def test_depth_representation_is_explicit() -> None:
    assert DepthRepresentation.Z_DEPTH is not DepthRepresentation.RAY_DISTANCE


def test_derived_image_requires_source_photo() -> None:
    d = DerivedImage("d1", "P-001", path="/tmp/d1.jpg")
    assert d.source_photo_id == "P-001"
    with pytest.raises(ValueError):
        DerivedImage("", "", path="/tmp/x.jpg")


def test_run_record_carries_provenance_fields() -> None:
    r = RunRecord(run_id="r2")
    assert r.engine_version == "" and r.code_version == "" and r.weight_version == ""
    assert r.retry_count == 0 and r.selected_views == ()


def test_project_manifest_verifies_raw_integrity_without_modifying_files(tmp_path) -> None:
    import hashlib
    from archphoto.project.manifest import ProjectManifest, RawItem

    raw_file = tmp_path / "IMG_001.jpg"
    payload = b"\xff\xd8original-bytes"
    raw_file.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()

    manifest = ProjectManifest(project_id="proj-1", raw_root=str(tmp_path))
    manifest.register_raw(
        RawItem(rel_path="IMG_001.jpg", sha256=digest, kind="photo", byte_size=len(payload))
    )
    assert manifest.verify_raw_integrity() == []
    assert raw_file.read_bytes() == payload

    # Simulate external tampering in temp dir: manifest must detect the mismatch
    raw_file.write_bytes(b"\xff\xd8tampered-bytes")
    assert manifest.verify_raw_integrity() == ["IMG_001.jpg"]
