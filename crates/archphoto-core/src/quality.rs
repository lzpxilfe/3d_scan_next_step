//! GCP constraint application vs independent CHECK-point evaluation.
//!
//! Ported from `archphoto.quality` (Python reference). PRINCIPLE (05 §2,
//! AGENTS.md): the two are SEPARATE and enforced.
//!   - [`apply_gcp_constraint`] consumes ONLY calibration roles
//!     (GCP/SCALE/CONSTRAINT). Their residuals may be reported but are NOT
//!     independent accuracy.
//!   - [`evaluate_check`] consumes ONLY CHECK (or CHECK_LENGTH) points, and
//!     only those that did NOT take part in fitting the model (see
//!     [`PointUsageLedger`]). Its residuals are MODEL error in the frame's
//!     units — NOT survey error.
//!
//! A residual is `reconstructed − surveyed`, both in the same units/axes as
//! the [`ControlPoint`]s. The `model` maps `point_id -> [x, y, z]` of
//! reconstructed coordinates; a real reconstruction supplies it, synthetic
//! tests supply a small map.

use std::collections::{HashMap, HashSet};

use crate::sensing::ControlPoint;
use crate::{ContractResult, Point3D};

/// Reconstructed coordinates by point id, in the same frame as the points.
pub type ModelMap = HashMap<String, Point3D>;

/// Records which points were used to FIT the model vs to EVALUATE it.
///
/// A point used in `constraint` or `alignment` helped determine the model, so
/// its residual is not an independent accuracy measure. [`Self::mark_evaluation`]
/// therefore rejects any such point — even a mislabeled one cannot silently
/// double as an independent check.
#[derive(Debug, Default, Clone)]
pub struct PointUsageLedger {
    constraint: HashSet<String>,
    alignment: HashSet<String>,
    evaluation: HashSet<String>,
}

impl PointUsageLedger {
    /// Record that a point constrained the solve (GCP / scale / constraint).
    pub fn mark_constraint(&mut self, point_id: impl Into<String>) {
        self.constraint.insert(point_id.into());
    }

    /// Record that a point took part in post-alignment (also fits the model).
    pub fn mark_alignment(&mut self, point_id: impl Into<String>) {
        self.alignment.insert(point_id.into());
    }

    /// Record independent-evaluation use, refusing points that fitted the
    /// model (constraint/alignment).
    pub fn mark_evaluation(&mut self, point_id: &str) -> ContractResult<()> {
        if self.constraint.contains(point_id) || self.alignment.contains(point_id) {
            return Err(format!(
                "Point {point_id:?} was used to fit the model (constraint/alignment); \
                 it cannot be reused as an independent evaluation point."
            ));
        }
        self.evaluation.insert(point_id.to_string());
        Ok(())
    }

    /// Points that helped determine the model (NOT independent).
    pub fn fitted(&self) -> HashSet<String> {
        self.constraint.union(&self.alignment).cloned().collect()
    }

    pub fn is_evaluation(&self, point_id: &str) -> bool {
        self.evaluation.contains(point_id)
    }
}

/// Summary statistics of CHECK-point distance residuals (frame units).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ValidationStats {
    pub count: usize,
    pub mean: f64,
    pub median: f64,
    pub max: f64,
}

/// Residuals of the model against CHECK points (model error, NOT survey error).
#[derive(Debug, Default, Clone, PartialEq)]
pub struct CheckValidation {
    /// point_id -> per-axis residual (reconstructed − surveyed), frame units.
    pub residuals: HashMap<String, Point3D>,
    /// point_id -> Euclidean residual distance.
    pub distances: HashMap<String, f64>,
    /// Summary stats; None only when there were no check points at all.
    pub stats: Option<ValidationStats>,
}

/// Which GCP/scale/constraint points were applied to the solve.
///
/// `residuals` may report the post-solve residual at those points, but these
/// are NOT independent accuracy.
#[derive(Debug, Default, Clone, PartialEq)]
pub struct ConstraintReport {
    pub applied: Vec<String>,
    pub residuals: HashMap<String, Point3D>,
}

/// Apply calibration-role points as constraints; refuse CHECK points.
///
/// Only roles with `used_in_calibration` are accepted. CHECK/CHECK_LENGTH are
/// rejected so they can never enter the solve. Applied points are recorded in
/// `ledger` so they cannot later be used for independent evaluation.
pub fn apply_gcp_constraint(
    points: &[ControlPoint],
    ledger: &mut PointUsageLedger,
    model: Option<&ModelMap>,
) -> ContractResult<ConstraintReport> {
    let mut report = ConstraintReport::default();
    for point in points {
        if !point.role.used_in_calibration() {
            return Err(format!(
                "Point {:?} has role {:?}; CHECK points must not be used to constrain the model.",
                point.point_id, point.role
            ));
        }
        ledger.mark_constraint(point.point_id.clone());
        report.applied.push(point.point_id.clone());
        if let Some(model) = model {
            if let Some(reconstructed) = model.get(&point.point_id) {
                report
                    .residuals
                    .insert(point.point_id.clone(), residual(*reconstructed, point));
            }
        }
    }
    Ok(report)
}

/// Compute model-vs-CHECK residuals for INDEPENDENT validation only.
///
/// Enforces, in this order (mirroring the Python reference):
///   1. every point must be a CHECK (or CHECK_LENGTH) role — this is checked
///      before any model access, so a GCP is rejected regardless of `model`;
///   2. every point must have a reconstructed coordinate;
///   3. no point may have been used to fit the model (`ledger` refuses).
pub fn evaluate_check(
    model: &ModelMap,
    check_points: &[ControlPoint],
    ledger: &mut PointUsageLedger,
) -> ContractResult<CheckValidation> {
    let mut out = CheckValidation::default();
    for point in check_points {
        if !point.role.is_independent_check() {
            return Err(format!(
                "Point {:?} has role {:?}; only CHECK points may be used for independent validation.",
                point.point_id, point.role
            ));
        }
        let Some(reconstructed) = model.get(&point.point_id) else {
            return Err(format!(
                "No reconstructed coordinates for check point {:?}",
                point.point_id
            ));
        };
        ledger.mark_evaluation(&point.point_id)?;
        let r = residual(*reconstructed, point);
        let distance = (r[0] * r[0] + r[1] * r[1] + r[2] * r[2]).sqrt();
        out.residuals.insert(point.point_id.clone(), r);
        out.distances.insert(point.point_id.clone(), distance);
    }
    out.stats = stats(&out.distances);
    Ok(out)
}

fn residual(reconstructed: Point3D, surveyed: &ControlPoint) -> Point3D {
    [
        reconstructed[0] - surveyed.x,
        reconstructed[1] - surveyed.y,
        reconstructed[2] - surveyed.z,
    ]
}

fn stats(distances: &HashMap<String, f64>) -> Option<ValidationStats> {
    if distances.is_empty() {
        return None;
    }
    let mut vals: Vec<f64> = distances.values().copied().collect();
    vals.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    let n = vals.len();
    let mid = n / 2;
    let median = if n % 2 == 1 {
        vals[mid]
    } else {
        (vals[mid - 1] + vals[mid]) / 2.0
    };
    Some(ValidationStats {
        count: n,
        mean: vals.iter().sum::<f64>() / n as f64,
        median,
        max: vals[n - 1],
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crs::{LengthUnit, SpatialFrame};
    use crate::sensing::{ControlRole, SurveyRole};

    fn frame() -> SpatialFrame {
        SpatialFrame::new("LOCAL:test", LengthUnit::Meter)
            .unwrap()
            .with_vertical_datum(crate::crs::VerticalDatum::Orthometric)
    }

    fn pt(id: &str, role: SurveyRole, x: f64, y: f64, z: f64) -> ControlPoint {
        ControlPoint::new(id, role, x, y, z, frame()).unwrap()
    }

    fn model(entries: &[(&str, [f64; 3])]) -> ModelMap {
        entries
            .iter()
            .map(|(id, xyz)| ((*id).to_string(), *xyz))
            .collect()
    }

    #[test]
    fn gcp_constraint_records_and_reports_residuals() {
        let mut ledger = PointUsageLedger::default();
        let gcp = pt("GCP-1", SurveyRole::Gcp, 1.0, 2.0, 3.0);
        let scale = pt("SCALE-1", SurveyRole::Scale, 0.0, 0.0, 0.0);
        let m = model(&[("GCP-1", [1.1, 2.0, 3.05])]);

        let report = apply_gcp_constraint(&[gcp, scale], &mut ledger, Some(&m)).unwrap();

        assert_eq!(
            report.applied,
            vec!["GCP-1".to_string(), "SCALE-1".to_string()]
        );
        let expected = [0.1, 0.0, 0.05];
        for (got, want) in report.residuals["GCP-1"].iter().zip(expected.iter()) {
            assert!((got - want).abs() < 1e-12, "{got} vs {want}");
        }
        // No model entry → no fabricated residual.
        assert!(!report.residuals.contains_key("SCALE-1"));
        assert!(ledger.fitted().contains("GCP-1"));
        assert!(ledger.fitted().contains("SCALE-1"));
    }

    #[test]
    fn check_role_may_never_constrain_the_model() {
        let mut ledger = PointUsageLedger::default();
        let check = pt("CHK-1", SurveyRole::Check, 0.0, 0.0, 0.0);
        let err = apply_gcp_constraint(&[check], &mut ledger, None).unwrap_err();
        assert!(
            err.contains("must not be used to constrain the model"),
            "{err}"
        );
        assert!(ledger.fitted().is_empty());
    }

    #[test]
    fn ledger_refuses_evaluation_of_fitted_points() {
        let mut ledger = PointUsageLedger::default();
        ledger.mark_constraint("GCP-1");
        let err = ledger.mark_evaluation("GCP-1").unwrap_err();
        assert!(
            err.contains("cannot be reused as an independent evaluation point"),
            "{err}"
        );

        ledger.mark_alignment("AL-1");
        assert!(ledger.mark_evaluation("AL-1").is_err());
        assert!(ledger.mark_evaluation("CHK-1").is_ok());
        assert!(ledger.is_evaluation("CHK-1"));
    }

    #[test]
    fn evaluation_validates_residuals_distances_and_stats() {
        let mut ledger = PointUsageLedger::default();
        let a = pt("CHK-A", SurveyRole::Check, 0.0, 0.0, 0.0);
        let b = pt("CHK-B", SurveyRole::CheckLength, 10.0, 0.0, 0.0);
        let m = model(&[("CHK-A", [0.1, -0.2, 0.02]), ("CHK-B", [10.02, 0.0, 0.02])]);

        let v = evaluate_check(&m, &[a, b], &mut ledger).unwrap();

        assert_eq!(v.residuals.get("CHK-A"), Some(&[0.1, -0.2, 0.02]));
        let da = (0.1f64 * 0.1 + 0.2 * 0.2 + 0.02 * 0.02).sqrt(); // ≈ 0.2244994
        let db = (0.02f64 * 0.02 + 0.02 * 0.02).sqrt(); // ≈ 0.0282843
        assert!((v.distances["CHK-A"] - da).abs() < 1e-12);
        assert!((v.distances["CHK-B"] - db).abs() < 1e-12);

        let s = v.stats.expect("stats for 2 points");
        assert_eq!(s.count, 2);
        assert!((s.mean - (da + db) / 2.0).abs() < 1e-12);
        assert!((s.median - s.mean).abs() < 1e-12); // n=2: median = mean of the two
        assert!((s.max - da).abs() < 1e-12);
        assert!(ledger.is_evaluation("CHK-A") && ledger.is_evaluation("CHK-B"));
    }

    #[test]
    fn stats_median_picks_middle_value_for_odd_counts() {
        let mut ledger = PointUsageLedger::default();
        let a = pt("A", SurveyRole::Check, 0.0, 0.0, 0.0);
        let b = pt("B", SurveyRole::Check, 0.0, 0.0, 0.0);
        let c = pt("C", SurveyRole::Check, 0.0, 0.0, 0.0);
        let m = model(&[
            ("A", [0.1, 0.0, 0.0]),
            ("B", [0.0, 0.3, 0.0]),
            ("C", [0.0, 0.0, 0.2]),
        ]);

        let v = evaluate_check(&m, &[a, b, c], &mut ledger).unwrap();
        let s = v.stats.unwrap();
        // sorted: 0.1, 0.2, 0.3 → median 0.2
        assert_eq!(s.count, 3);
        assert!((s.median - 0.2).abs() < 1e-12);
        assert!((s.max - 0.3).abs() < 1e-12);
        assert!((s.mean - (0.1 + 0.2 + 0.3) / 3.0).abs() < 1e-12);
    }

    #[test]
    fn evaluation_rejects_gcp_role_before_touching_the_model() {
        let mut ledger = PointUsageLedger::default();
        let gcp = pt("GCP-1", SurveyRole::Gcp, 0.0, 0.0, 0.0);
        let empty = ModelMap::new();

        let err = evaluate_check(&empty, &[gcp], &mut ledger).unwrap_err();
        // Role refusal fires even though the model has no entry at all.
        assert!(
            err.contains("only CHECK points may be used for independent validation"),
            "{err}"
        );
        assert!(!ledger.is_evaluation("GCP-1"));
    }

    #[test]
    fn evaluation_requires_a_reconstructed_coordinate() {
        let mut ledger = PointUsageLedger::default();
        let chk = pt("CHK-1", SurveyRole::Check, 0.0, 0.0, 0.0);
        let m = model(&[("OTHER", [0.0, 0.0, 0.0])]);

        let err = evaluate_check(&m, &[chk], &mut ledger).unwrap_err();
        assert!(
            err.contains("No reconstructed coordinates for check point"),
            "{err}"
        );
    }

    #[test]
    fn evaluation_via_shared_ledger_refuses_a_point_that_constrained_the_solve() {
        // Even with a CHECK-group role label, the ledger refuses a point that
        // was used as a constraint (mislabeled points cannot double as checks).
        let mut ledger = PointUsageLedger::default();
        let scale = pt("S-1", SurveyRole::Scale, 1.0, 0.0, 0.0);
        apply_gcp_constraint(&[scale], &mut ledger, None).unwrap();

        let relabeled = pt("S-1", SurveyRole::CheckLength, 1.0, 0.0, 0.0);
        let m = model(&[("S-1", [1.01, 0.0, 0.0])]);
        let err = evaluate_check(&m, &[relabeled], &mut ledger).unwrap_err();
        assert!(
            err.contains("cannot be reused as an independent evaluation point"),
            "{err}"
        );
    }

    #[test]
    fn raw_unknown_role_never_reaches_a_point() {
        // Parsing may yield Unknown; the point layer must refuse it.
        assert_eq!(ControlRole::Unknown.as_survey_role(), None);
        assert!(ControlRole::Unknown.as_survey_role().is_none());
    }
}
