"""Block / scan registration and stitching ("붙이기").

The reconstruction focus (DECISIONS D-2026-10-12-07): combine multiple blocks /
scans / features into one coherent, georeferenced whole — faithfully — and leave
fine mesh refinement to external tools. Good meshes come from honest stitching.

This module provides:
  - :class:`Block`            — one reconstructed piece (own frame, geometry, origin).
  - :func:`fit_rigid_transform` — closed-form (Horn/Umeyama) rotation+translation
    (+optional uniform scale) from corresponding points. Pure Python.
  - :func:`register_blocks`   — fit a block into a target frame using tie points,
    recording them in a :class:`PointUsageLedger` so they can never double as
    independent checks (05 §2).
  - :func:`apply_transform` / :func:`merge_blocks` — move a block and stitch
    registered blocks into one :class:`MeshProduct`, preserving observed/interpolated
    honesty.

No engine or real data needed: this is geometry + the honesty/separation rules,
testable synthetically.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from math import sqrt

from archphoto.archaeo.surface import OriginKind, ProductKind
from archphoto.geom.crs import SpatialFrame
from archphoto.mesh.product import MeshProduct
from archphoto.quality.ledger import PointUsageLedger

Point3D = tuple[float, float, float]


@dataclass
class Block:
    """One reconstructed piece in its own ``frame``.

    ``origin`` is per-vertex provenance (same length as ``vertices``) and is
    carried through registration and stitching so honesty survives.
    """

    block_id: str
    frame: SpatialFrame
    vertices: list[Point3D]
    faces: list[tuple[int, int, int]]
    origin: list[OriginKind]

    def __post_init__(self) -> None:
        if len(self.origin) != len(self.vertices):
            raise ValueError("origin length must match vertices length")


@dataclass(frozen=True)
class TiePoint:
    """A correspondence: ``src_point`` in the source block maps to ``dst_point``."""

    tie_id: str
    src_point: Point3D
    dst_point: Point3D


@dataclass
class RegistrationResult:
    """The fitted similarity transform (source -> target) and its fit quality.

    ``inlier_ids`` are ties consistent with the accepted model; ``rejected_ids``
    are ties treated as outliers (excluded from the fit). Only inliers are marked
    as model-fitting use in the ledger.
    """

    quaternion_xyzw: tuple[float, float, float, float]
    translation: Point3D
    scale: float
    residuals: dict[str, float]  # tie_id -> distance error at that tie
    rms: float
    inlier_ids: list[str] = field(default_factory=list)
    rejected_ids: list[str] = field(default_factory=list)


# --- linear algebra (pure Python) -------------------------------------------

def _apply_rot(r: list[list[float]], p: Point3D) -> Point3D:
    return (
        r[0][0] * p[0] + r[0][1] * p[1] + r[0][2] * p[2],
        r[1][0] * p[0] + r[1][1] * p[1] + r[1][2] * p[2],
        r[2][0] * p[0] + r[2][1] * p[1] + r[2][2] * p[2],
    )


def _quat_xyzw_to_rot(q: tuple[float, float, float, float]) -> list[list[float]]:
    x, y, z, w = q
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def apply_similarity(
    quaternion_xyzw: tuple[float, float, float, float],
    translation: Point3D,
    scale: float,
    p: Point3D,
) -> Point3D:
    """Apply ``scale * R * p + translation`` (the fitted source->target map)."""
    rp = _apply_rot(_quat_xyzw_to_rot(quaternion_xyzw), p)
    return (
        scale * rp[0] + translation[0],
        scale * rp[1] + translation[1],
        scale * rp[2] + translation[2],
    )


def _dominant_eigenvector_sym4(n: list[list[float]]) -> list[float]:
    """Dominant eigenvector of a symmetric 4x4 matrix (cyclic Jacobi).

    Jacobi is used (not power iteration) so the rotation is recovered precisely
    even when the dominant eigenvalue gap is small.
    """
    size = 4
    a = [row[:] for row in n]
    v = [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]
    for _ in range(100):
        off = sum(a[p][q] ** 2 for p in range(size) for q in range(p + 1, size))
        if off < 1e-30:
            break
        for p in range(size - 1):
            for q in range(p + 1, size):
                apq = a[p][q]
                if abs(apq) < 1e-300:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * apq)
                t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + sqrt(theta * theta + 1.0))
                c = 1.0 / sqrt(t * t + 1.0)
                s = t * c
                for i in range(size):
                    aip, aiq = a[i][p], a[i][q]
                    a[i][p] = c * aip - s * aiq
                    a[i][q] = s * aip + c * aiq
                for i in range(size):
                    api, aqi = a[p][i], a[q][i]
                    a[p][i] = c * api - s * aqi
                    a[q][i] = s * api + c * aqi
                for i in range(size):
                    vip, viq = v[i][p], v[i][q]
                    v[i][p] = c * vip - s * viq
                    v[i][q] = s * vip + c * viq
    eigvals = [a[i][i] for i in range(size)]
    k = max(range(size), key=lambda i: eigvals[i])
    vec = [v[i][k] for i in range(size)]
    norm = sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def fit_rigid_transform(
    src: list[Point3D], dst: list[Point3D], with_scale: bool = False
) -> tuple[tuple[float, float, float, float], Point3D, float]:
    """Closed-form best similarity mapping ``src[i] -> dst[i]`` (Horn / Umeyama).

    Returns (quaternion_xyzw, translation, scale). ``scale`` is 1 when
    ``with_scale`` is False. Needs at least 3 non-degenerate correspondences.
    """
    if len(src) != len(dst):
        raise ValueError("correspondence sets must have equal length")
    n = len(src)
    if n < 3:
        raise ValueError("need at least 3 correspondences")

    def _centroid(pts: list[Point3D]) -> Point3D:
        return (
            sum(p[0] for p in pts) / n,
            sum(p[1] for p in pts) / n,
            sum(p[2] for p in pts) / n,
        )

    mu_s, mu_d = _centroid(src), _centroid(dst)
    src_c = [(p[0] - mu_s[0], p[1] - mu_s[1], p[2] - mu_s[2]) for p in src]
    dst_c = [(p[0] - mu_d[0], p[1] - mu_d[1], p[2] - mu_d[2]) for p in dst]

    # cross-covariance H = mean of src_c (x) dst_c
    h = [[0.0] * 3 for _ in range(3)]
    for a, b in zip(src_c, dst_c):
        for i in range(3):
            for j in range(3):
                h[i][j] += a[i] * b[j]
    for i in range(3):
        for j in range(3):
            h[i][j] /= n

    hxx, hxy, hxz = h[0][0], h[0][1], h[0][2]
    hyx, hyy, hyz = h[1][0], h[1][1], h[1][2]
    hzx, hzy, hzz = h[2][0], h[2][1], h[2][2]

    # Horn's symmetric 4x4 matrix
    mat = [
        [hxx + hyy + hzz, hyz - hzy, hzx - hxz, hxy - hyx],
        [hyz - hzy, hxx - hyy - hzz, hxy + hyx, hzx + hxz],
        [hzx - hxz, hxy + hyx, -hxx + hyy - hzz, hyz + hzy],
        [hxy - hyx, hzx + hxz, hyz + hzy, -hxx - hyy + hzz],
    ]
    q0123 = _dominant_eigenvector_sym4(mat)  # (qw, qx, qy, qz)
    quat = (q0123[1], q0123[2], q0123[3], q0123[0])  # -> (x, y, z, w)

    rot = _quat_xyzw_to_rot(quat)
    if with_scale:
        num = 0.0
        den = 0.0
        for a, b in zip(src_c, dst_c):
            ra = _apply_rot(rot, a)
            num += ra[0] * b[0] + ra[1] * b[1] + ra[2] * b[2]
            den += a[0] * a[0] + a[1] * a[1] + a[2] * a[2]
        scale = (num / den) if den > 0 else 1.0
    else:
        scale = 1.0

    rmu = _apply_rot(rot, mu_s)
    translation = (
        mu_d[0] - scale * rmu[0],
        mu_d[1] - scale * rmu[1],
        mu_d[2] - scale * rmu[2],
    )
    return quat, translation, scale


# --- registration / stitching -----------------------------------------------

def register_blocks(
    ties: list[TiePoint],
    frame: SpatialFrame,
    ledger: PointUsageLedger | None = None,
    with_scale: bool = False,
) -> RegistrationResult:
    """Fit the source block into ``frame`` using ``ties`` (source->target).

    Every tie is recorded in ``ledger`` as ALIGNMENT use, so it can never later
    be reused as an independent check point (05 §2). Residuals at the ties report
    registration fit quality.
    """
    src = [t.src_point for t in ties]
    dst = [t.dst_point for t in ties]
    quat, translation, scale = fit_rigid_transform(src, dst, with_scale)

    residuals: dict[str, float] = {}
    for t in ties:
        predicted = apply_similarity(quat, translation, scale, t.src_point)
        residuals[t.tie_id] = _dist(predicted, t.dst_point)
        if ledger is not None:
            ledger.mark_alignment(t.tie_id)

    n = len(residuals) or 1
    rms = sqrt(sum(r * r for r in residuals.values()) / n)
    return RegistrationResult(
        quat, translation, scale, residuals, rms,
        inlier_ids=[t.tie_id for t in ties],
        rejected_ids=[],
    )


def register_blocks_ransac(
    ties: list[TiePoint],
    frame: SpatialFrame,
    inlier_threshold: float,
    ledger: PointUsageLedger | None = None,
    with_scale: bool = False,
    iterations: int = 200,
    seed: int = 0,
) -> RegistrationResult:
    """Robust registration ("붙이기") that rejects outlier tie points.

    Repeatedly fits to minimal 3-tie samples, keeps the model with the most
    inliers (ties within ``inlier_threshold``), refits on the inliers, and reports
    which ties were rejected. Sampling uses a seeded RNG so the result is
    reproducible (PERFORMANCE_GOALS §2.3). Only inliers are marked as model-fitting
    use in the ledger; rejected ties are not.

    ``inlier_threshold`` is in frame units and MUST be chosen for the data; it is
    not a validated default (tolerance is [O]).
    """
    if len(ties) < 3:
        raise ValueError("need at least 3 tie points for RANSAC registration")
    rng = random.Random(seed)
    n = len(ties)
    best_inliers: list[int] | None = None
    best_key: tuple[int, float] | None = None  # (inlier_count, -rms) to maximize

    for _ in range(iterations):
        sample = [ties[i] for i in rng.sample(range(n), 3)]
        try:
            quat, trans, scale = fit_rigid_transform(
                [t.src_point for t in sample], [t.dst_point for t in sample], with_scale
            )
        except ValueError:
            continue
        inliers = [
            i
            for i, t in enumerate(ties)
            if _dist(apply_similarity(quat, trans, scale, t.src_point), t.dst_point) < inlier_threshold
        ]
        if len(inliers) < 3:
            continue
        rms = sqrt(
            sum(
                _dist(apply_similarity(quat, trans, scale, ties[i].src_point), ties[i].dst_point) ** 2
                for i in inliers
            )
            / len(inliers)
        )
        key = (len(inliers), -rms)
        if best_key is None or key > best_key:
            best_key = key
            best_inliers = inliers

    if best_inliers is None:
        raise ValueError("RANSAC found no model with enough inliers")

    # refit on the best inlier set
    inlier_ties = [ties[i] for i in best_inliers]
    quat, trans, scale = fit_rigid_transform(
        [t.src_point for t in inlier_ties], [t.dst_point for t in inlier_ties], with_scale
    )

    residuals: dict[str, float] = {}
    inlier_ids: list[str] = []
    rejected_ids: list[str] = []
    for t in ties:
        d = _dist(apply_similarity(quat, trans, scale, t.src_point), t.dst_point)
        residuals[t.tie_id] = d
        if d < inlier_threshold:
            inlier_ids.append(t.tie_id)
        else:
            rejected_ids.append(t.tie_id)

    rms = (
        sqrt(sum(residuals[i] ** 2 for i in inlier_ids) / len(inlier_ids)) if inlier_ids else 0.0
    )
    if ledger is not None:
        for tid in inlier_ids:
            ledger.mark_alignment(tid)
    return RegistrationResult(
        quat, trans, scale, residuals, rms, inlier_ids=inlier_ids, rejected_ids=rejected_ids
    )


def apply_transform(block: Block, reg: RegistrationResult, frame: SpatialFrame) -> Block:
    """Return ``block`` moved into ``frame`` by the fitted registration transform."""
    verts = [apply_similarity(reg.quaternion_xyzw, reg.translation, reg.scale, v) for v in block.vertices]
    return Block(
        block_id=block.block_id,
        frame=frame,
        vertices=verts,
        faces=list(block.faces),
        origin=list(block.origin),
    )


def merge_blocks(
    blocks: list[Block], frame: SpatialFrame, product_kind: ProductKind = ProductKind.SURVEY
) -> MeshProduct:
    """Stitch registered blocks (all already in ``frame``) into one MeshProduct.

    Per-vertex origin is concatenated, so the honesty split survives the merge.
    """
    vertices: list[Point3D] = []
    faces: list[tuple[int, int, int]] = []
    origin: list[OriginKind] = []
    offset = 0
    for b in blocks:
        if b.frame.crs_id != frame.crs_id:
            raise ValueError(f"block {b.block_id!r} is not in the target frame; register it first")
        vertices.extend(b.vertices)
        origin.extend(b.origin)
        for i, j, k in b.faces:
            faces.append((i + offset, j + offset, k + offset))
        offset += len(b.vertices)
    return MeshProduct(vertices, faces, origin, product_kind, frame)


def _dist(a: Point3D, b: Point3D) -> float:
    return sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)
