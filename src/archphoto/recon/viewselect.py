"""View selection (R01): choose which photos contribute to a given region.

Reduces redundant computation by picking a compact, informative subset of views
while preserving multi-view geometry. Research stage; not implemented.
"""

from __future__ import annotations


class ViewSelector:
    def select(self, region, candidate_views) -> list:
        """Return the chosen subset of views for ``region``. Not implemented."""
        raise NotImplementedError("ViewSelector.select: not implemented yet.")
