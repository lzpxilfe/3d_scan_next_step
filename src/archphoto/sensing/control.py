"""Survey control points: GCP vs. independent checkpoints (and scale standards).

PRINCIPLE (AGENTS.md + 05 §2, non-negotiable): Ground Control Points (GCP) and
independent check points are SEPARATE. Check points MUST NOT be used to
calibrate / constrain the solution and then also reported as if they were an
independent accuracy measure. The :class:`ControlRole` enum makes the role
explicit and the validation layer enforces the separation.

05 §2 additionally separates scale standards from check standards:
  - SCALE        : used to determine scale (e.g. a scale bar). Its residual is
                   NOT an independent validation value.
  - CHECK_LENGTH : an independent distance used ONLY for dimension validation,
                   excluded from scale determination.

05 §2 also requires that a point's own coordinates/uncertainty be stored
SEPARATELY from its per-photo pixel observations. Pixel observations live in
:mod:`archphoto.sensing.observations`, not here.

Coordinates are always expressed in a stated :class:`~archphoto.geom.crs.SpatialFrame`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ControlRole(Enum):
    """Role of a surveyed point/standard. This is the enforcement hook for separation.

    Map to 05 §2 table:
      GCP         -> 좌표·축척·보정 구속에 사용 (잔차 보고하되 독립 검증 혼용 금지)
      CHECK       -> 구성·보정에서 제외, 좌표 오차 평가
      SCALE       -> 축척 결정에 사용 (기준척), 별도 검증 거리 마련
      CHECK_LENGTH-> 축척 결정에서 제외, 치수 검증용 독립 검증 길이
    """

    GCP = "gcp"
    CHECK = "check"
    SCALE = "scale"
    CHECK_LENGTH = "check_length"
    CONSTRAINT = "constraint"  # generic non-GCP constraint (scale/distance/orientation)
    UNKNOWN = "unknown"

    @property
    def used_in_calibration(self) -> bool:
        """Whether this role may take part in building/constraining the model."""
        return self in (ControlRole.GCP, ControlRole.SCALE, ControlRole.CONSTRAINT)

    @property
    def is_independent_check(self) -> bool:
        """Whether this role is reserved for independent validation only."""
        return self in (ControlRole.CHECK, ControlRole.CHECK_LENGTH)


class AccuracyLabel(Enum):
    """Nominal survey accuracy of the point measurement (NOT model accuracy)."""

    SUB_CM = "sub_cm"
    CM = "cm"
    DM = "dm"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ControlPoint:
    """One surveyed point or standard.

    Attributes:
        point_id: Stable identifier (e.g. "GCP-01", "CHK-03", "SCALE-01").
        role: GCP vs CHECK vs SCALE vs CHECK_LENGTH. Never leave as UNKNOWN for
            real data (it would break separation).
        x / y / z: Coordinates in ``frame`` units (see SpatialFrame).
        frame: The spatial frame (CRS, unit, vertical datum) for these values.
        measured_sigma: Optional 1-sigma survey uncertainty in frame units, as
            reported by the survey instrument/operator. This is MEASUREMENT
            uncertainty, not model error.
        source: How it was measured (e.g. "GNSS-RTK", "total-station", "scale-bar").

    NOTE: per-photo 2D pixel observations of this point are NOT stored here.
    See :class:`archphoto.sensing.observations.PhotoObservation`.
    """

    point_id: str
    role: ControlRole
    x: float
    y: float
    z: float
    frame: "object"  # SpatialFrame
    measured_sigma: Optional[float] = None
    source: str = ""

    def __post_init__(self) -> None:
        if not self.point_id:
            raise ValueError("ControlPoint.point_id must be set")
        if self.role is ControlRole.UNKNOWN:
            raise ValueError(
                "ControlPoint.role must be GCP/CHECK/SCALE/CHECK_LENGTH (or CONSTRAINT); "
                "UNKNOWN would break GCP/checkpoint separation"
            )
        if self.measured_sigma is not None and self.measured_sigma < 0:
            raise ValueError("measured_sigma must be >= 0")

    @property
    def is_gcp(self) -> bool:
        return self.role is ControlRole.GCP

    @property
    def is_check(self) -> bool:
        return self.role is ControlRole.CHECK
