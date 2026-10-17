"""Incremental fusion (R01): merge depth/geometry across views into a surface.

Distinguishes an OBSERVED surface (from data) from an INTERPOLATED surface
(filled/guessed). Downstream display models must not present interpolated areas
as surveyed fact. Research stage.
"""

from __future__ import annotations


class IncrementalFuser:
    def fuse(self, observations) -> "object":
        """Return a fused surface carrying an observed-vs-interpolated mask.

        Not implemented. The result MUST expose which parts are observed and
        which are interpolated so downstream exports keep the distinction.
        """
        raise NotImplementedError("IncrementalFuser.fuse: not implemented yet.")
