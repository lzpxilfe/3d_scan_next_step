//! Reproducibility / determinism utilities (`PERFORMANCE_GOALS.md` §2.3).
//!
//! Ported from `archphoto.reproducibility`. Hardware-independent mesh results
//! require determinism: the same inputs and the same algorithm version must
//! produce the same geometry within a stated tolerance, regardless of which
//! machine computes it.

use std::collections::{BTreeSet, HashMap};

use crate::{ContractResult, Point3D};

/// Provenance needed to reproduce a run (`05 §5` / `PERFORMANCE_GOALS.md` §2.3).
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub struct DeterminismSettings {
    pub seed: u64,
    pub code_version: String,
    pub engine_version: String,
    pub weight_version: String,
    pub input_hashes: HashMap<String, String>,
}

impl DeterminismSettings {
    #[must_use]
    pub fn new(seed: u64) -> Self {
        Self {
            seed,
            code_version: String::new(),
            engine_version: String::new(),
            weight_version: String::new(),
            input_hashes: HashMap::new(),
        }
    }

    #[must_use]
    pub fn with_versions(
        mut self,
        code_version: impl Into<String>,
        engine_version: impl Into<String>,
        weight_version: impl Into<String>,
    ) -> Self {
        self.code_version = code_version.into();
        self.engine_version = engine_version.into();
        self.weight_version = weight_version.into();
        self
    }

    #[must_use]
    pub fn with_input_hashes(mut self, input_hashes: HashMap<String, String>) -> Self {
        self.input_hashes = input_hashes;
        self
    }

    /// Flat map suitable for [`crate::runlog::RunRecord::parameters`].
    #[must_use]
    pub fn as_run_parameters(&self) -> HashMap<String, String> {
        let mut out = HashMap::new();
        out.insert("seed".into(), self.seed.to_string());
        out.insert("code_version".into(), self.code_version.clone());
        out.insert("engine_version".into(), self.engine_version.clone());
        out.insert("weight_version".into(), self.weight_version.clone());
        out
    }
}

/// Outcome of a reproducibility comparison (`M` is the mismatch key type:
/// `usize` for sequences, `String` for maps).
#[derive(Debug, Clone, PartialEq)]
pub struct ReproResult<M> {
    pub within_tolerance: bool,
    pub max_deviation: f64,
    pub count_a: usize,
    pub count_b: usize,
    pub mismatches: Vec<M>,
}

fn dev(pa: Point3D, pb: Point3D) -> f64 {
    let dx = pa[0] - pb[0];
    let dy = pa[1] - pb[1];
    let dz = pa[2] - pb[2];
    (dx * dx + dy * dy + dz * dz).sqrt()
}

/// Compare two ordered point slices within `tol` (same order assumed).
pub fn compare_point_sequences(
    a: &[Point3D],
    b: &[Point3D],
    tol: f64,
) -> ContractResult<ReproResult<usize>> {
    if !tol.is_finite() || tol < 0.0 {
        return Err("tol must be finite and >= 0".into());
    }
    if a.len() != b.len() {
        return Ok(ReproResult {
            within_tolerance: false,
            max_deviation: f64::INFINITY,
            count_a: a.len(),
            count_b: b.len(),
            mismatches: Vec::new(),
        });
    }
    let mut max_dev = 0.0_f64;
    let mut mismatches = Vec::new();
    for (i, (&pa, &pb)) in a.iter().zip(b.iter()).enumerate() {
        let d = dev(pa, pb);
        if d > max_dev {
            max_dev = d;
        }
        if d > tol || !d.is_finite() {
            mismatches.push(i);
        }
    }
    Ok(ReproResult {
        within_tolerance: mismatches.is_empty(),
        max_deviation: max_dev,
        count_a: a.len(),
        count_b: b.len(),
        mismatches,
    })
}

/// Compare two ID-keyed point maps within `tol`.
///
/// Missing or extra IDs count as mismatches and force `within_tolerance = false`.
pub fn compare_point_maps(
    a: &HashMap<String, Point3D>,
    b: &HashMap<String, Point3D>,
    tol: f64,
) -> ContractResult<ReproResult<String>> {
    if !tol.is_finite() || tol < 0.0 {
        return Err("tol must be finite and >= 0".into());
    }
    let keys_a: BTreeSet<&String> = a.keys().collect();
    let keys_b: BTreeSet<&String> = b.keys().collect();
    if keys_a != keys_b {
        let missing: Vec<String> = keys_a
            .symmetric_difference(&keys_b)
            .map(|k| (*k).clone())
            .collect();
        return Ok(ReproResult {
            within_tolerance: false,
            max_deviation: f64::INFINITY,
            count_a: a.len(),
            count_b: b.len(),
            mismatches: missing,
        });
    }
    let mut max_dev = 0.0_f64;
    let mut mismatches = Vec::new();
    for k in keys_a {
        let d = dev(a[k], b[k]);
        if d > max_dev {
            max_dev = d;
        }
        if d > tol || !d.is_finite() {
            mismatches.push(k.clone());
        }
    }
    Ok(ReproResult {
        within_tolerance: mismatches.is_empty(),
        max_deviation: max_dev,
        count_a: a.len(),
        count_b: b.len(),
        mismatches,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sequence_comparison_detects_within_and_outside_tolerance() {
        let a = [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]];
        let b = [[0.0, 0.0, 0.005], [1.0, 1.0, 1.0]];
        let ok = compare_point_sequences(&a, &b, 0.01).unwrap();
        assert!(ok.within_tolerance);
        assert!(ok.max_deviation < 0.01);
        assert!(ok.mismatches.is_empty());

        let c = [[0.0, 0.0, 0.0], [1.0, 1.0, 5.0]];
        let bad = compare_point_sequences(&a, &c, 0.1).unwrap();
        assert!(!bad.within_tolerance);
        assert_eq!(bad.mismatches, vec![1]);
    }

    #[test]
    fn map_comparison_flags_missing_keys_and_provenance_settings() {
        let mut a = HashMap::new();
        a.insert("P1".into(), [0.0, 0.0, 0.0]);
        a.insert("P2".into(), [1.0, 1.0, 1.0]);
        let mut b = HashMap::new();
        b.insert("P1".into(), [0.0, 0.0, 0.0]);

        let r = compare_point_maps(&a, &b, 0.1).unwrap();
        assert!(!r.within_tolerance);
        assert_eq!(r.mismatches, vec!["P2".to_string()]);

        let s = DeterminismSettings::new(7).with_versions("0.0.1", "colmap-x", "");
        let p = s.as_run_parameters();
        assert_eq!(p.get("seed").map(String::as_str), Some("7"));
        assert_eq!(p.get("code_version").map(String::as_str), Some("0.0.1"));
    }
}
