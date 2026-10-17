"""Drawing-output facade for archaeology deliverables.

The real implementations live in :mod:`archphoto.archaeo.section` (computed vs
interpreted section lines) and :mod:`archphoto.archaeo.ortho` (orthophoto
projection + grid + honesty). This module re-exports them so there is a single
source of truth. Assembling a full drawing sheet (ortho + section + interpretation
linework into a report layout) is future work layered on top of these.
"""

from archphoto.archaeo.ortho import OrthoGrid, OrthoProduct, OrthoSpec
from archphoto.archaeo.section import (
    LineOrigin,
    SectionLine,
    compute_section,
    interpretation_line,
)

__all__ = [
    "LineOrigin",
    "OrthoGrid",
    "OrthoProduct",
    "OrthoSpec",
    "SectionLine",
    "compute_section",
    "interpretation_line",
]
