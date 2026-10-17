"""Top-level reconstruction orchestration.

The pipeline wires the four research stages (depth, view selection, refinement,
fusion) and the mesh build. It must keep the separation between GCP (used for
constraint) and CHECK points (used only for independent validation) intact end
to end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PipelineConfig:
    """Configuration for one reconstruction run.

    Explicit and reproducible; every run stores its config in the RunRecord.

    Attributes:
        frame: The target SpatialFrame (CRS/unit/datum). Must be set.
        use_learned_depth: Whether to use the research learned-depth path.
            False = classical depth path. This is a research toggle, not a
            promise that one is better.
        gcp_ids: Point IDs used as GCP constraints. Must be disjoint from
            ``check_ids``.
        check_ids: Point IDs used ONLY for independent validation. Must be
            disjoint from ``gcp_ids``.
    """

    frame: "object"  # SpatialFrame
    use_learned_depth: bool = False
    gcp_ids: tuple[str, ...] = ()
    check_ids: tuple[str, ...] = ()
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        overlap = set(self.gcp_ids) & set(self.check_ids)
        if overlap:
            raise ValueError(
                f"GCP and CHECK point ids must be disjoint; overlap={sorted(overlap)}. "
                "Using a check point in calibration would invalidate independent validation."
            )


class ReconstructionPipeline:
    """Orchestrates depth -> view selection -> refinement -> fusion -> mesh.

    Not implemented. Methods raise until the research stages are filled in.
    """

    def run(self, config: PipelineConfig) -> "object":
        raise NotImplementedError(
            "ReconstructionPipeline.run: full pipeline not implemented. "
            "Define inputs/outputs/units and validate GCP/check separation first."
        )
