"""Photograph records.

A photo is an immutable reference to an original image file. Originals are
never overwritten or auto-deleted (AGENTS.md). This module records metadata and
integrity info only; it does not load pixels.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class CaptureRole(Enum):
    """Why the photo was taken; drives downstream handling."""

    OBJECT = "object"  # primary subject (artifact / feature / site)
    SCALE = "scale"  # reference scale bar / metric target
    REFERENCE = "reference"  # context, documentation
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Photo:
    """Immutable reference to one original image.

    Attributes:
        photo_id: Stable identifier within the project (e.g. file stem).
        path: Path to the ORIGINAL file. Must not be modified by the program.
        capture_role: Role of the capture.
        camera_id: Links to :class:`archphoto.sensing.cameras.Camera`; may be
            None before calibration.
        sha256: Hex digest of the original bytes for integrity / preservation.
            Populate before any processing so later runs can detect changes.
        acquired_at: Capture timestamp if available (from EXIF), else None.
        width_px: Image width in pixels. Required for pixel<->unit conversions.
        height_px: Image height in pixels.
        notes: Free-form operator note.
    """

    photo_id: str
    path: Path
    capture_role: CaptureRole = CaptureRole.OBJECT
    camera_id: Optional[str] = None
    sha256: Optional[str] = None
    acquired_at: Optional[datetime] = None
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.photo_id:
            raise ValueError("Photo.photo_id must be set")
        if self.width_px is not None and self.width_px <= 0:
            raise ValueError("Photo.width_px must be positive when set")
        if self.height_px is not None and self.height_px <= 0:
            raise ValueError("Photo.height_px must be positive when set")


class ProcessingStep(Enum):
    """A derivation applied to an original photo.

    05 §3: the relation between the ORIGINAL photo and rotated / cropped /
    downscaled / undistorted images must be recorded. Every derived image names
    the steps applied and links back to its source Photo.
    """

    ROTATE = "rotate"
    CROP = "crop"
    DOWNSCALE = "downscale"
    UNDISTORT = "undistort"
    NORMALIZE = "normalize"


@dataclass(frozen=True)
class DerivedImage:
    """A processed image derived from an original :class:`Photo`.

    The original is never overwritten. This record states how the derived image
    relates to the original so camera values, pixel observations, and depth maps
    are never mixed across versions without a stated transform.

    Attributes:
        derived_id: Identifier of this derived image.
        source_photo_id: The ORIGINAL photo it came from (must reference a Photo).
        path: Path to the derived file (in an output/derived area, not raw).
        steps: The processing steps applied, in order.
        width_px / height_px: Size of the derived image.
        scale_to_original: Optional uniform scale factor relating derived pixels
            to original pixels (e.g. 0.5 after a 2x downscale). None when
            non-uniform or not applicable.
    """

    derived_id: str
    source_photo_id: str
    path: "object"  # Path
    steps: tuple[ProcessingStep, ...] = ()
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    scale_to_original: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.derived_id or not self.source_photo_id:
            raise ValueError("DerivedImage requires derived_id and source_photo_id")
