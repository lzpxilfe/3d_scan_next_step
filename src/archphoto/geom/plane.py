"""A plane primitive for section/profile cutting.

A plane is a point plus a unit normal in a stated SpatialFrame. Used to cut
meshes into archaeological sections (05 §4: 계산된 단면선).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt

from archphoto.geom.crs import SpatialFrame

Point3D = tuple[float, float, float]


@dataclass
class Plane:
    """A plane: ``normal`` (normalized) at ``point``, in ``frame`` coordinates."""

    point: Point3D
    normal: Point3D
    frame: SpatialFrame

    def __post_init__(self) -> None:
        if not all(isfinite(v) for v in self.point) or not all(isfinite(v) for v in self.normal):
            raise ValueError("Plane point and normal coordinates must be finite")
        nx, ny, nz = self.normal
        n = sqrt(nx * nx + ny * ny + nz * nz)
        if n == 0.0 or not isfinite(n):
            raise ValueError("Plane normal must be non-zero")
        self.normal = (nx / n, ny / n, nz / n)

    def signed_distance(self, p: Point3D) -> float:
        """Positive on the normal side, negative on the other, 0 on the plane."""
        nx, ny, nz = self.normal
        return nx * (p[0] - self.point[0]) + ny * (p[1] - self.point[1]) + nz * (p[2] - self.point[2])
