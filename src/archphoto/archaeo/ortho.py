"""Orthophoto projection and grid (고고학 산출물: 정사영상).

An orthophoto is an orthographic (parallel) projection of geometry onto a plane,
so distances are metric and there is no perspective distortion — unlike a normal
photo. This module provides the geometric core:

  - :class:`OrthoSpec`  — where the projection plane and its in-plane (u, v) axes
    are, so 3D points map to metric 2D coordinates.
  - :class:`OrthoGrid`  — the pixel grid with a real-unit resolution (pixels<->units).
  - :class:`OrthoProduct` — projected points carrying the honesty axes, so a cell
    backed by interpolated geometry is never presented as measured.

Texture/color rasterization is not done here (that needs imagery); this is the
metric projection + grid + honesty, which is what makes an ortho a survey
deliverable and is testable without an engine or real data.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt

from archphoto.archaeo.surface import OriginKind, ProductKind
from archphoto.geom.crs import SpatialFrame

Point3D = tuple[float, float, float]
Point2D = tuple[float, float]


def _normalize(v: Point3D) -> Point3D:
    if not all(isfinite(c) for c in v):
        raise ValueError("axis vector components must be finite")
    n = sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if n == 0.0 or not isfinite(n):
        raise ValueError("axis vector must be non-zero")
    return (v[0] / n, v[1] / n, v[2] / n)


@dataclass
class OrthoSpec:
    """Projection plane given by ``origin`` and in-plane unit axes ``u_axis``/``v_axis``.

    ``project`` is an orthographic projection: it drops the component along the
    plane normal (u_axis x v_axis), giving metric (u, v) in ``frame`` units.
    """

    origin: Point3D
    u_axis: Point3D
    v_axis: Point3D
    frame: SpatialFrame

    def __post_init__(self) -> None:
        if not all(isfinite(c) for c in self.origin):
            raise ValueError("OrthoSpec origin coordinates must be finite")
        self.u_axis = _normalize(self.u_axis)
        self.v_axis = _normalize(self.v_axis)
        dot = (
            self.u_axis[0] * self.v_axis[0]
            + self.u_axis[1] * self.v_axis[1]
            + self.u_axis[2] * self.v_axis[2]
        )
        if abs(dot) > 1e-6:
            raise ValueError("OrthoSpec u_axis and v_axis must be orthogonal")

    def project(self, p: Point3D) -> Point2D:
        dx = p[0] - self.origin[0]
        dy = p[1] - self.origin[1]
        dz = p[2] - self.origin[2]
        ux, uy, uz = self.u_axis
        vx, vy, vz = self.v_axis
        u = dx * ux + dy * uy + dz * uz
        v = dx * vx + dy * vy + dz * vz
        return (u, v)


@dataclass
class OrthoGrid:
    """Pixel grid with a metric resolution (frame units per pixel)."""

    origin_uv: Point2D
    resolution: float
    width_px: int
    height_px: int
    frame: SpatialFrame

    def __post_init__(self) -> None:
        if not all(isfinite(c) for c in self.origin_uv) or not isfinite(self.resolution):
            raise ValueError("OrthoGrid origin_uv and resolution must be finite")
        if self.resolution <= 0:
            raise ValueError("resolution must be positive")
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("grid size must be positive")

    def uv_to_pixel(self, u: float, v: float) -> Point2D:
        col = (u - self.origin_uv[0]) / self.resolution
        row = (v - self.origin_uv[1]) / self.resolution
        return (col, row)

    def pixel_to_uv(self, col: float, row: float) -> Point2D:
        u = self.origin_uv[0] + col * self.resolution
        v = self.origin_uv[1] + row * self.resolution
        return (u, v)

    def extent(self) -> tuple[Point2D, Point2D]:
        """Axis-aligned bounds ((u_min, v_min), (u_max, v_max)) of the grid."""
        u0, v0 = self.pixel_to_uv(0, 0)
        u1, v1 = self.pixel_to_uv(self.width_px, self.height_px)
        return ((min(u0, u1), min(v0, v1)), (max(u0, u1), max(v0, v1)))


@dataclass
class OrthoProduct:
    """Projected 2D points with per-point provenance and product purpose.

    Mirrors the honesty contract of :class:`archphoto.mesh.product.MeshProduct`:
    interpolated geometry is disclosed and a display ortho is not a survey record.
    """

    points_uv: list[Point2D]
    origin: list[OriginKind]
    product_kind: ProductKind
    spec: OrthoSpec
    grid: OrthoGrid

    def __post_init__(self) -> None:
        if len(self.origin) != len(self.points_uv):
            raise ValueError("origin length must match points_uv length")
        if self.spec.frame != self.grid.frame:
            raise ValueError("OrthoProduct spec.frame and grid.frame must match")

    def honesty_report(self) -> dict:
        total = len(self.origin)
        observed = sum(1 for o in self.origin if o is OriginKind.OBSERVED)
        return {
            "product_kind": self.product_kind.value,
            "is_survey_record": self.product_kind is ProductKind.SURVEY,
            "point_count": total,
            "observed_points": observed,
            "interpolated_points": total - observed,
            "observed_fraction": (observed / total) if total else 0.0,
            "unit": self.grid.frame.unit.value,
            "crs_id": self.grid.frame.crs_id,
        }
