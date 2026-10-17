"""Input preflight checks: contract conformance before any processing.

Used to vet user-supplied survey data (BASELINE_T06.md §6) against the data
contracts before a run, so missing CRS/units or a broken GCP/check separation is
caught up front. Returns a list of issues (does not raise) so a single pass can
report every problem at once. Pure Python, no external dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

from archphoto.sensing.control import ControlRole
from archphoto.sensing.observations import PhotoObservation


@dataclass(frozen=True)
class PreflightIssue:
    """One problem found during preflight.

    ``code`` is a stable machine key, ``message`` is human-readable, ``severity``
    is ``"error"`` (blocks processing) or ``"warning"`` (review recommended).
    """

    code: str
    message: str
    severity: str = "error"


def preflight_control(control_points, observations=None) -> list[PreflightIssue]:
    """Check surveyed control and pixel observations against the contracts.

    ``control_points``: iterable of ControlPoint.
    ``observations``: optional iterable of PhotoObservation.

    Checks:
      - every point has an explicit CRS id and unit-bearing frame;
      - no point uses role UNKNOWN;
      - point ids are unique;
      - at least one CHECK point exists (else independent validation impossible);
      - observations reference non-empty point_id/photo_id and their point exists.
    """
    issues: list[PreflightIssue] = []
    points = list(control_points)
    seen: set[str] = set()
    roles_by_id: dict[str, ControlRole] = {}

    first_valid_frame = None

    for p in points:
        # CRS / unit must be explicit (05 §3).
        frame = getattr(p, "frame", None)
        has_valid_frame = True
        if frame is None or not getattr(frame, "crs_id", ""):
            issues.append(PreflightIssue("missing_crs", f"{p.point_id}: 좌표계(crs_id)가 없습니다."))
            has_valid_frame = False
        if frame is None or getattr(frame, "unit", None) is None:
            issues.append(PreflightIssue("missing_unit", f"{p.point_id}: 단위가 명시되지 않았습니다."))
            has_valid_frame = False
        if has_valid_frame:
            if first_valid_frame is None:
                first_valid_frame = frame
            elif frame != first_valid_frame:
                issues.append(
                    PreflightIssue(
                        "inconsistent_frame",
                        f"{p.point_id}: 좌표계 프레임이 기준 프레임과 다릅니다.",
                    )
                )

        if p.role is ControlRole.UNKNOWN:
            issues.append(PreflightIssue("unknown_role", f"{p.point_id}: 역할이 UNKNOWN입니다."))

        if p.point_id in seen:
            issues.append(PreflightIssue("duplicate_id", f"{p.point_id}: point_id가 중복됩니다."))
        seen.add(p.point_id)
        roles_by_id[p.point_id] = p.role

    if not any(r.is_independent_check for r in roles_by_id.values()):
        issues.append(
            PreflightIssue(
                "no_check_point",
                "독립 검증점(CHECK)이 없습니다. 독립 정확도 평가가 불가능합니다.",
                severity="warning",
            )
        )

    for o in list(observations or []):
        if not o.point_id or not o.photo_id:
            issues.append(PreflightIssue("bad_observation", "관측에 point_id/photo_id가 비어 있습니다."))
        elif o.point_id not in roles_by_id:
            issues.append(
                PreflightIssue("orphan_observation", f"관측이 알 수 없는 점 {o.point_id!r}을 참조합니다.")
            )
    return issues
