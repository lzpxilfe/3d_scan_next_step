"""Run records, resource usage, and processing-vs-validation state.

PRINCIPLE (AGENTS.md): a successful processing run is NOT the same as a passed
survey validation. These are recorded in separate fields (:class:`ProcessState`
and :class:`ValidationState`) and must never be collapsed into one "success"
flag. Resource figures are recorded as measured or explicitly unmeasured; we do
not fabricate timings or accuracy numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ProcessState(Enum):
    """Whether the computation ran. Says nothing about survey accuracy."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


class ValidationState(Enum):
    """Independent survey validation against CHECK points (never used in calibration)."""

    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"  # e.g. too few check points


class ResourceUsage:
    """Measured resource usage. Each field is Optional and may be None when
    NOT measured; None means 'unmeasured', never zero."""

    def __init__(
        self,
        wall_seconds: Optional[float] = None,
        peak_ram_mb: Optional[float] = None,
        peak_vram_mb: Optional[float] = None,
        disk_mb: Optional[float] = None,
    ) -> None:
        self.wall_seconds = wall_seconds
        self.peak_ram_mb = peak_ram_mb
        self.peak_vram_mb = peak_vram_mb
        self.disk_mb = disk_mb


@dataclass
class RunRecord:
    """One processing run. Originals are never modified by a run.

    05 §5 requires a reproducible run record: input hashes, camera-solution
    version, control-point roles, engine/code/weight versions, full config,
    selected views, time, RAM/VRAM/disk peaks, errors/retries, output list.
    Fields below carry that provenance; any left empty is recorded as unknown,
    never guessed.

    Attributes:
        run_id: Unique id for this run.
        started_at / finished_at: UTC timestamps.
        process_state: Did the computation run (separate from validation).
        validation_state: Did independent survey validation pass (separate).
        parameters: The exact settings used, for reproducibility.
        resources: Measured usage (or None per metric if not measured).
        log_path: Where the full log is preserved (do not inline huge logs).
        failure_reason: Populated when process_state is FAILED/PARTIAL.
        engine_version / code_version / weight_version: provenance of the
            engine, this codebase, and any model weights used (05 §5).
        input_hashes: Map input id -> digest (e.g. photo_id -> sha256).
        selected_views: The view subset actually used (R01 view selection).
        outputs: List of produced artifact paths / ids.
        retry_count: Number of retries before the recorded state.
    """

    run_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    process_state: ProcessState = ProcessState.NOT_STARTED
    validation_state: ValidationState = ValidationState.NOT_RUN
    parameters: dict = field(default_factory=dict)
    resources: ResourceUsage = field(default_factory=ResourceUsage)
    log_path: Optional[str] = None
    failure_reason: Optional[str] = None
    engine_version: str = ""
    code_version: str = ""
    weight_version: str = ""
    input_hashes: dict = field(default_factory=dict)
    selected_views: tuple[str, ...] = ()
    outputs: list[str] = field(default_factory=list)
    retry_count: int = 0

    def mark_succeeded(self) -> None:
        """Mark processing success ONLY. Does not imply validation passed."""
        self.process_state = ProcessState.SUCCEEDED
        self.finished_at = datetime.now(timezone.utc)

    def mark_failed(self, reason: str) -> None:
        self.process_state = ProcessState.FAILED
        self.failure_reason = reason
        self.finished_at = datetime.now(timezone.utc)

    @property
    def is_processing_success(self) -> bool:
        return self.process_state is ProcessState.SUCCEEDED

    @property
    def is_survey_validated(self) -> bool:
        return self.validation_state is ValidationState.PASSED
