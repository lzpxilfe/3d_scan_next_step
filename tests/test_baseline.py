"""Synthetic tests for baseline reconstruction orchestration. SYNTHETIC only.

A fake engine exercises the flow's invariants (GCP/check separation, honest run
record) without any real engine or data.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from archphoto.geom import LengthUnit, SpatialFrame
from archphoto.recon.baseline import BaselineInputs, BaselineRunner
from archphoto.runlog import ProcessState, ValidationState
from archphoto.sensing import ControlPoint, ControlRole


def _frame() -> SpatialFrame:
    return SpatialFrame(crs_id="LOCAL:t", unit=LengthUnit.MILLIMETER)


class FakeEngine:
    """Returns reconstructed coords exactly at surveyed positions."""

    def reconstruct(self, inputs):
        return {p.point_id: (p.x, p.y, p.z) for p in inputs.control_points}


class OffsetEngine:
    """Returns coordinates offset by 1 unit to produce a non-zero residual."""

    def reconstruct(self, inputs):
        return {p.point_id: (p.x + 1.0, p.y, p.z) for p in inputs.control_points}


def _inputs() -> BaselineInputs:
    pts = [
        ControlPoint("GCP-01", ControlRole.GCP, 0.0, 0.0, 0.0, _frame()),
        ControlPoint("CHK-01", ControlRole.CHECK, 10.0, 10.0, 10.0, _frame()),
    ]
    return BaselineInputs(
        control_points=pts,
        frame=_frame(),
        gcp_ids=("GCP-01",),
        check_ids=("CHK-01",),
        input_hashes={"P-001": "abc"},
    )


def test_baseline_flow_happy_path() -> None:
    result = BaselineRunner(FakeEngine()).run(_inputs())
    assert result.constraint.applied == ["GCP-01"]
    assert result.validation.residuals["CHK-01"] == (0.0, 0.0, 0.0)
    assert result.run.process_state is ProcessState.SUCCEEDED
    # pass/fail needs a tolerance that is still [O], so validation stays NOT_RUN
    assert result.run.validation_state is ValidationState.NOT_RUN
    assert result.run.input_hashes == {"P-001": "abc"}


def test_baseline_nonzero_residual_computed() -> None:
    result = BaselineRunner(OffsetEngine()).run(_inputs())
    assert result.validation.residuals["CHK-01"] == (1.0, 0.0, 0.0)
    assert result.validation.distances["CHK-01"] == pytest.approx(1.0)


def test_baseline_rejects_gcp_check_overlap() -> None:
    inp = _inputs()
    inp.gcp_ids = ("GCP-01", "CHK-01")
    inp.check_ids = ("CHK-01",)
    with pytest.raises(ValueError):
        BaselineRunner(FakeEngine()).run(inp)


def test_baseline_requires_engine() -> None:
    with pytest.raises(RuntimeError):
        BaselineRunner(None).run(_inputs())


def test_baseline_aborts_on_preflight_error() -> None:
    inp = _inputs()
    bad = SimpleNamespace(
        point_id="BAD",
        role=ControlRole.UNKNOWN,
        frame=SimpleNamespace(crs_id="", unit=None),
    )
    inp.control_points = [bad]
    with pytest.raises(ValueError):
        BaselineRunner(FakeEngine()).run(inp)
