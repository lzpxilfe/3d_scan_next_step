"""Synthetic tests for orthophoto projection + grid + honesty. SYNTHETIC only."""

from __future__ import annotations

import pytest

from archphoto.archaeo import (
    OriginKind,
    OrthoGrid,
    OrthoProduct,
    OrthoSpec,
    ProductKind,
)
from archphoto.geom import LengthUnit, SpatialFrame


def _frame() -> SpatialFrame:
    return SpatialFrame(crs_id="LOCAL:t", unit=LengthUnit.MILLIMETER)


def _spec() -> OrthoSpec:
    # Orthographic plan view: u=x, v=y, drops z.
    return OrthoSpec(origin=(0, 0, 0), u_axis=(1, 0, 0), v_axis=(0, 1, 0), frame=_frame())


def test_axes_are_normalized() -> None:
    s = OrthoSpec(origin=(0, 0, 0), u_axis=(5, 0, 0), v_axis=(0, 2, 0), frame=_frame())
    assert s.u_axis == pytest.approx((1, 0, 0)) and s.v_axis == pytest.approx((0, 1, 0))


def test_project_drops_depth_component() -> None:
    s = _spec()
    assert s.project((3.0, 4.0, 9.0)) == pytest.approx((3.0, 4.0))  # z ignored


def test_grid_pixel_uv_round_trip() -> None:
    g = OrthoGrid(origin_uv=(0.0, 0.0), resolution=2.0, width_px=10, height_px=10, frame=_frame())
    assert g.uv_to_pixel(4.0, 6.0) == pytest.approx((2.0, 3.0))
    assert g.pixel_to_uv(2.0, 3.0) == pytest.approx((4.0, 6.0))


def test_grid_extent() -> None:
    g = OrthoGrid(origin_uv=(0.0, 0.0), resolution=1.0, width_px=5, height_px=4, frame=_frame())
    (umin, vmin), (umax, vmax) = g.extent()
    assert (umin, vmin) == pytest.approx((0.0, 0.0))
    assert (umax, vmax) == pytest.approx((5.0, 4.0))


def test_ortho_honesty_report_discloses_split() -> None:
    spec = _spec()
    grid = OrthoGrid(origin_uv=(0, 0), resolution=1.0, width_px=4, height_px=4, frame=_frame())
    op = OrthoProduct(
        points_uv=[(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)],
        origin=[OriginKind.OBSERVED, OriginKind.OBSERVED, OriginKind.INTERPOLATED],
        product_kind=ProductKind.SURVEY,
        spec=spec,
        grid=grid,
    )
    r = op.honesty_report()
    assert r["observed_points"] == 2 and r["interpolated_points"] == 1
    assert r["observed_fraction"] == pytest.approx(2 / 3)
    assert r["is_survey_record"] is True and r["unit"] == "mm"
