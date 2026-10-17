"""Build a mesh from fused geometry. Not implemented."""

from __future__ import annotations


class MeshBuilder:
    def build(self, fused_surface) -> "object":
        """Return a mesh carrying frame + surface-kind metadata.

        Not implemented. The output must preserve the observed/interpolated
        distinction and the SpatialFrame so exports stay unambiguous.
        """
        raise NotImplementedError("MeshBuilder.build: not implemented yet.")
