//! Run records, resource usage, and processing-vs-validation state.
//!
//! Ported from `archphoto.runlog.record`.
//! PRINCIPLE (`AGENTS.md`): a successful processing run is NOT the same as a
//! passed survey validation. These are recorded in separate fields
//! ([`ProcessState`] and [`ValidationState`]) and must never be collapsed into
//! one "success" flag. Resource figures are recorded as measured (`Some`) or
//! explicitly unmeasured (`None`); we never fabricate timings or accuracy.

use std::collections::HashMap;

use crate::ContractResult;

/// Whether the computation ran. Says nothing about survey accuracy.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ProcessState {
    NotStarted,
    Running,
    Succeeded,
    Failed,
    Partial,
}

impl ProcessState {
    pub fn label(self) -> &'static str {
        match self {
            Self::NotStarted => "not_started",
            Self::Running => "running",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Partial => "partial",
        }
    }

    pub fn ko_label(self) -> &'static str {
        match self {
            Self::NotStarted => "미실시",
            Self::Running => "실행 중",
            Self::Succeeded => "완료",
            Self::Failed => "실패",
            Self::Partial => "부분 완료",
        }
    }
}

/// Independent survey validation against CHECK points (never used in calibration).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ValidationState {
    NotRun,
    Passed,
    Failed,
    /// E.g. too few check points or tolerance still undecided (`[O]`).
    Inconclusive,
}

impl ValidationState {
    pub fn label(self) -> &'static str {
        match self {
            Self::NotRun => "not_run",
            Self::Passed => "passed",
            Self::Failed => "failed",
            Self::Inconclusive => "inconclusive",
        }
    }

    pub fn ko_label(self) -> &'static str {
        match self {
            Self::NotRun => "미실시",
            Self::Passed => "통과(독립 검증)",
            Self::Failed => "불통과(독립 검증)",
            Self::Inconclusive => "판정 보류",
        }
    }
}

/// Measured resource usage. `None` means "unmeasured", NEVER zero.
#[derive(Debug, Default, Clone, Copy, PartialEq)]
pub struct ResourceUsage {
    pub wall_seconds: Option<f64>,
    pub peak_ram_mb: Option<f64>,
    pub peak_vram_mb: Option<f64>,
    pub disk_mb: Option<f64>,
}

/// One processing run. Originals are never modified by a run.
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
pub struct RunRecord {
    pub run_id: String,
    pub process_state: ProcessState,
    pub validation_state: ValidationState,
    pub parameters: HashMap<String, String>,
    pub resources: ResourceUsage,
    pub log_path: Option<String>,
    pub failure_reason: Option<String>,
    pub engine_version: String,
    pub code_version: String,
    pub weight_version: String,
    pub input_hashes: HashMap<String, String>,
    pub selected_views: Vec<String>,
    pub outputs: Vec<String>,
    pub retry_count: u32,
}

impl RunRecord {
    pub fn new(run_id: impl Into<String>) -> ContractResult<Self> {
        let run_id = run_id.into();
        if run_id.trim().is_empty() {
            return Err("RunRecord.run_id must be set".into());
        }
        Ok(Self {
            run_id,
            process_state: ProcessState::NotStarted,
            validation_state: ValidationState::NotRun,
            parameters: HashMap::new(),
            resources: ResourceUsage::default(),
            log_path: None,
            failure_reason: None,
            engine_version: String::new(),
            code_version: String::new(),
            weight_version: String::new(),
            input_hashes: HashMap::new(),
            selected_views: Vec::new(),
            outputs: Vec::new(),
            retry_count: 0,
        })
    }

    /// Mark processing success ONLY. Does NOT imply validation passed.
    pub fn mark_succeeded(&mut self) {
        self.process_state = ProcessState::Succeeded;
    }

    pub fn mark_failed(&mut self, reason: impl Into<String>) {
        self.process_state = ProcessState::Failed;
        self.failure_reason = Some(reason.into());
    }

    pub fn is_processing_success(&self) -> bool {
        self.process_state == ProcessState::Succeeded
    }

    pub fn is_survey_validated(&self) -> bool {
        self.validation_state == ValidationState::Passed
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn processing_success_never_implies_survey_validation() {
        let mut r = RunRecord::new("run-1").unwrap();
        r.mark_succeeded();
        assert!(r.is_processing_success());
        assert!(!r.is_survey_validated());
        assert_eq!(r.process_state, ProcessState::Succeeded);
        assert_eq!(r.validation_state, ValidationState::NotRun);
        assert_eq!(r.resources.wall_seconds, None);
    }

    #[test]
    fn empty_run_id_is_refused() {
        assert!(RunRecord::new("  ").is_err());
    }
}
