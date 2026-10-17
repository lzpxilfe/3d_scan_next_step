"""Engine adapter interface (baseline path).

An adapter wraps one external photogrammetry engine. The interface is defined;
no concrete engine is implemented in the scaffold.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EngineCapability(Enum):
    """What an engine can do, so callers can pick a baseline appropriately."""

    SFM = "sfm"  # structure-from-motion / camera pose
    MVS = "mvs"  # multi-view stereo / dense depth
    MESH = "mesh"
    ORTHO = "ortho"
    GCP_SUPPORT = "gcp_support"  # can apply GCP constraints


@dataclass
class EngineInfo:
    """Identity and provenance of an engine. Filled in only after verification."""

    name: str
    version: str = ""
    license_id: str = ""  # SPDX id, filled after checking the exact version
    license_verified: bool = False  # MUST stay False until actually checked


class EngineAdapter:
    """Interface for one external engine. Not implemented."""

    info: EngineInfo

    def capabilities(self) -> set[EngineCapability]:
        raise NotImplementedError("EngineAdapter.capabilities: not implemented.")

    def run(self, inputs, config) -> "object":
        raise NotImplementedError(
            "EngineAdapter.run: no engine is wired in yet. Engine choice and "
            "license are undecided [O]; do not assume an engine is present."
        )
