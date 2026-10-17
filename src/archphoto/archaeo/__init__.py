"""Archaeology-specific workflow: targets, surfaces, sections, orthos, drawings.

This encodes the domain differences that make the tool archaeology-specific:
artifact / feature / site handling, the honesty axes (observed-vs-interpolated
origin and survey-vs-display purpose), and survey deliverables (section, ortho)
that keep computed geometry separate from interpretation.
"""

from archphoto.archaeo.ortho import OrthoGrid, OrthoProduct, OrthoSpec
from archphoto.archaeo.section import (
    LineOrigin,
    SectionLine,
    compute_section,
    interpretation_line,
)
from archphoto.archaeo.surface import OriginKind, ProductKind, SurfaceProduct
from archphoto.archaeo.targets import TargetClass, TargetSpec

__all__ = [
    "LineOrigin",
    "OriginKind",
    "OrthoGrid",
    "OrthoProduct",
    "OrthoSpec",
    "ProductKind",
    "SectionLine",
    "SurfaceProduct",
    "TargetClass",
    "TargetSpec",
    "compute_section",
    "interpretation_line",
]
