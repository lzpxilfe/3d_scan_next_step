"""Target classes: artifact (유물), feature (유구), site (유적).

Each class drives different capture, processing, and deliverable expectations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TargetClass(Enum):
    ARTIFACT = "artifact"  # 유물: small object, interior/exterior, flip capture
    FEATURE = "feature"  # 유구: floor, stone wall, section face, stratigraphic surface
    SITE = "site"  # 유적: survey area, multiple features, surrounding surface


@dataclass
class TargetSpec:
    """What is being reconstructed and the expected deliverables.

    Attributes:
        target_class: artifact / feature / site.
        identifier: operator-assigned id (e.g. "TR-01", "Vessel-12").
        deliverables: requested products (e.g. "mesh", "ortho", "section",
            "profile", "dem"). Kept as labels here; the concrete export code is
            in archphoto.mesh and archphoto.archaeo.drawing.
        notes: interpretive or contextual note (not survey fact).
    """

    target_class: TargetClass
    identifier: str
    deliverables: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.identifier:
            raise ValueError("TargetSpec.identifier must be set")
