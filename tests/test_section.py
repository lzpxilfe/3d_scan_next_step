"""Synthetic tests for section/profile computation (T: 고고학 산출물). SYNTHETIC only.

Proves (05 §4): the computed section line is distinct from the researcher's
interpreted line, and a section through interpolated geometry is flagged.
"""

from __future__ import annotations

import pytest

from archphoto.archaeo import (
    LineOrigin,
    OriginKind,
    compute_section,
    interpretation_line,
)
from archphoto.geom import LengthUnit, Plane, SpatialFrame


def _frame() -> SpatialFrame:
    return SpatialFrame(crs_id="LOCAL:t", unit=LengthUnit.MILLIMETER)


def _zplane() -> Plane:
    return Plane(point=(0, 0, 0), normal=(0, 0, 1), frame=_frame())


def test_plane_normal_is_normalized() -> None:
    p = Plane(point=(0, 0, 0), normal=(0, 0, 5), frame=_frame())
    assert p.normal == pytest.approx((0, 0, 1))
    assert p.signed_distance((0, 0, 3)) == pytest.approx(3.0)


def test_single_triangle_crossing_gives_one_segment_on_plane() -> None:
    verts = [(0, 0, -1), (1, 0, 1), (0, 1, 1)]
    faces = [(0, 1, 2)]
    sec = compute_section(verts, faces, _zplane())
    assert sec.is_computed is True
    assert len(sec.segments) == 1
    a, b = sec.segments[0]
    assert a[2] == pytest.approx(0.0) and b[2] == pytest.approx(0.0)


def test_triangle_above_plane_gives_no_segment() -> None:
    verts = [(0, 0, 1), (1, 0, 1), (0, 1, 1)]
    sec = compute_section(verts, [(0, 1, 2)], _zplane())
    assert sec.segments == []


def test_interpolated_face_is_flagged_in_section() -> None:
    verts = [(0, 0, -1), (1, 0, 1), (0, 1, 1)]
    faces = [(0, 1, 2)]
    # all three vertices interpolated -> segment flagged INTERPOLATED
    origin = [OriginKind.INTERPOLATED] * 3
    sec = compute_section(verts, faces, _zplane(), vertex_origin=origin)
    assert sec.segment_origin == [OriginKind.INTERPOLATED]


def test_observed_vertex_makes_segment_observed() -> None:
    verts = [(0, 0, -1), (1, 0, 1), (0, 1, 1)]
    origin = [OriginKind.OBSERVED, OriginKind.INTERPOLATED, OriginKind.INTERPOLATED]
    sec = compute_section(verts, [(0, 1, 2)], _zplane(), vertex_origin=origin)
    assert sec.segment_origin == [OriginKind.OBSERVED]


def test_interpretation_line_is_not_computed() -> None:
    strokes = [((0, 0, 0), (1, 0, 0))]
    line = interpretation_line(strokes, _frame())
    assert line.is_interpreted is True and line.is_computed is False
    assert len(line.segments) == 1
