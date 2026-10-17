"""Depth estimation stage (R01 learned depth + classical fallback).

CONTRACT: a depth map is produced per photo in the camera's pixel grid, with an
explicit metric scale tied to the project SpatialFrame. A learned model's
confidence score is NOT a real-world dimension error and must never be reported
as one (AGENTS.md).
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class DepthRepresentation(Enum):
    """What a depth value MEANS (05 §3). Engines differ; never assume.

    Z_DEPTH     : distance along the camera optical axis (a plane, not a ray).
    RAY_DISTANCE: Euclidean distance along the viewing ray from the camera center.
    Disparity / inverse-depth encodings would need their own labels before use.

    A metric error in mm cannot be interpreted without knowing which of these
    the numbers represent and in what SpatialFrame unit.
    """

    Z_DEPTH = "z_depth"
    RAY_DISTANCE = "ray_distance"
    UNKNOWN = "unknown"


class DepthEstimator:
    """Interface for depth maps from a single photo + camera."""

    def estimate(self, photo, camera, frame) -> "object":
        """Return a depth map (pixels -> metric depth in ``frame`` units).

        Not implemented. The returned object must carry:
          - ``depth``: per-pixel depth in ``frame`` unit
          - ``representation``: a DepthRepresentation (required, never implicit)
          - ``valid``: boolean mask
          - ``scale_frame``: the SpatialFrame the metric scale refers to
          - ``confidence``: OPTIONAL model confidence, labelled as model output
            (NOT a survey accuracy).
        """
        raise NotImplementedError("DepthEstimator.estimate: not implemented yet.")
