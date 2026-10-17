"""Section / profile computation and the computed-vs-interpreted distinction.

05 §4 requires separating the COMPUTED section line (derived from the model by
cutting with a plane) from the researcher's INTERPRETED line (e.g. a stratigraphic
reading). Both are kept as :class:`SectionLine` with an explicit
:class:`LineOrigin`, so a reader can never mistake interpretation for measurement.

When a section is cut from a mesh that carries per-vertex origin (see
:func:`archphoto.mesh.product.MeshProduct`), each segment is also tagged
OBSERVED/INTERPOLATED by the face it came from, so a section through a filled-in
region is honestly flagged as derived from interpolated geometry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from archphoto.archaeo.surface import OriginKind
from archphoto.geom.crs import SpatialFrame
from archphoto.geom.plane import Plane

Point3D = tuple[float, float, float]
Segment = tuple[Point3D, Point3D]


class LineOrigin(Enum):
    """Where a line came from — measurement-derived vs human interpretation."""

    COMPUTED = "computed"  # 계산된 단면선 (cut from the model)
    INTERPRETED = "interpreted"  # 연구자 해석선 (e.g. 토층 판독선)


@dataclass
class SectionLine:
    """A set of 3D segments with an explicit origin and spatial frame."""

    segments: list[Segment]
    origin: LineOrigin
    frame: SpatialFrame
    segment_origin: list[OriginKind] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.segment_origin and len(self.segment_origin) != len(self.segments):
            raise ValueError("segment_origin length must match segments length")

    @property
    def is_computed(self) -> bool:
        return self.origin is LineOrigin.COMPUTED

    @property
    def is_interpreted(self) -> bool:
        return self.origin is LineOrigin.INTERPRETED


def compute_section(
    vertices: list[Point3D],
    faces: list[tuple[int, int, int]],
    plane: Plane,
    vertex_origin: list[OriginKind] | None = None,
    tol: float = 1e-9,
) -> SectionLine:
    """Cut ``faces`` with ``plane`` and return the computed section line.

    Each triangle that straddles the plane contributes one segment. If
    ``vertex_origin`` is given, a segment is tagged OBSERVED only when ALL three
    vertices of the cut triangle are OBSERVED; any interpolated vertex on the
    face tags the segment INTERPOLATED so hole-fill boundary triangles are never
    presented as observed fact.
    """
    segments: list[Segment] = []
    seg_origin: list[OriginKind] = []
    for f in faces:
        v0, v1, v2 = vertices[f[0]], vertices[f[1]], vertices[f[2]]
        pts = _dedupe(_tri_plane_points(v0, v1, v2, plane, tol), tol)
        if len(pts) >= 2:
            segments.append((pts[0], pts[1]))
            if vertex_origin is not None:
                face_origins = (vertex_origin[f[0]], vertex_origin[f[1]], vertex_origin[f[2]])
                seg_origin.append(
                    OriginKind.OBSERVED
                    if all(o is OriginKind.OBSERVED for o in face_origins)
                    else OriginKind.INTERPOLATED
                )
    return SectionLine(segments, LineOrigin.COMPUTED, plane.frame, seg_origin)


def interpretation_line(strokes: list[Segment], frame: SpatialFrame) -> SectionLine:
    """Wrap a researcher's interpretive strokes as an INTERPRETED section line."""
    return SectionLine(list(strokes), LineOrigin.INTERPRETED, frame)


def _tri_plane_points(
    v0: Point3D, v1: Point3D, v2: Point3D, plane: Plane, tol: float
) -> list[Point3D]:
    verts = (v0, v1, v2)
    d = (plane.signed_distance(v0), plane.signed_distance(v1), plane.signed_distance(v2))
    if abs(d[0]) <= tol and abs(d[1]) <= tol and abs(d[2]) <= tol:
        return []
    pts: list[Point3D] = []
    for i in range(3):
        j = (i + 1) % 3
        di, dj = d[i], d[j]
        if abs(di) <= tol and abs(dj) <= tol:
            pts.append(verts[i])
            pts.append(verts[j])  # edge lies on the plane
        elif abs(di) <= tol:
            pts.append(verts[i])  # vertex on the plane
        elif di * dj < 0:  # edge crosses the plane
            t = di / (di - dj)
            pi, pj = verts[i], verts[j]
            pts.append(
                (
                    pi[0] + t * (pj[0] - pi[0]),
                    pi[1] + t * (pj[1] - pi[1]),
                    pi[2] + t * (pj[2] - pi[2]),
                )
            )
    return pts


def _dedupe(pts: list[Point3D], tol: float) -> list[Point3D]:
    out: list[Point3D] = []
    for p in pts:
        if not any(
            abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol and abs(p[2] - q[2]) <= tol
            for q in out
        ):
            out.append(p)
    return out
