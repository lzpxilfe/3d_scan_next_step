"""Surface provenance and product kind — the honesty axes (05 §4).

Two DISTINCT axes are kept apart so an unobserved region is never presented as fact:

  - :class:`OriginKind`  — WHERE the geometry came from: OBSERVED (measured from
    data) vs INTERPOLATED (filled / smoothed / guessed).
  - :class:`ProductKind` — WHAT the model is FOR: SURVEY (measurement-grade record)
    vs DISPLAY (exhibition; explicitly NOT a survey record).

A survey model may contain some interpolated region (e.g. a filled hole) but it
MUST disclose it. A display model must never be labelled as a survey record.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OriginKind(Enum):
    """Data origin of a piece of geometry."""

    OBSERVED = "observed"  # directly supported by input measurements
    INTERPOLATED = "interpolated"  # filled, smoothed, mirrored, or inferred


class ProductKind(Enum):
    """Intended use of the model."""

    SURVEY = "survey"  # measurement-grade record
    DISPLAY = "display"  # exhibition model, NOT a survey record


@dataclass
class SurfaceProduct:
    """A surface product carrying both honesty axes.

    ``product_kind`` is the whole-model purpose. Per-region/per-vertex origin is
    carried by :class:`archphoto.mesh.product.MeshProduct`; this class names the
    product and its description.
    """

    product_kind: ProductKind
    description: str = ""

    def is_survey_record(self) -> bool:
        return self.product_kind is ProductKind.SURVEY
