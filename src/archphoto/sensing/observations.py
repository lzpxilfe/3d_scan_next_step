"""Per-photo pixel observations of control points.

05 §2: "점 자체의 좌표·불확도와, 사진별 픽셀 관측은 별도 구조로 저장한다."
A point's surveyed 3D coordinate lives in :class:`~archphoto.sensing.control.ControlPoint`;
its 2D image measurements live here. Keeping them apart prevents a pixel
measurement from being mistaken for a survey coordinate and vice versa.

A pixel observation is the operator/target's 2D location (in PIXELS) of a
control point in one photo, together with its measurement uncertainty. These
observations feed bundle adjustment for GCP; for CHECK points they must be
recorded but withheld from calibration and used only for validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PhotoObservation:
    """One 2D image measurement of a control point in one photo.

    Attributes:
        point_id: Which control point this observes (links to ControlPoint.point_id).
        photo_id: Which photo this measurement is in (links to Photo.photo_id).
        x_px / y_px: Pixel coordinates in the photo's pixel grid.
        sigma_px: Optional 1-sigma pixel measurement uncertainty (pixels).
        photo_undistorted: True if (x_px, y_px) are in an undistorted/normalized
            image plane rather than raw sensor pixels. Distortion handling must
            be explicit (05 §3); never assume raw pixels.
    """

    point_id: str
    photo_id: str
    x_px: float
    y_px: float
    sigma_px: Optional[float] = None
    photo_undistorted: bool = False

    def __post_init__(self) -> None:
        if not self.point_id or not self.photo_id:
            raise ValueError("PhotoObservation requires point_id and photo_id")
        if self.sigma_px is not None and self.sigma_px < 0:
            raise ValueError("sigma_px must be >= 0")
