"""Local refinement (R01): dense, localized geometry polishing.

Runs after coarse reconstruction to refine selected regions (e.g. thin walls,
edges, tool marks) without re-processing the whole scene. Research stage.
"""

from __future__ import annotations


class LocalRefiner:
    def refine(self, region, geometry) -> "object":
        """Return refined geometry for ``region``. Not implemented."""
        raise NotImplementedError("LocalRefiner.refine: not implemented yet.")
