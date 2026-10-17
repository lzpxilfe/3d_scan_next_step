"""Camera models: intrinsics, distortion, and extrinsics.

Principle: camera parameters and any camera transform must be explicit and
unit-checked. Pixel coordinates and object coordinates are never mixed without
going through a stated transform. Distortion model is named, not assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DistortionModel(Enum):
    """Named radial/tangential distortion model. Must match how parameters are interpreted."""

    NONE = "none"
    BROWN_CONRADY = "brown_conrady"  # k1,k2,k3,p1,p2
    FISHEYE = "fisheye"
    OPENCV = "opencv"  # k1,k2,p1,p2,k3
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Intrinsics:
    """Pinhole intrinsics in PIXEL units.

    Attributes:
        fx: Focal length in pixels along x.
        fy: Focal length in pixels along y.
        cx: Principal point x in pixels.
        cy: Principal point y in pixels.
        width_px / height_px: Image size the intrinsics apply to.
        distortion_model: Which distortion model the coefficients below follow.
        distortion: Model coefficients, order defined by ``distortion_model``.
            Empty tuple when ``distortion_model`` is NONE.
    """

    fx: float
    fy: float
    cx: float
    cy: float
    width_px: int
    height_px: int
    distortion_model: DistortionModel = DistortionModel.NONE
    distortion: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.fx <= 0 or self.fy <= 0:
            raise ValueError("Intrinsics focal lengths must be positive")
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("Intrinsics image size must be positive")

    @property
    def is_calibrated(self) -> bool:
        return self.distortion_model != DistortionModel.UNKNOWN


@dataclass(frozen=True)
class Extrinsics:
    """Camera pose in a stated :class:`~archphoto.geom.crs.SpatialFrame`.

    The rotation quaternion maps CAMERA coordinates to the world frame; the
    convention (world-from-camera vs camera-from-world) is fixed by
    ``world_from_camera`` and must not be guessed.
    """

    frame: "object"  # SpatialFrame; typed loosely to avoid a circular import
    quaternion_xyzw: tuple[float, float, float, float]
    translation: tuple[float, float, float]
    world_from_camera: bool = True


@dataclass(frozen=True)
class Camera:
    """A named camera body/lens configuration used by one or more photos."""

    camera_id: str
    intrinsics: Intrinsics
    make: Optional[str] = None
    model: Optional[str] = None
    sensor_mm_width: Optional[float] = None
    calibrated: bool = False

    def __post_init__(self) -> None:
        if not self.camera_id:
            raise ValueError("Camera.camera_id must be set")
