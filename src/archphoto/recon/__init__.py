"""Reconstruction pipeline: new algorithm + fast reconstruction (R01) + baseline + registration.

STATUS: research / orchestration only. Module BOUNDARIES and the honest baseline
and registration flows are defined; no real engine is bundled and no accuracy or
speed claims are made here (AGENTS.md: do not fabricate benchmarks).

Per the product direction (DECISIONS D-2026-10-12-07): fine mesh refinement is
left to external tools; our reconstruction focus is faithful geometry + block/scan
registration ("붙이기") that combines captures into a coherent whole.
"""

from archphoto.recon.baseline import BaselineInputs, BaselineResult, BaselineRunner
from archphoto.recon.pipeline import PipelineConfig, ReconstructionPipeline
from archphoto.recon.register import (
    Block,
    RegistrationResult,
    TiePoint,
    apply_similarity,
    apply_transform,
    fit_rigid_transform,
    merge_blocks,
    register_blocks,
)

__all__ = [
    "BaselineInputs",
    "BaselineResult",
    "BaselineRunner",
    "Block",
    "PipelineConfig",
    "ReconstructionPipeline",
    "RegistrationResult",
    "TiePoint",
    "apply_similarity",
    "apply_transform",
    "fit_rigid_transform",
    "merge_blocks",
    "register_blocks",
]
