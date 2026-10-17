"""Project and session manifest.

PRINCIPLE (AGENTS.md): original photos and original survey data must never be
overwritten or auto-deleted. The manifest records integrity digests so that a
later run can detect if an original changed. All writes go to derived/output
areas, never back to the raw area.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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

    def __post_init__(self) -> None:
        if not self.rel_path or not self.rel_path.strip():
            raise ValueError("RawItem.rel_path must be set")
        if not self.sha256 or not self.sha256.strip():
            raise ValueError("RawItem.sha256 must be set")
        if self.byte_size < 0:
            raise ValueError("RawItem.byte_size must be >= 0")


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

    def __post_init__(self) -> None:
        if not self.project_id or not self.project_id.strip():
            raise ValueError("ProjectManifest.project_id must be set")

    def register_raw(self, item: RawItem) -> None:
        self.raw_items.append(item)

    def verify_raw_integrity(self) -> list[str]:
        """Return ``rel_path``s whose stored digest or byte size no longer matches disk.

        Recomputes SHA-256 against disk in read-only mode without ever modifying
        originals (AGENTS.md).
        """
        mismatched: list[str] = []
        for item in self.raw_items:
            target = (Path(self.raw_root) / item.rel_path) if self.raw_root else Path(item.rel_path)
            if not target.is_file():
                mismatched.append(item.rel_path)
                continue
            try:
                if target.stat().st_size != item.byte_size:
                    mismatched.append(item.rel_path)
                    continue
                digest = hashlib.sha256()
                with open(target, "rb") as handle:
                    for chunk in iter(lambda: handle.read(65536), b""):
                        digest.update(chunk)
                if digest.hexdigest() != item.sha256:
                    mismatched.append(item.rel_path)
            except OSError:
                mismatched.append(item.rel_path)
        return mismatched
