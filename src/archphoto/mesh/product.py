"""MeshProduct: a mesh that carries the honesty axes into every output.

A :class:`MeshProduct` holds vertices, faces, a per-vertex :class:`OriginKind`
(observed vs interpolated), and a whole-model :class:`ProductKind` (survey vs
display). This is what lets downstream consumers — and us — tell measured
geometry from filled-in geometry, and a survey record from an exhibition model
(05 §4, PERFORMANCE_GOALS §2.1).

The honesty is enforced structurally: ``mesh_sidecar`` always discloses the
observed/interpolated breakdown and the product kind, so an export can never
present interpolated geometry as observed fact.
"""

from __future__ import annotations

from dataclasses import dataclass

from archphoto.archaeo.surface import OriginKind, ProductKind
from archphoto.geom.crs import SpatialFrame

Point3D = tuple[float, float, float]


@dataclass
class MeshProduct:
    """A mesh with per-vertex provenance and a product purpose.

    Attributes:
        vertices: 3D vertices in ``frame`` unit.
        faces: Triangles as vertex-index triples.
        origin: Per-vertex :class:`OriginKind` (same length as ``vertices``).
        product_kind: :class:`ProductKind` for the whole model.
        frame: The SpatialFrame (CRS/unit/datum) the coordinates refer to.
    """

    vertices: list[Point3D]
    faces: list[tuple[int, int, int]]
    origin: list[OriginKind]
    product_kind: ProductKind
    frame: SpatialFrame

    def __post_init__(self) -> None:
        if len(self.origin) != len(self.vertices):
            raise ValueError("origin length must match vertices length")
        if self.product_kind not in (ProductKind.SURVEY, ProductKind.DISPLAY):
            raise ValueError("product_kind must be SURVEY or DISPLAY")

    def observed_fraction(self) -> float:
        if not self.origin:
            return 0.0
        return sum(1 for o in self.origin if o is OriginKind.OBSERVED) / len(self.origin)

    def count_by_origin(self) -> dict[str, int]:
        counts = {OriginKind.OBSERVED.value: 0, OriginKind.INTERPOLATED.value: 0}
        for o in self.origin:
            counts[o.value] += 1
        return counts

    def honesty_report(self) -> dict:
        """A truthfulness summary: product purpose + observed/interpolated split."""
        counts = self.count_by_origin()
        total = len(self.origin)
        return {
            "product_kind": self.product_kind.value,
            "is_survey_record": self.product_kind is ProductKind.SURVEY,
            "vertex_count": total,
            "observed_vertices": counts[OriginKind.OBSERVED.value],
            "interpolated_vertices": counts[OriginKind.INTERPOLATED.value],
            "observed_fraction": self.observed_fraction(),
            "interpolated_fraction": (counts[OriginKind.INTERPOLATED.value] / total) if total else 0.0,
        }


def mesh_sidecar(mesh: MeshProduct) -> dict:
    """The honesty + spatial metadata that MUST accompany any mesh export.

    Returning this dict is the mechanism by which the observed/interpolated and
    survey/display distinctions survive to the consumer. A real writer would emit
    this next to the mesh file; the point is that it is always produced and never
    omits the split.
    """
    report = mesh.honesty_report()
    return {
        "product_kind": report["product_kind"],
        "is_survey_record": report["is_survey_record"],
        "crs_id": mesh.frame.crs_id,
        "unit": mesh.frame.unit.value,
        "vertical_datum": mesh.frame.vertical_datum.value,
        "vertex_count": report["vertex_count"],
        "face_count": len(mesh.faces),
        "observed_vertices": report["observed_vertices"],
        "interpolated_vertices": report["interpolated_vertices"],
        "observed_fraction": report["observed_fraction"],
        "interpolated_fraction": report["interpolated_fraction"],
    }
