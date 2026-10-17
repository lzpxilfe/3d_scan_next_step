//! Baseline reconstruction orchestration, pipeline config, depth semantics, and
//! engine adapter contracts.
//!
//! Ported from `archphoto.recon.baseline`, `archphoto.recon.pipeline`,
//! `archphoto.recon.depth`, and `archphoto.engines.base`.
//! Wires the honest reconstruction flow around an injected engine:
//!   1. preflight input (abort on errors)
//!   2. apply GCP constraint (`PointUsageLedger` records constraint use)
//!   3. engine reconstruct
//!   4. independent CHECK evaluation (refuses any point that fitted the model)
//!   5. `RunRecord` (`ProcessState::Succeeded`, `ValidationState::NotRun`)

use std::collections::{BTreeSet, HashMap};

use crate::ContractResult;
use crate::crs::SpatialFrame;
use crate::preflight::{Severity, preflight_control};
use crate::quality::{
    CheckValidation, ConstraintReport, ModelMap, PointUsageLedger, apply_gcp_constraint,
    evaluate_check,
};
use crate::runlog::{ProcessState, RunRecord, ValidationState};
use crate::sensing::{ControlPoint, PhotoObservation};

/// What a depth value MEANS (`05 §3`). Engines differ; never assume.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum DepthRepresentation {
    /// Distance along the camera optical axis (a plane, not a ray).
    ZDepth,
    /// Euclidean distance along the viewing ray from the camera center.
    RayDistance,
    Unknown,
}

impl DepthRepresentation {
    pub fn label(self) -> &'static str {
        match self {
            Self::ZDepth => "z_depth",
            Self::RayDistance => "ray_distance",
            Self::Unknown => "unknown",
        }
    }
}

/// Capabilities an external photogrammetry engine may provide.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum EngineCapability {
    Sfm,
    Mvs,
    Mesh,
    Ortho,
    GcpSupport,
}

/// Identity and license provenance of an external engine.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub struct EngineInfo {
    pub name: String,
    pub version: String,
    pub license_id: String,
    /// MUST stay `false` until the exact version's license is verified.
    pub license_verified: bool,
}

impl EngineInfo {
    pub fn new(name: impl Into<String>, version: impl Into<String>) -> ContractResult<Self> {
        let name = name.into();
        if name.trim().is_empty() {
            return Err("EngineInfo.name must be set".into());
        }
        Ok(Self {
            name,
            version: version.into(),
            license_id: String::new(),
            license_verified: false,
        })
    }
}

/// Configuration for one reconstruction run, enforcing disjoint `gcp_ids` and `check_ids`.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub struct PipelineConfig {
    pub frame: SpatialFrame,
    pub use_learned_depth: bool,
    pub gcp_ids: Vec<String>,
    pub check_ids: Vec<String>,
}

impl PipelineConfig {
    pub fn new(
        frame: SpatialFrame,
        use_learned_depth: bool,
        gcp_ids: Vec<String>,
        check_ids: Vec<String>,
    ) -> ContractResult<Self> {
        let gcp_set: BTreeSet<&String> = gcp_ids.iter().collect();
        let chk_set: BTreeSet<&String> = check_ids.iter().collect();
        let overlap: Vec<&String> = gcp_set.intersection(&chk_set).copied().collect();
        if !overlap.is_empty() {
            return Err(format!(
                "GCP and CHECK point ids must be disjoint; overlap={overlap:?}. \
                 Using a check point in calibration would invalidate independent validation."
            ));
        }
        Ok(Self {
            frame,
            use_learned_depth,
            gcp_ids,
            check_ids,
        })
    }
}

/// Everything one baseline run needs.
#[derive(Debug, Clone)]
#[non_exhaustive]
pub struct BaselineInputs {
    pub control_points: Vec<ControlPoint>,
    pub frame: SpatialFrame,
    pub gcp_ids: Vec<String>,
    pub check_ids: Vec<String>,
    pub observations: Vec<PhotoObservation>,
    pub input_hashes: HashMap<String, String>,
}

impl BaselineInputs {
    pub fn new(
        control_points: Vec<ControlPoint>,
        frame: SpatialFrame,
        gcp_ids: Vec<String>,
        check_ids: Vec<String>,
        observations: Vec<PhotoObservation>,
        input_hashes: HashMap<String, String>,
    ) -> ContractResult<Self> {
        let _ = PipelineConfig::new(frame.clone(), false, gcp_ids.clone(), check_ids.clone())?;
        Ok(Self {
            control_points,
            frame,
            gcp_ids,
            check_ids,
            observations,
            input_hashes,
        })
    }
}

/// Result of a baseline orchestration run.
#[derive(Debug, Clone)]
pub struct BaselineResult {
    pub model_points: ModelMap,
    pub constraint: ConstraintReport,
    pub validation: CheckValidation,
    pub run: RunRecord,
}

/// Injected baseline engine interface. No concrete engine is bundled by default.
pub trait BaselineEngine {
    fn reconstruct(&self, inputs: &BaselineInputs) -> ContractResult<ModelMap>;
}

/// Execute the baseline reconstruction flow with an injected engine.
pub fn run_baseline(
    engine: Option<&dyn BaselineEngine>,
    inputs: &BaselineInputs,
) -> ContractResult<BaselineResult> {
    let Some(engine) = engine else {
        return Err(
            "No engine registered. The baseline engine is an external dependency \
             (not bundled); install/register one explicitly after license verification."
                .into(),
        );
    };

    let _ = PipelineConfig::new(
        inputs.frame.clone(),
        false,
        inputs.gcp_ids.clone(),
        inputs.check_ids.clone(),
    )?;

    // 1) Input preflight — abort on hard errors
    let obs_slice = if inputs.observations.is_empty() {
        None
    } else {
        Some(inputs.observations.as_slice())
    };
    let issues = preflight_control(&inputs.control_points, obs_slice);
    let errors: Vec<String> = issues
        .into_iter()
        .filter(|i| i.severity == Severity::Error)
        .map(|i| i.message)
        .collect();
    if !errors.is_empty() {
        return Err(format!("input preflight failed: {}", errors.join("; ")));
    }

    // 2) Split roles by ID
    let by_id: HashMap<&str, &ControlPoint> = inputs
        .control_points
        .iter()
        .map(|p| (p.point_id.as_str(), p))
        .collect();
    let gcp: Vec<ControlPoint> = inputs
        .gcp_ids
        .iter()
        .filter_map(|id| by_id.get(id.as_str()).map(|&p| p.clone()))
        .collect();
    let checks: Vec<ControlPoint> = inputs
        .check_ids
        .iter()
        .filter_map(|id| by_id.get(id.as_str()).map(|&p| p.clone()))
        .collect();

    // 3) Apply GCP constraint (refuses CHECK roles internally)
    let mut ledger = PointUsageLedger::default();
    let constraint = apply_gcp_constraint(&gcp, &mut ledger, None)?;

    // 4) Engine reconstruction
    let model_points = engine.reconstruct(inputs)?;

    // 5) Independent CHECK evaluation (refuses points used to fit the model)
    let validation = evaluate_check(&model_points, &checks, &mut ledger)?;

    // 6) RunRecord — process success is distinct from validation pass/fail
    let mut run = RunRecord::new("baseline")?;
    run.process_state = ProcessState::Succeeded;
    run.validation_state = ValidationState::NotRun;
    run.parameters
        .insert("gcp_ids".into(), inputs.gcp_ids.join(","));
    run.parameters
        .insert("check_ids".into(), inputs.check_ids.join(","));
    run.input_hashes.clone_from(&inputs.input_hashes);

    Ok(BaselineResult {
        model_points,
        constraint,
        validation,
        run,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crs::LengthUnit;
    use crate::sensing::SurveyRole;

    struct FakeEngine;
    impl BaselineEngine for FakeEngine {
        fn reconstruct(&self, inputs: &BaselineInputs) -> ContractResult<ModelMap> {
            Ok(inputs
                .control_points
                .iter()
                .map(|p| (p.point_id.clone(), [p.x, p.y, p.z]))
                .collect())
        }
    }

    struct OffsetEngine;
    impl BaselineEngine for OffsetEngine {
        fn reconstruct(&self, inputs: &BaselineInputs) -> ContractResult<ModelMap> {
            Ok(inputs
                .control_points
                .iter()
                .map(|p| (p.point_id.clone(), [p.x + 1.0, p.y, p.z]))
                .collect())
        }
    }

    fn frame() -> SpatialFrame {
        SpatialFrame::new("LOCAL:test", LengthUnit::Millimeter).unwrap()
    }

    fn sample_inputs() -> BaselineInputs {
        let f = frame();
        let pts = vec![
            ControlPoint::new("GCP-01", SurveyRole::Gcp, 0.0, 0.0, 0.0, f.clone()).unwrap(),
            ControlPoint::new("CHK-01", SurveyRole::Check, 10.0, 10.0, 10.0, f.clone()).unwrap(),
        ];
        let mut hashes = HashMap::new();
        hashes.insert("P-001".into(), "abc".into());
        BaselineInputs::new(
            pts,
            f,
            vec!["GCP-01".into()],
            vec!["CHK-01".into()],
            vec![],
            hashes,
        )
        .unwrap()
    }

    #[test]
    fn baseline_happy_path_and_nonzero_residual() {
        let inp = sample_inputs();
        let res = run_baseline(Some(&FakeEngine), &inp).unwrap();
        assert_eq!(res.constraint.applied, vec!["GCP-01".to_string()]);
        assert_eq!(
            res.validation.residuals.get("CHK-01"),
            Some(&[0.0, 0.0, 0.0])
        );
        assert_eq!(res.run.process_state, ProcessState::Succeeded);
        assert_eq!(res.run.validation_state, ValidationState::NotRun);

        let off = run_baseline(Some(&OffsetEngine), &inp).unwrap();
        assert_eq!(
            off.validation.residuals.get("CHK-01"),
            Some(&[1.0, 0.0, 0.0])
        );
        assert!((off.validation.distances["CHK-01"] - 1.0).abs() < 1e-12);
    }

    #[test]
    fn baseline_refuses_missing_engine_or_overlapping_ids() {
        let inp = sample_inputs();
        assert!(run_baseline(None, &inp).is_err());

        let f = frame();
        assert!(
            PipelineConfig::new(
                f,
                false,
                vec!["GCP-01".into(), "CHK-01".into()],
                vec!["CHK-01".into()]
            )
            .is_err()
        );
    }
}
