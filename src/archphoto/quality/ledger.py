"""Point-usage ledger: enforces GCP-constraint vs independent-evaluation separation.

05 §2 and AGENTS.md require that we PREVENT calibrating/aligning with a check
point and then using that same point as an independent evaluation. This ledger
records, per point id, whether it took part in CONSTRAINT (bundle/GCP solve) or
ALIGNMENT (post-alignment), and refuses to let such a point be used for
independent EVALUATION afterwards.

Roles are checked in :mod:`archphoto.quality.checkpoints`; this module only
tracks USE so that even a mislabeled point cannot silently double as an
independent check.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PointUsageLedger:
    """Records which points were used to FIT the model vs to EVALUATE it.

    A point used in ``constraint`` or ``alignment`` helped determine the model,
    so its residual is not an independent accuracy measure. ``mark_evaluation``
    therefore rejects any such point.
    """

    constraint: set[str] = field(default_factory=set)
    alignment: set[str] = field(default_factory=set)
    evaluation: set[str] = field(default_factory=set)

    def mark_constraint(self, point_id: str) -> None:
        """Record that a point constrained the solve (GCP / scale / constraint)."""
        self.constraint.add(point_id)

    def mark_alignment(self, point_id: str) -> None:
        """Record that a point took part in post-alignment (also fits the model)."""
        self.alignment.add(point_id)

    def mark_evaluation(self, point_id: str) -> None:
        """Record independent-evaluation use, refusing points that fitted the model."""
        if point_id in self.constraint or point_id in self.alignment:
            raise ValueError(
                f"Point {point_id!r} was used to fit the model (constraint/alignment); "
                "it cannot be reused as an independent evaluation point."
            )
        self.evaluation.add(point_id)

    @property
    def fitted(self) -> set[str]:
        """Points that helped determine the model (not independent)."""
        return set(self.constraint) | set(self.alignment)
