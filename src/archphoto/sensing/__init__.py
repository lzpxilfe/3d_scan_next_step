"""Input sensing records: photos, cameras, control, and pixel observations.

The data contracts here (dataclasses) are real and validated. Algorithms that
consume them live elsewhere (recon/, engines/, quality/).

05 §2 separation kept here:
  - ControlPoint      : surveyed 3D coordinate + uncertainty (control.py)
  - PhotoObservation  : per-photo 2D pixel measurement (observations.py)
"""

from archphoto.sensing.cameras import (
    Camera,
    DistortionModel,
    Extrinsics,
    Intrinsics,
)
from archphoto.sensing.control import AccuracyLabel, ControlPoint, ControlRole
from archphoto.sensing.observations import PhotoObservation
from archphoto.sensing.photos import CaptureRole, DerivedImage, Photo, ProcessingStep

__all__ = [
    "AccuracyLabel",
    "Camera",
    "CaptureRole",
    "ControlPoint",
    "ControlRole",
    "DerivedImage",
    "DistortionModel",
    "Extrinsics",
    "Intrinsics",
    "Photo",
    "PhotoObservation",
    "ProcessingStep",
]
