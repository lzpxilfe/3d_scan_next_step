"""Baseline reconstruction orchestration (기준선 재구성 흐름).

Wires the honest reconstruction flow around an ENGINE:
  preflight input -> apply GCP constraint -> engine reconstruct -> independent
  CHECK evaluation -> run record.

This is the orchestration skeleton for the baseline path (BASELINE_T06.md). The
engine is injected; no engine is bundled here. With a real engine + data this
produces the baseline; in tests a fake engine exercises the flow's invariants
(GCP/check separation, honesty of the record) without any install or real data.

NOTE (PERFORMANCE_GOALS): fine mesh refinement is left to external tools; our
reconstruction focus is faithful geometry + the block/scan registration
("붙이기") that combines captures into a coherent whole. Mesh building itself is
a separate step (archphoto.mesh).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from archphoto.preflight import preflight_control
from archphoto.quality import (
    CheckValidation,
    ConstraintReport,
    PointUsageLedger,
    apply_gcp_constraint,
    evaluate_check,
)
from archphoto.runlog import ProcessState, RunRecord, ValidationState

Point3D = tuple[float, float, float]


@dataclass
class BaselineInputs:
    """Everything one baseline run needs.

    ``gcp_ids`` and ``check_ids`` MUST be disjoint (enforced). ``frame`` is the
    target SpatialFrame. ``input_hashes`` records original-data digests.
    """

    control_points: list
    frame: "object"  # SpatialFrame
    gcp_ids: tuple[str, ...] = ()
    check_ids: tuple[str, ...] = ()
    observations: list = field(default_factory=list)
    input_hashes: dict = field(default_factory=dict)


@dataclass
class BaselineResult:
    model_points: dict
    constraint: ConstraintReport
    validation: CheckValidation
    run: RunRecord


class BaselineRunner:
    """Run the baseline flow with an injected engine.

    ``engine`` must provide ``reconstruct(inputs) -> dict[point_id -> Point3D]``
    of reconstructed coordinates in the input frame. No real engine is bundled.
    """

    def __init__(self, engine) -> None:
        self.engine = engine

    def run(self, inputs: BaselineInputs) -> BaselineResult:
        if self.engine is None:
            raise RuntimeError(
                "No engine registered. The baseline engine is an external "
                "dependency (not bundled); install/register one explicitly after "
                "license verification."
            )
        if set(inputs.gcp_ids) & set(inputs.check_ids):
            raise ValueError("gcp_ids and check_ids must be disjoint (05 §2)")

        # 1) input preflight — abort on hard errors
        issues = preflight_control(inputs.control_points, inputs.observations)
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            raise ValueError("input preflight failed: " + "; ".join(i.message for i in errors))

        # 2) split roles
        by_id = {p.point_id: p for p in inputs.control_points}
        gcp = [by_id[i] for i in inputs.gcp_ids if i in by_id]
        checks = [by_id[i] for i in inputs.check_ids if i in by_id]

        # 3) apply GCP constraint (refuses CHECK roles internally)
        ledger = PointUsageLedger()
        constraint = apply_gcp_constraint(gcp, ledger)

        # 4) engine reconstruction
        model_points = self.engine.reconstruct(inputs)

        # 5) independent CHECK evaluation (refuses points used to fit the model)
        validation = evaluate_check(model_points, checks, ledger)

        # 6) run record — process success is distinct from validation pass/fail;
        #    pass/fail needs a tolerance that is still [O], so leave NOT_RUN.
        run = RunRecord(
            run_id="baseline",
            process_state=ProcessState.SUCCEEDED,
            validation_state=ValidationState.NOT_RUN,
            parameters={"gcp_ids": list(inputs.gcp_ids), "check_ids": list(inputs.check_ids)},
            input_hashes=dict(inputs.input_hashes),
        )
        return BaselineResult(model_points, constraint, validation, run)
