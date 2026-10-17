//! Input preflight checks: contract conformance before any processing.
//!
//! Ported from Python `archphoto.preflight` (BASELINE_T06 §6): vet user-supplied
//! survey data against the contracts before a run, so broken GCP/check
//! separation is caught up front. Returns a list of issues (does NOT raise) so
//! a single pass can report every problem at once.
//!
//! CHECKS REMOVED BY DESIGN (superseded by compile-time contracts, see
//! D-2026-10-12-11 — they cannot occur in Rust data, so emitting them would be
//! theater):
//!   - `missing_crs` / `missing_unit`: SpatialFrame requires crs_id + unit at
//!     construction;
//!   - `unknown_role`: ControlPoint stores the validated SurveyRole; UNKNOWN
//!     cannot enter;
//!   - `bad_observation`: PhotoObservation::new refuses empty ids.
//!
//! Kept here (list-level checks no constructor can know):
//!   - `duplicate_id`: ids unique across the survey set;
//!   - `inconsistent_frame`: all points in a survey set must share the same SpatialFrame;
//!   - `no_check_point` (warning): at least one CHECK point must exist or
//!     independent validation is impossible;
//!   - `orphan_observation`: pixel observation referencing an unknown point.

use std::collections::HashSet;

use crate::sensing::{ControlPoint, PhotoObservation};

/// Severity of a preflight issue (Python `severity` string, enum'd).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Severity {
    /// Blocks processing.
    Error,
    /// Review recommended.
    Warning,
}

impl Severity {
    pub fn label(self) -> &'static str {
        match self {
            Severity::Error => "error",
            Severity::Warning => "warning",
        }
    }
}

/// One problem found during preflight.
///
/// `code` is a stable machine key, `message` human-readable.
#[derive(Debug, Clone, PartialEq)]
pub struct PreflightIssue {
    pub code: &'static str,
    pub message: String,
    pub severity: Severity,
}

impl PreflightIssue {
    fn error(code: &'static str, message: impl Into<String>) -> Self {
        PreflightIssue {
            code,
            message: message.into(),
            severity: Severity::Error,
        }
    }

    fn warning(code: &'static str, message: impl Into<String>) -> Self {
        PreflightIssue {
            code,
            message: message.into(),
            severity: Severity::Warning,
        }
    }
}

/// Check surveyed control and pixel observations against the (remaining
/// runtime) contracts.
pub fn preflight_control(
    points: &[ControlPoint],
    observations: Option<&[PhotoObservation]>,
) -> Vec<PreflightIssue> {
    let mut issues = Vec::new();
    let mut seen: HashSet<&str> = HashSet::new();
    let mut has_check = false;
    let first_frame = points.first().map(|p| &p.frame);

    for p in points {
        if !seen.insert(p.point_id.as_str()) {
            issues.push(PreflightIssue::error(
                "duplicate_id",
                format!("{}: point_id가 중복됩니다.", p.point_id),
            ));
        }
        if let Some(expected) = first_frame
            && &p.frame != expected
        {
            issues.push(PreflightIssue::error(
                "inconsistent_frame",
                format!(
                    "{}: 좌표계 프레임({})이 기준 프레임({})과 다릅니다.",
                    p.point_id, p.frame, expected
                ),
            ));
        }
        has_check |= p.role.is_independent_check();
    }

    if !has_check {
        issues.push(PreflightIssue::warning(
            "no_check_point",
            "독립 검증점(CHECK)이 없습니다. 독립 정확도 평가가 불가능합니다.",
        ));
    }

    for o in observations.iter().flat_map(|os| os.iter()) {
        if !seen.contains(o.point_id.as_str()) {
            issues.push(PreflightIssue::error(
                "orphan_observation",
                format!("관측이 알 수 없는 점 {:?}을 참조합니다.", o.point_id),
            ));
        }
    }
    issues
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crs::{LengthUnit, SpatialFrame};
    use crate::sensing::SurveyRole;

    fn frame() -> SpatialFrame {
        SpatialFrame::new("LOCAL:t", LengthUnit::Meter).unwrap()
    }

    fn pt(id: &str, role: SurveyRole) -> ControlPoint {
        ControlPoint::new(id, role, 0.0, 0.0, 0.0, frame()).unwrap()
    }

    #[test]
    fn clean_survey_reports_no_issues() {
        let points = vec![pt("GCP-1", SurveyRole::Gcp), pt("CHK-1", SurveyRole::Check)];
        let obs = vec![PhotoObservation::new("CHK-1", "IMG-1", 10.0, 20.0).unwrap()];
        let issues = preflight_control(&points, Some(&obs));
        assert!(issues.is_empty(), "{issues:?}");
    }

    #[test]
    fn duplicate_point_ids_are_reported_once_each() {
        let points = vec![pt("GCP-1", SurveyRole::Gcp), pt("GCP-1", SurveyRole::Scale)];
        let issues = preflight_control(&points, None);
        let dups: Vec<&PreflightIssue> =
            issues.iter().filter(|i| i.code == "duplicate_id").collect();
        // Clean surveys without checks also warn; here a check exists → exactly one dup.
        assert_eq!(dups.len(), 1);
        assert_eq!(dups[0].severity, Severity::Error);
        assert!(dups[0].message.contains("중복"));
    }

    #[test]
    fn inconsistent_frames_are_reported_as_error() {
        let other = SpatialFrame::new("LOCAL:t", LengthUnit::Millimeter).unwrap();
        let points = vec![
            pt("GCP-1", SurveyRole::Gcp),
            ControlPoint::new("CHK-1", SurveyRole::Check, 0.0, 0.0, 0.0, other).unwrap(),
        ];
        let issues = preflight_control(&points, None);
        assert!(
            issues
                .iter()
                .any(|i| i.code == "inconsistent_frame" && i.severity == Severity::Error)
        );
    }

    #[test]
    fn missing_check_point_warns_but_does_not_block() {
        let points = vec![pt("GCP-1", SurveyRole::Gcp), pt("S-1", SurveyRole::Scale)];
        let issues = preflight_control(&points, None);
        assert_eq!(issues.len(), 1);
        assert_eq!(issues[0].code, "no_check_point");
        assert_eq!(issues[0].severity, Severity::Warning);
    }

    #[test]
    fn orphan_observation_is_reported() {
        let points = vec![pt("CHK-1", SurveyRole::Check)];
        let obs = vec![
            PhotoObservation::new("CHK-1", "IMG-1", 5.0, 5.0).unwrap(),
            PhotoObservation::new("GHOST", "IMG-1", 6.0, 6.0).unwrap(),
        ];
        let issues = preflight_control(&points, Some(&obs));
        let orphans: Vec<&PreflightIssue> = issues
            .iter()
            .filter(|i| i.code == "orphan_observation")
            .collect();
        assert_eq!(orphans.len(), 1);
        assert_eq!(orphans[0].severity, Severity::Error);
        assert!(orphans[0].message.contains("GHOST"));
    }

    #[test]
    fn empty_survey_warns_about_missing_check() {
        let issues = preflight_control(&[], None);
        assert_eq!(issues.len(), 1);
        assert_eq!(issues[0].code, "no_check_point");
    }
}
