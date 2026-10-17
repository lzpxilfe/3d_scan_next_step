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

use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};

use crate::crs::SpatialFrame;
use crate::{ContractResult, Point3D};

/// Why a photo was taken. Drives downstream handling (Python `CaptureRole`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CaptureRole {
    Object,
    Scale,
    Reference,
    Unknown,
}

impl CaptureRole {
    pub fn label(self) -> &'static str {
        match self {
            CaptureRole::Object => "object",
            CaptureRole::Scale => "scale",
            CaptureRole::Reference => "reference",
            CaptureRole::Unknown => "unknown",
        }
    }
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

    pub fn label(self) -> &'static str {
        match self {
            SurveyRole::Gcp => "gcp",
            SurveyRole::Check => "check",
            SurveyRole::Scale => "scale",
            SurveyRole::CheckLength => "check_length",
            SurveyRole::Constraint => "constraint",
        }
    }
}

/// One surveyed point or standard (Python `ControlPoint`).
///
/// Coordinates are in `frame` units/axes/datum — never implied. Per-photo pixel
/// observations of this point are NOT stored here
/// (see [`PhotoObservation`], 05 §2).
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
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
        if !x.is_finite() || !y.is_finite() || !z.is_finite() {
            return Err("ControlPoint coordinates must be finite".into());
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
        if !sigma.is_finite() || sigma < 0.0 {
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
#[non_exhaustive]
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

    /// Read-only ingest of an original photo file: computes the SHA-256 hex
    /// digest in 64 KiB chunks and inspects PNG/JPEG header dimensions when
    /// available (otherwise leaves `width_px`/`height_px` honestly `None`).
    /// Never modifies or writes to `path` (AGENTS.md).
    pub fn from_file(
        photo_id: impl Into<String>,
        path: impl Into<PathBuf>,
    ) -> ContractResult<Self> {
        let path = path.into();
        let digest = sha256_file(&path)?;
        let mut photo = Photo::new(photo_id, path.clone())?.with_sha256(digest);
        if let Some((w, h)) = inspect_image_dimensions(&path)
            && w > 0
            && h > 0
        {
            photo.width_px = Some(w);
            photo.height_px = Some(h);
        }
        Ok(photo)
    }

    #[must_use]
    pub fn with_capture_role(mut self, role: CaptureRole) -> Self {
        self.capture_role = role;
        self
    }

    #[must_use]
    pub fn with_camera_id(mut self, camera_id: impl Into<String>) -> Self {
        self.camera_id = Some(camera_id.into());
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

/// A derivation applied to an original photo (Python `ProcessingStep`, 05 §3).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProcessingStep {
    Rotate,
    Crop,
    Downscale,
    Undistort,
    Normalize,
}

impl ProcessingStep {
    pub fn label(self) -> &'static str {
        match self {
            ProcessingStep::Rotate => "rotate",
            ProcessingStep::Crop => "crop",
            ProcessingStep::Downscale => "downscale",
            ProcessingStep::Undistort => "undistort",
            ProcessingStep::Normalize => "normalize",
        }
    }
}

/// A processed image derived from an original [`Photo`] (Python `DerivedImage`).
///
/// The original is never overwritten. This record states how the derived image
/// relates to the original so camera values, pixel observations, and depth maps
/// are never mixed across versions without a stated transform.
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
pub struct DerivedImage {
    pub derived_id: String,
    pub source_photo_id: String,
    pub path: PathBuf,
    pub steps: Vec<ProcessingStep>,
    pub width_px: Option<u32>,
    pub height_px: Option<u32>,
    pub scale_to_original: Option<f64>,
}

impl DerivedImage {
    pub fn new(
        derived_id: impl Into<String>,
        source_photo_id: impl Into<String>,
        path: impl Into<PathBuf>,
        steps: Vec<ProcessingStep>,
    ) -> ContractResult<Self> {
        let derived_id = derived_id.into();
        let source_photo_id = source_photo_id.into();
        if derived_id.is_empty() || source_photo_id.is_empty() {
            return Err("DerivedImage requires derived_id and source_photo_id".into());
        }
        Ok(DerivedImage {
            derived_id,
            source_photo_id,
            path: path.into(),
            steps,
            width_px: None,
            height_px: None,
            scale_to_original: None,
        })
    }

    pub fn with_size(mut self, width_px: u32, height_px: u32) -> ContractResult<Self> {
        if width_px == 0 || height_px == 0 {
            return Err("DerivedImage width_px/height_px must be positive".into());
        }
        self.width_px = Some(width_px);
        self.height_px = Some(height_px);
        Ok(self)
    }

    pub fn with_scale_to_original(mut self, scale: f64) -> ContractResult<Self> {
        if !scale.is_finite() || scale <= 0.0 {
            return Err("scale_to_original must be positive and finite".into());
        }
        self.scale_to_original = Some(scale);
        Ok(self)
    }
}

/// Named radial/tangential distortion model (Python `DistortionModel`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DistortionModel {
    None,
    /// k1, k2, k3, p1, p2
    BrownConrady,
    Fisheye,
    /// k1, k2, p1, p2, k3
    OpenCv,
    Unknown,
}

impl DistortionModel {
    pub fn label(self) -> &'static str {
        match self {
            DistortionModel::None => "none",
            DistortionModel::BrownConrady => "brown_conrady",
            DistortionModel::Fisheye => "fisheye",
            DistortionModel::OpenCv => "opencv",
            DistortionModel::Unknown => "unknown",
        }
    }
}

/// Pinhole intrinsics in PIXEL units (Python `Intrinsics`).
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
pub struct Intrinsics {
    pub fx: f64,
    pub fy: f64,
    pub cx: f64,
    pub cy: f64,
    pub width_px: u32,
    pub height_px: u32,
    pub distortion_model: DistortionModel,
    pub distortion: Vec<f64>,
}

impl Intrinsics {
    pub fn new(
        fx: f64,
        fy: f64,
        cx: f64,
        cy: f64,
        width_px: u32,
        height_px: u32,
    ) -> ContractResult<Self> {
        if !fx.is_finite() || !fy.is_finite() || !cx.is_finite() || !cy.is_finite() {
            return Err("Intrinsics parameters must be finite".into());
        }
        if fx <= 0.0 || fy <= 0.0 {
            return Err("Intrinsics focal lengths must be positive".into());
        }
        if width_px == 0 || height_px == 0 {
            return Err("Intrinsics image size must be positive".into());
        }
        Ok(Intrinsics {
            fx,
            fy,
            cx,
            cy,
            width_px,
            height_px,
            distortion_model: DistortionModel::None,
            distortion: Vec::new(),
        })
    }

    pub fn with_distortion(
        mut self,
        model: DistortionModel,
        coefficients: Vec<f64>,
    ) -> ContractResult<Self> {
        if !coefficients.iter().all(|c| c.is_finite()) {
            return Err("Intrinsics distortion coefficients must be finite".into());
        }
        self.distortion_model = model;
        self.distortion = coefficients;
        Ok(self)
    }

    pub fn is_calibrated(&self) -> bool {
        self.distortion_model != DistortionModel::Unknown
    }
}

/// Camera pose in a stated [`SpatialFrame`] (Python `Extrinsics`).
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
pub struct Extrinsics {
    pub frame: SpatialFrame,
    pub quaternion_xyzw: [f64; 4],
    pub translation: Point3D,
    pub world_from_camera: bool,
}

impl Extrinsics {
    pub fn new(
        frame: SpatialFrame,
        quaternion_xyzw: [f64; 4],
        translation: Point3D,
        world_from_camera: bool,
    ) -> ContractResult<Self> {
        if !quaternion_xyzw.iter().all(|v| v.is_finite())
            || !translation.iter().all(|v| v.is_finite())
        {
            return Err("Extrinsics quaternion and translation must be finite".into());
        }
        let norm_sq: f64 = quaternion_xyzw.iter().map(|v| v * v).sum();
        if norm_sq <= 0.0 || !norm_sq.is_finite() {
            return Err("Extrinsics quaternion must have non-zero norm".into());
        }
        Ok(Extrinsics {
            frame,
            quaternion_xyzw,
            translation,
            world_from_camera,
        })
    }
}

/// A named camera body/lens configuration used by one or more photos (Python `Camera`).
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
pub struct Camera {
    pub camera_id: String,
    pub intrinsics: Intrinsics,
    pub make: Option<String>,
    pub model: Option<String>,
    pub sensor_mm_width: Option<f64>,
    pub calibrated: bool,
}

impl Camera {
    pub fn new(camera_id: impl Into<String>, intrinsics: Intrinsics) -> ContractResult<Self> {
        let camera_id = camera_id.into();
        if camera_id.is_empty() {
            return Err("Camera.camera_id must be set".into());
        }
        Ok(Camera {
            camera_id,
            intrinsics,
            make: None,
            model: None,
            sensor_mm_width: None,
            calibrated: false,
        })
    }

    #[must_use]
    pub fn with_make_model(mut self, make: impl Into<String>, model: impl Into<String>) -> Self {
        self.make = Some(make.into());
        self.model = Some(model.into());
        self
    }

    pub fn with_sensor_mm_width(mut self, width_mm: f64) -> ContractResult<Self> {
        if !width_mm.is_finite() || width_mm <= 0.0 {
            return Err("sensor_mm_width must be positive and finite".into());
        }
        self.sensor_mm_width = Some(width_mm);
        Ok(self)
    }

    #[must_use]
    pub fn with_calibrated(mut self, calibrated: bool) -> Self {
        self.calibrated = calibrated;
        self
    }
}

/// One 2D image measurement of a control point in one photo (Python
/// `PhotoObservation`, 05 §2). Pixels live here; surveyed 3D coordinates live
/// in [`ControlPoint`]. The two must never be conflated.
#[derive(Debug, Clone, PartialEq)]
#[non_exhaustive]
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
        if !x_px.is_finite() || !y_px.is_finite() {
            return Err("PhotoObservation pixel coordinates must be finite".into());
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

    /// Record a pixel observation while validating against `photo`'s pixel
    /// dimensions when known (`0.0 <= x_px <= width_px`, `0.0 <= y_px <= height_px`).
    pub fn new_in_photo(
        point_id: impl Into<String>,
        photo: &Photo,
        x_px: f64,
        y_px: f64,
    ) -> ContractResult<Self> {
        if let Some(w) = photo.width_px
            && !(0.0..=f64::from(w)).contains(&x_px)
        {
            return Err(format!(
                "x_px={x_px} is outside photo {:?} width {w}",
                photo.photo_id
            ));
        }
        if let Some(h) = photo.height_px
            && !(0.0..=f64::from(h)).contains(&y_px)
        {
            return Err(format!(
                "y_px={y_px} is outside photo {:?} height {h}",
                photo.photo_id
            ));
        }
        PhotoObservation::new(point_id, photo.photo_id.clone(), x_px, y_px)
    }

    pub fn with_sigma_px(mut self, sigma: f64) -> ContractResult<Self> {
        if !sigma.is_finite() || sigma < 0.0 {
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

/// Compute SHA-256 hex digest of an in-memory byte slice (FIPS 180-4, pure std).
#[must_use]
pub fn sha256_bytes(data: &[u8]) -> String {
    let mut hasher = Sha256State::new();
    hasher.update(data);
    hasher.finalize_hex()
}

/// Compute SHA-256 hex digest of a file in 64 KiB chunks (read-only, never modifies file).
pub fn sha256_file(path: impl AsRef<Path>) -> ContractResult<String> {
    let mut file = File::open(path.as_ref()).map_err(|e| format!("failed to open photo: {e}"))?;
    let mut hasher = Sha256State::new();
    let mut buf = [0u8; 65536];
    loop {
        let n = file
            .read(&mut buf)
            .map_err(|e| format!("failed to read photo: {e}"))?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    Ok(hasher.finalize_hex())
}

/// Inspect PNG (`IHDR`) or JPEG (`SOF0`..`SOF3`) image dimensions from the file
/// header without loading or decoding pixel data. Returns `None` if format is
/// unrecognized or truncated.
#[must_use]
pub fn inspect_image_dimensions(path: impl AsRef<Path>) -> Option<(u32, u32)> {
    let mut file = File::open(path.as_ref()).ok()?;
    let mut header = [0u8; 24];
    let n = file.read(&mut header).ok()?;
    if n >= 24
        && header[0..8] == [0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A]
        && &header[12..16] == b"IHDR"
    {
        let w = u32::from_be_bytes([header[16], header[17], header[18], header[19]]);
        let h = u32::from_be_bytes([header[20], header[21], header[22], header[23]]);
        return Some((w, h));
    }
    None
}

struct Sha256State {
    h: [u32; 8],
    buf: [u8; 64],
    buf_len: usize,
    total_len: u64,
}

impl Sha256State {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];

    fn new() -> Self {
        Sha256State {
            h: [
                0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
                0x5be0cd19,
            ],
            buf: [0u8; 64],
            buf_len: 0,
            total_len: 0,
        }
    }

    fn update(&mut self, mut data: &[u8]) {
        self.total_len = self.total_len.wrapping_add(data.len() as u64);
        if self.buf_len > 0 {
            let take = (64 - self.buf_len).min(data.len());
            self.buf[self.buf_len..self.buf_len + take].copy_from_slice(&data[..take]);
            self.buf_len += take;
            data = &data[take..];
            if self.buf_len == 64 {
                let block = self.buf;
                self.compress(&block);
                self.buf_len = 0;
            }
        }
        while data.len() >= 64 {
            let mut block = [0u8; 64];
            block.copy_from_slice(&data[..64]);
            self.compress(&block);
            data = &data[64..];
        }
        if !data.is_empty() {
            self.buf[..data.len()].copy_from_slice(data);
            self.buf_len = data.len();
        }
    }

    fn compress(&mut self, block: &[u8; 64]) {
        let mut w = [0u32; 64];
        for (i, chunk) in block.as_chunks::<4>().0.iter().enumerate() {
            w[i] = u32::from_be_bytes(*chunk);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut h] = self.h;
        for (&wi, &ki) in w.iter().zip(Self::K.iter()) {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let temp1 = h
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(ki)
                .wrapping_add(wi);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = s0.wrapping_add(maj);
            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }
        for (dst, add) in self.h.iter_mut().zip([a, b, c, d, e, f, g, h]) {
            *dst = dst.wrapping_add(add);
        }
    }

    fn finalize_hex(mut self) -> String {
        let bit_len = self.total_len.wrapping_mul(8);
        self.buf[self.buf_len] = 0x80;
        self.buf_len += 1;
        if self.buf_len > 56 {
            self.buf[self.buf_len..64].fill(0);
            let block = self.buf;
            self.compress(&block);
            self.buf_len = 0;
        }
        self.buf[self.buf_len..56].fill(0);
        self.buf[56..64].copy_from_slice(&bit_len.to_be_bytes());
        let block = self.buf;
        self.compress(&block);
        let mut out = String::with_capacity(64);
        for word in self.h {
            use std::fmt::Write as _;
            let _ = write!(&mut out, "{word:08x}");
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crs::LengthUnit;

    fn frame() -> SpatialFrame {
        SpatialFrame::new("LOCAL:test", LengthUnit::Meter).unwrap()
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
    fn point_contract_rejects_empty_id_non_finite_and_negative_sigma() {
        assert!(ControlPoint::new("", SurveyRole::Gcp, 0.0, 0.0, 0.0, frame()).is_err());
        assert!(ControlPoint::new("P", SurveyRole::Gcp, f64::NAN, 0.0, 0.0, frame()).is_err());
        assert!(ControlPoint::new("P", SurveyRole::Gcp, 0.0, f64::INFINITY, 0.0, frame()).is_err());
        let point = ControlPoint::new("GCP-01", SurveyRole::Gcp, 0.0, 0.0, 0.0, frame()).unwrap();
        assert!(point.clone().with_measured_sigma(-0.1).is_err());
        assert!(point.clone().with_measured_sigma(f64::NAN).is_err());
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
    fn observation_contract_rejects_empty_ids_and_out_of_bounds_pixels() {
        assert!(PhotoObservation::new("", "IMG_001", 10.0, 20.0).is_err());
        assert!(PhotoObservation::new("GCP-01", "", 10.0, 20.0).is_err());
        assert!(PhotoObservation::new("GCP-01", "IMG_001", f64::NAN, 20.0).is_err());
        let obs = PhotoObservation::new("GCP-01", "IMG_001", 10.5, 20.5).unwrap();
        assert!(obs.clone().with_sigma_px(-1.0).is_err());
        assert!(obs.clone().with_sigma_px(f64::INFINITY).is_err());
        let obs = obs.with_sigma_px(0.5).unwrap();
        assert!(!obs.photo_undistorted);
        assert!(obs.in_undistorted_plane().photo_undistorted);

        let sized_photo = Photo::new("IMG_001", "/tmp/x.png")
            .unwrap()
            .with_size(64, 48)
            .unwrap();
        assert!(PhotoObservation::new_in_photo("GCP-01", &sized_photo, 30.0, 24.0).is_ok());
        assert!(PhotoObservation::new_in_photo("GCP-01", &sized_photo, 65.0, 24.0).is_err());
        assert!(PhotoObservation::new_in_photo("GCP-01", &sized_photo, 30.0, -1.0).is_err());
    }

    #[test]
    fn derived_image_and_camera_contracts_enforced() {
        assert!(DerivedImage::new("", "P-01", "/tmp/d.jpg", vec![]).is_err());
        let d = DerivedImage::new(
            "d1",
            "P-01",
            "/tmp/d1.jpg",
            vec![ProcessingStep::Downscale, ProcessingStep::Undistort],
        )
        .unwrap()
        .with_scale_to_original(0.5)
        .unwrap();
        assert_eq!(d.source_photo_id, "P-01");
        assert_eq!(d.scale_to_original, Some(0.5));

        assert!(Intrinsics::new(0.0, 1000.0, 500.0, 500.0, 1000, 1000).is_err());
        assert!(Intrinsics::new(1000.0, 1000.0, 500.0, 500.0, 0, 1000).is_err());
        let intr = Intrinsics::new(3000.0, 3000.0, 2000.0, 1500.0, 4000, 3000)
            .unwrap()
            .with_distortion(
                DistortionModel::BrownConrady,
                vec![-0.1, 0.01, 0.0, 0.0, 0.0],
            )
            .unwrap();
        assert!(intr.is_calibrated());
        let cam = Camera::new("CAM-P4", intr)
            .unwrap()
            .with_make_model("DJI", "Phantom 4 Pro")
            .with_sensor_mm_width(13.2)
            .unwrap()
            .with_calibrated(true);
        assert!(cam.calibrated);

        assert!(Extrinsics::new(frame(), [0.0, 0.0, 0.0, 0.0], [0.0; 3], true).is_err());
        assert!(Extrinsics::new(frame(), [0.0, 0.0, 0.0, 1.0], [1.0, 2.0, 3.0], true).is_ok());
    }

    #[test]
    fn sha256_and_png_ingest_preserve_original_bytes() {
        assert_eq!(
            sha256_bytes(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            sha256_bytes(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        // Synthetic PNG header (64x48) in temp dir
        let dir = std::env::temp_dir().join(format!("archphoto_test_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let png_path = dir.join("SYNTH_001.png");
        let mut png_bytes = Vec::new();
        png_bytes.extend_from_slice(&[0x89, b'P', b'N', b'G', 0x0D, 0x0A, 0x1A, 0x0A]);
        png_bytes.extend_from_slice(&13u32.to_be_bytes());
        png_bytes.extend_from_slice(b"IHDR");
        png_bytes.extend_from_slice(&64u32.to_be_bytes());
        png_bytes.extend_from_slice(&48u32.to_be_bytes());
        png_bytes.extend_from_slice(&[8, 2, 0, 0, 0]);
        std::fs::write(&png_path, &png_bytes).unwrap();

        let photo = Photo::from_file("SYNTH_001", &png_path).unwrap();
        assert_eq!(photo.width_px, Some(64));
        assert_eq!(photo.height_px, Some(48));
        assert_eq!(photo.sha256, Some(sha256_bytes(&png_bytes)));
        assert_eq!(std::fs::read(&png_path).unwrap(), png_bytes);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
