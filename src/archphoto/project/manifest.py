"""Project and session manifest.

PRINCIPLE (AGENTS.md): original photos and original survey data must never be
overwritten or auto-deleted. The manifest records integrity digests so that a
later run can detect if an original changed. All writes go to derived/output
areas, never back to the raw area.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class RawItem:
    """One preserved original file (photo or survey export).

    ``sha256`` is captured at ingest; verification later compares against it.
    """

    rel_path: str
    sha256: str
    kind: str  # "photo" | "survey" | "other"
    byte_size: int


@dataclass
class ProjectManifest:
    """Top-level project record.

    The manifest separates the immutable RAW area from DERIVED outputs so that
    originals are preserved and never overwritten.

    Attributes:
        project_id: Stable project identifier.
        title: Human-readable project/title (site, trench, object).
        created_at: UTC creation time.
        raw_root: Directory holding originals (read-only by policy).
        output_root: Directory for derived products (meshes, orthos, logs).
        raw_items: Integrity records for originals.
        crs_id: Declared coordinate reference system (see geom). Must be set
            before any survey-bearing operation; may be "LOCAL".
    """

    project_id: str
    title: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_root: Optional[str] = None
    output_root: Optional[str] = None
    raw_items: list[RawItem] = field(default_factory=list)
    crs_id: Optional[str] = None

    def register_raw(self, item: RawItem) -> None:
        self.raw_items.append(item)

    def verify_raw_integrity(self) -> list[str]:
        """Return rel_paths whose stored digest no longer matches the file.

        Not implemented in the scaffold; must recompute digests against disk
        without modifying the originals.
        """
        raise NotImplementedError(
            "ProjectManifest.verify_raw_integrity: recompute SHA-256 of originals "
            "and compare; never modify originals. Not implemented yet."
        )
