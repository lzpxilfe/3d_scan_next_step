//! Survey sensing contracts — ported from `archphoto.sensing` (Python reference).
//!
//! 05 §2: a point's surveyed coordinate and its per-photo pixel observation are
//! separate structures; roles are explicit; a Photo is an immutable reference to
//! the ORIGINAL file and the program never writes through its path.
//!
//! Rust translation (D-2026-10-12-11): what Python enforced with runtime
//! `ValueError`s is enforced structurally here — a `ControlRole::Unknown` label
//! cannot enter a `ControlPoint` because the point stores the validated
//! [`SurveyRole`] only, and an empty id is a construction-time error.

use std::path::PathBuf;

use crate::ContractResult;
use crate::crs::SpatialFrame;

/// Why a photo was taken. Drives downstream handling (Python `CaptureRole`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CaptureRole {
    Object,
    Scale,
    Reference,
    Unknown,
}

/// Raw control-role label as delivered by survey data, including a genuinely
/// unknown value (Python `ControlRole`). Promotion to a point-construction role
/// goes through [`ControlRole::as_survey_role`]; `Unknown` is unpromotable.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ControlRole {
    Gcp,
    Check,
    Scale,
    CheckLength,
    Constraint,
    Unknown,
}

impl ControlRole {
    pub fn as_survey_role(self) -> Option<SurveyRole> {
        match self {
            ControlRole::Gcp => Some(SurveyRole::Gcp),
            ControlRole::Check => Some(SurveyRole::Check),
            ControlRole::Scale => Some(SurveyRole::Scale),
            ControlRole::CheckLength => Some(SurveyRole::CheckLength),
            ControlRole::Constraint => Some(SurveyRole::Constraint),
            ControlRole::Unknown => None,
        }
    }
}

/// Validated role of a surveyed point/standard. UNKNOWN is unrepresentable:
/// a point whose role is not known must not exist, matching Python's
/// `ControlPoint` refusing `ControlRole.UNKNOWN`.
///
/// GCP/SCALE/CONSTRAINT may constrain the solve; CHECK/CHECK_LENGTH are
/// reserved for independent validation only.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum SurveyRole {
    Gcp,
    Check,
    Scale,
    CheckLength,
    Constraint,
}

impl SurveyRole {
    /// May this role take part in building/constraining the model?
    pub fn used_in_calibration(self) -> bool {
        matches!(
            self,
            SurveyRole::Gcp | SurveyRole::Scale | SurveyRole::Constraint
        )
    }

    /// Is this role reserved for independent validation only?
    pub fn is_independent_check(self) -> bool {
        matches!(self, SurveyRole::Check | SurveyRole::CheckLength)
    }
}

/// One surveyed point or standard (Python `ControlPoint`).
///
/// Coordinates are in `frame` units/axes/datum — never implied. Per-photo pixel
/// observations of this point are NOT stored here
/// (see [`PhotoObservation`], 05 §2).
#[derive(Debug, Clone, PartialEq)]
pub struct ControlPoint {
    pub point_id: String,
    pub role: SurveyRole,
    pub x: f64,
    pub y: f64,
    pub z: f64,
    pub frame: SpatialFrame,
    pub measured_sigma: Option<f64>,
    pub source: String,
}

impl ControlPoint {
    pub fn new(
        point_id: impl Into<String>,
        role: SurveyRole,
        x: f64,
        y: f64,
        z: f64,
        frame: SpatialFrame,
    ) -> ContractResult<Self> {
        let point_id = point_id.into();
        if point_id.is_empty() {
            return Err("ControlPoint.point_id must be set".into());
        }
        Ok(ControlPoint {
            point_id,
            role,
            x,
            y,
            z,
            frame,
            measured_sigma: None,
            source: String::new(),
        })
    }

    /// Measurement uncertainty (1σ) in frame units — survey accuracy of the
    /// INPUT, not the model's accuracy.
    pub fn with_measured_sigma(mut self, sigma: f64) -> ContractResult<Self> {
        if sigma < 0.0 {
            return Err("measured_sigma must be >= 0".into());
        }
        self.measured_sigma = Some(sigma);
        Ok(self)
    }

    #[must_use]
    pub fn with_source(mut self, source: impl Into<String>) -> Self {
        self.source = source.into();
        self
    }

    pub fn is_gcp(&self) -> bool {
        self.role == SurveyRole::Gcp
    }

    pub fn is_check(&self) -> bool {
        self.role == SurveyRole::Check
    }
}

/// Immutable reference to one original image (Python `Photo`).
///
/// `path` points to the ORIGINAL file; nothing in the program writes through
/// it. `sha256` records the original bytes' digest at ingest for integrity.
#[derive(Debug, Clone, PartialEq)]
pub struct Photo {
    pub photo_id: String,
    pub path: PathBuf,
    pub capture_role: CaptureRole,
    pub camera_id: Option<String>,
    pub sha256: Option<String>,
    /// Capture timestamp (ISO-8601 string) when available, else None.
    /// String until a time-crate decision lands; never guessed.
    pub acquired_at: Option<String>,
    /// Image dimensions in pixels; required later for pixel-unit conversions.
    pub width_px: Option<u32>,
    pub height_px: Option<u32>,
    pub notes: String,
}

impl Photo {
    pub fn new(photo_id: impl Into<String>, path: impl Into<PathBuf>) -> ContractResult<Self> {
        let photo_id = photo_id.into();
        if photo_id.is_empty() {
            return Err("Photo.photo_id must be set".into());
        }
        Ok(Photo {
            photo_id,
            path: path.into(),
            capture_role: CaptureRole::Object,
            camera_id: None,
            sha256: None,
            acquired_at: None,
            width_px: None,
            height_px: None,
            notes: String::new(),
        })
    }

    #[must_use]
    pub fn with_capture_role(mut self, role: CaptureRole) -> Self {
        self.capture_role = role;
        self
    }

    /// Size must be positive when present (Python contract); sizes are used for
    /// pixel↔unit conversions, and a zero size would silently corrupt those.
    pub fn with_size(mut self, width_px: u32, height_px: u32) -> ContractResult<Self> {
        if width_px == 0 || height_px == 0 {
            return Err("Photo.width_px/height_px must be positive when set".into());
        }
        self.width_px = Some(width_px);
        self.height_px = Some(height_px);
        Ok(self)
    }

    #[must_use]
    pub fn with_sha256(mut self, sha256: impl Into<String>) -> Self {
        self.sha256 = Some(sha256.into());
        self
    }
}

/// One 2D image measurement of a control point in one photo (Python
/// `PhotoObservation`, 05 §2). Pixels live here; surveyed 3D coordinates live
/// in [`ControlPoint`]. The two must never be conflated.
#[derive(Debug, Clone, PartialEq)]
pub struct PhotoObservation {
    pub point_id: String,
    pub photo_id: String,
    pub x_px: f64,
    pub y_px: f64,
    /// 1σ pixel measurement uncertainty, if known.
    pub sigma_px: Option<f64>,
    /// True only when (x_px, y_px) are in an undistorted image plane rather
    /// than raw sensor pixels. Distortion handling must be explicit.
    pub photo_undistorted: bool,
}

impl PhotoObservation {
    pub fn new(
        point_id: impl Into<String>,
        photo_id: impl Into<String>,
        x_px: f64,
        y_px: f64,
    ) -> ContractResult<Self> {
        let point_id = point_id.into();
        let photo_id = photo_id.into();
        if point_id.is_empty() || photo_id.is_empty() {
            return Err("PhotoObservation requires point_id and photo_id".into());
        }
        Ok(PhotoObservation {
            point_id,
            photo_id,
            x_px,
            y_px,
            sigma_px: None,
            photo_undistorted: false,
        })
    }

    pub fn with_sigma_px(mut self, sigma: f64) -> ContractResult<Self> {
        if sigma < 0.0 {
            return Err("sigma_px must be >= 0".into());
        }
        self.sigma_px = Some(sigma);
        Ok(self)
    }

    #[must_use]
    pub fn in_undistorted_plane(mut self) -> Self {
        self.photo_undistorted = true;
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crs::LengthUnit;

    fn frame() -> SpatialFrame {
        SpatialFrame::new("LOCAL:test", LengthUnit::Meter)
    }

    #[test]
    fn survey_roles_split_calibration_from_independent_check() {
        assert!(SurveyRole::Gcp.used_in_calibration());
        assert!(SurveyRole::Scale.used_in_calibration());
        assert!(SurveyRole::Constraint.used_in_calibration());
        assert!(!SurveyRole::Check.used_in_calibration());
        assert!(!SurveyRole::CheckLength.used_in_calibration());
        assert!(SurveyRole::Check.is_independent_check());
        assert!(SurveyRole::CheckLength.is_independent_check());
        assert!(!SurveyRole::Gcp.is_independent_check());
    }

    #[test]
    fn unknown_raw_label_cannot_become_a_point_role() {
        assert_eq!(ControlRole::Unknown.as_survey_role(), None);
        assert_eq!(ControlRole::Check.as_survey_role(), Some(SurveyRole::Check));
    }

    #[test]
    fn point_contract_rejects_empty_id_and_negative_sigma() {
        assert!(ControlPoint::new("", SurveyRole::Gcp, 0.0, 0.0, 0.0, frame()).is_err());
        let point = ControlPoint::new("GCP-01", SurveyRole::Gcp, 0.0, 0.0, 0.0, frame()).unwrap();
        assert!(point.clone().with_measured_sigma(-0.1).is_err());
        assert!(point.clone().with_measured_sigma(0.0).is_ok());
        assert!(point.is_gcp() && !point.is_check());
    }

    #[test]
    fn photo_contract_rejects_empty_id_and_nonpositive_size() {
        assert!(Photo::new("", "/tmp/x.jpg").is_err());
        let photo = Photo::new("IMG_001", "/tmp/x.jpg").unwrap();
        assert_eq!(photo.capture_role, CaptureRole::Object);
        assert!(photo.clone().with_size(0, 48).is_err());
        assert!(photo.clone().with_size(64, 0).is_err());
        assert!(photo.clone().with_size(64, 48).is_ok());
    }

    #[test]
    fn observation_contract_rejects_empty_ids() {
        assert!(PhotoObservation::new("", "IMG_001", 10.0, 20.0).is_err());
        assert!(PhotoObservation::new("GCP-01", "", 10.0, 20.0).is_err());
        let obs = PhotoObservation::new("GCP-01", "IMG_001", 10.5, 20.5).unwrap();
        assert!(obs.clone().with_sigma_px(-1.0).is_err());
        let obs = obs.with_sigma_px(0.5).unwrap();
        assert!(!obs.photo_undistorted);
        assert!(obs.in_undistorted_plane().photo_undistorted);
    }
}
