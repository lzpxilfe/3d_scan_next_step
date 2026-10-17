"""Synthetic tests for the honesty layer (observed/interpolated + survey/display).

SYNTHETIC only. These prove (05 §4): an export can never present interpolated
geometry as observed fact, and a display model is never labelled a survey record.
"""

from __future__ import annotations

import pytest

from archphoto.archaeo.surface import OriginKind, ProductKind
from archphoto.geom import LengthUnit, SpatialFrame
from archphoto.mesh import MeshProduct, mesh_sidecar


def _frame() -> SpatialFrame:
    return SpatialFrame(crs_id="LOCAL:t", unit=LengthUnit.MILLIMETER)


def _mesh(product=ProductKind.SURVEY) -> MeshProduct:
    # 3 vertices: 2 observed, 1 interpolated; 1 triangle
    return MeshProduct(
        vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
        faces=[(0, 1, 2)],
        origin=[OriginKind.OBSERVED, OriginKind.OBSERVED, OriginKind.INTERPOLATED],
        product_kind=product,
        frame=_frame(),
    )


def test_origin_length_must_match_vertices() -> None:
    with pytest.raises(ValueError):
        MeshProduct(
            vertices=[(0, 0, 0)],
            faces=[],
            origin=[],  # mismatch
            product_kind=ProductKind.SURVEY,
            frame=_frame(),
        )


def test_observed_fraction_and_counts() -> None:
    m = _mesh()
    assert m.observed_fraction() == pytest.approx(2 / 3)
    counts = m.count_by_origin()
    assert counts["observed"] == 2 and counts["interpolated"] == 1


def test_honesty_report_discloses_split() -> None:
    r = _mesh().honesty_report()
    assert r["product_kind"] == "survey"
    assert r["is_survey_record"] is True
    assert r["observed_vertices"] == 2 and r["interpolated_vertices"] == 1
    assert r["interpolated_fraction"] == pytest.approx(1 / 3)


def test_sidecar_carries_frame_and_honesty() -> None:
    s = mesh_sidecar(_mesh())
    assert s["product_kind"] == "survey"
    assert s["crs_id"] == "LOCAL:t" and s["unit"] == "mm"
    assert s["observed_fraction"] == pytest.approx(2 / 3)
    assert s["interpolated_vertices"] == 1  # interpolated geometry is disclosed


def test_display_mesh_is_not_a_survey_record() -> None:
    s = mesh_sidecar(_mesh(product=ProductKind.DISPLAY))
    assert s["product_kind"] == "display"
    assert s["is_survey_record"] is False


def test_mesh_rejects_out_of_range_face_indices() -> None:
    with pytest.raises(ValueError, match="out of bounds"):
        MeshProduct(
            vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
            faces=[(0, 1, 3)],
            origin=[OriginKind.OBSERVED] * 3,
            product_kind=ProductKind.SURVEY,
            frame=_frame(),
        )
