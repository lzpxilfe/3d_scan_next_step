"""Coordinate reference systems, vertical datums, and units.

Principle (AGENTS.md): the coordinate system, height reference, and units must be
explicit and never implied. Every geometry-bearing record references a
:class:`SpatialFrame`. Nothing here silently assumes a CRS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import sqrt
from typing import Optional


class LengthUnit(Enum):
    """Linear unit. Must be stated; never inferred from magnitude."""

    METER = "m"
    MILLIMETER = "mm"
    CENTIMETER = "cm"
    FOOT = "ft"


class AxisOrder(Enum):
    """Horizontal axis order of the coordinate tuple."""

    EAST_NORTH = "EN"  # x=easting, y=northing
    NORTH_EAST = "NE"


class VerticalDatum(Enum):
    """Height reference. Orthometric vs ellipsoidal must be distinguished."""

    ELLIPSOIDAL = "ellipsoidal"  # e.g. GPS height above reference ellipsoid
    ORTHOMETRIC = "orthometric"  # e.g. above mean sea level / national datum
    LOCAL = "local"  # site-local benchmark
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SpatialFrame:
    """The contract binding every coordinate to a real-world frame.

    Attributes:
        crs_id: CRS identifier, e.g. an EPSG code ("EPSG:5186") or "LOCAL:<name>".
            Use "LOCAL" for arbitrary site grids; never leave blank.
        unit: Length unit of all coordinates in this frame.
        axis_order: Horizontal axis order of the stored tuple.
        vertical_datum: Height reference. Must be explicit.
        geoid_model: Optional geoid/height model name when converting
            ellipsoidal <-> orthometric heights. Required whenever the two are
            mixed; otherwise leave None and DO NOT mix.
        description: Human-readable note (site, project, source of the CRS).
    """

    crs_id: str
    unit: LengthUnit
    axis_order: AxisOrder = AxisOrder.EAST_NORTH
    vertical_datum: VerticalDatum = VerticalDatum.UNKNOWN
    geoid_model: Optional[str] = None
    description: str = ""

    def __post_init__(self) -> None:
        if not self.crs_id:
            raise ValueError("SpatialFrame.crs_id must be set explicitly")

    def is_metric(self) -> bool:
        return self.unit in (LengthUnit.METER, LengthUnit.CENTIMETER, LengthUnit.MILLIMETER)


@dataclass(frozen=True)
class Transform3D:
    """Rigid transform from frame ``source`` to frame ``target``.

    Rotation is stored as a unit quaternion (x, y, z, w). Translation is
    expressed in ``target_frame.unit``. The transform is only meaningful when
    both frames are known; this class does not guess either.

    05 §3: the method, parameters, and version used for a coordinate transform
    must be recorded so results are reproducible. ``method`` / ``software_version``
    carry that provenance.
    """

    source: SpatialFrame
    target: SpatialFrame
    quaternion_xyzw: tuple[float, float, float, float]
    translation: tuple[float, float, float]
    method: str = ""  # e.g. "Helmert-7param", "similarity-RANSAC"
    software_version: str = ""  # code/engine version that computed this transform

    def apply(self, point: tuple[float, float, float]) -> tuple[float, float, float]:
        """Map ``point`` (in ``source`` frame) to the ``target`` frame.

        Convention (explicit, per 05 §3):
          1. The input is interpreted in ``source`` axis order and unit.
          2. Axis order is normalized to East-North.
          3. Coordinates are converted from ``source.unit`` to ``target.unit``.
          4. A unit-quaternion rotation is applied, then ``translation`` (in
             ``target.unit``) is added.
          5. The result is written in ``target`` axis order.

        Vertical datums are NOT mixed silently: if source and target datums
        differ, this raises, because converting ellipsoidal <-> orthometric
        heights needs an explicit geoid model that is not applied here.
        """
        if not self.source.crs_id or not self.target.crs_id:
            raise ValueError("Transform3D frames must have explicit crs_id")
        if self.source.vertical_datum is not self.target.vertical_datum:
            raise ValueError(
                "Vertical datums differ; a geoid/height transform is required and "
                "is not applied here. Refusing to mix height references silently."
            )

        x, y, z = point
        # 2. source axis order -> canonical East-North
        if self.source.axis_order is AxisOrder.NORTH_EAST:
            x, y = y, x
        # 3. unit conversion source -> target
        k = _unit_factor(self.source.unit, self.target.unit)
        x, y, z = x * k, y * k, z * k
        # 4. rotate + translate (translation is in target.unit)
        rx, ry, rz = _rotate_quat(self.quaternion_xyzw, (x, y, z))
        tx, ty, tz = self.translation
        rx, ry, rz = rx + tx, ry + ty, rz + tz
        # 5. canonical East-North -> target axis order
        if self.target.axis_order is AxisOrder.NORTH_EAST:
            rx, ry = ry, rx
        return (rx, ry, rz)


# Meters per unit, for linear conversion.
_TO_METERS: dict[LengthUnit, float] = {
    LengthUnit.METER: 1.0,
    LengthUnit.CENTIMETER: 0.01,
    LengthUnit.MILLIMETER: 0.001,
    LengthUnit.FOOT: 0.3048,
}


def _unit_factor(src: LengthUnit, dst: LengthUnit) -> float:
    """Multiply a ``src`` length by this to get the same length in ``dst``."""
    return _TO_METERS[src] / _TO_METERS[dst]


def _rotate_quat(
    quaternion_xyzw: tuple[float, float, float, float],
    v: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Rotate vector ``v`` by a unit quaternion (x, y, z, w)."""
    qx, qy, qz, qw = quaternion_xyzw
    norm = sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if norm == 0.0:
        raise ValueError("Quaternion has zero norm")
    qx, qy, qz, qw = qx / norm, qy / norm, qz / norm, qw / norm

    vx, vy, vz = v
    # t = 2 * cross(q.xyz, v)
    tx = 2.0 * (qy * vz - qz * vy)
    ty = 2.0 * (qz * vx - qx * vz)
    tz = 2.0 * (qx * vy - qy * vx)
    # v' = v + qw * t + cross(q.xyz, t)
    rx = vx + qw * tx + (qy * tz - qz * ty)
    ry = vy + qw * ty + (qz * tx - qx * tz)
    rz = vz + qw * tz + (qx * ty - qy * tx)
    return (rx, ry, rz)
