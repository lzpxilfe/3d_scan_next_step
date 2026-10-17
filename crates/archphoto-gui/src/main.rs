//! archphoto GUI (egui 0.37) — interactive survey workflow + synthetic demos
//! (D-2026-10-12-09 layout → D-2026-10-12-11 Rust switch).
//!
//! COVERAGE — honest, slice-scoped:
//!   * Interactive workflow (ported from Python `gui/main_window.py`):
//!     - Read-only photo ingest (`Photo::from_file` + `ProjectManifest` SHA-256
//!       registration + `verify_raw_integrity`), capture role assignment;
//!     - Explicit `SpatialFrame` editor (`crs_id`, `LengthUnit`, `AxisOrder`,
//!       `VerticalDatum`, `geoid_model`) required before any control point or
//!       distance measurement;
//!     - `ControlPoint` entry, table selection, honest height-reference readout
//!       (`해발` / `타원체고` / `현지 Z` / `Z (기준 미상)`), and `preflight_control`;
//!     - Interactive Photo Viewer canvas recording `PhotoObservation::new_in_photo`
//!       on original pixels (`photo_undistorted = false`), replacing duplicate
//!       `(point_id, photo_id)` pairs, and drawing role-colored crosshairs;
//!     - Interactive distance measurement (`measure_distance` + `length_residual`),
//!       always labeled `"좌표 산출값 — 직접 실측이 아님"`.
//!   * Synthetic contract demos (`fit_rigid_transform`, `register_blocks_ransac`,
//!     `evaluate_check`, `merge_blocks`, `mesh_sidecar`, `compute_section`,
//!     `OrthoProduct`, `run_baseline`, and refusal demonstrations) with a
//!     persistent `PointUsageLedger`.

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

use eframe::egui;

use archphoto_core::Point3D;
use archphoto_core::baseline::{BaselineEngine, BaselineInputs, run_baseline};
use archphoto_core::crs::{AxisOrder, LengthUnit, SpatialFrame, VerticalDatum};
use archphoto_core::export::write_ply_string;
use archphoto_core::measure::{Measurement, length_residual, measure_distance};
use archphoto_core::mesh::{OriginKind, ProductKind, mesh_sidecar};
use archphoto_core::ortho::{OrthoGrid, OrthoProduct, OrthoSpec};
use archphoto_core::plane::Plane;
use archphoto_core::preflight::{PreflightIssue, preflight_control};
use archphoto_core::project::{ProjectManifest, RawItem, RawKind};
use archphoto_core::quality::{
    CheckValidation, ModelMap, PointUsageLedger, apply_gcp_constraint, evaluate_check,
};
use archphoto_core::register::{
    Block, RegistrationResult, SimilarityFit, TiePoint, apply_similarity, fit_rigid_transform,
    merge_blocks, register_blocks_ransac,
};
use archphoto_core::runlog::ProcessState;
use archphoto_core::section::compute_section;
use archphoto_core::sensing::{CaptureRole, ControlPoint, Photo, PhotoObservation, SurveyRole};

const HALF_SQRT2: f64 = std::f64::consts::FRAC_1_SQRT_2;

pub const TOOLBAR_ACTIONS: &[(&str, &str)] = &[
    ("photos", "사진 가져오기"),
    ("camera", "카메라"),
    ("control", "GCP·기준점"),
    ("measure", "거리 측정"),
    ("stitch", "정합(붙이기)"),
    ("section", "단면"),
    ("ortho", "정사영상"),
    ("mesh", "메시"),
    ("validate", "검증"),
    ("export", "내보내기"),
];

pub const PIPELINE_STAGES: &[(&str, &str)] = &[
    ("photos", "사진 입력"),
    ("camera", "카메라 보정"),
    ("control", "기준점 / 검증점"),
    ("stitch", "정합 (붙이기)"),
    ("recon", "밀집 복원"),
    ("mesh", "메시 생성"),
    ("validate", "독립 검증"),
    ("export", "내보내기"),
];

fn survey_role_label(role: SurveyRole) -> &'static str {
    match role {
        SurveyRole::Gcp => "GCP (보정)",
        SurveyRole::Scale => "축척 (SCALE)",
        SurveyRole::Constraint => "제약 (CONSTRAINT)",
        SurveyRole::Check => "검증점",
        SurveyRole::CheckLength => "길이 검증",
    }
}

fn survey_role_color(role: SurveyRole) -> egui::Color32 {
    match role {
        SurveyRole::Gcp => egui::Color32::from_rgb(0x2e, 0x7d, 0x32),
        SurveyRole::Scale => egui::Color32::from_rgb(0xef, 0x6c, 0x00),
        SurveyRole::Constraint => egui::Color32::from_rgb(0x6a, 0x1b, 0x9a),
        SurveyRole::Check => egui::Color32::from_rgb(0x15, 0x65, 0xc0),
        SurveyRole::CheckLength => egui::Color32::from_rgb(0x00, 0x83, 0x8f),
    }
}

fn capture_role_ko(role: CaptureRole) -> &'static str {
    match role {
        CaptureRole::Object => "피사체",
        CaptureRole::Scale => "축척기준",
        CaptureRole::Reference => "참고",
        CaptureRole::Unknown => "미상",
    }
}

fn datum_readout(datum: VerticalDatum) -> (&'static str, &'static str) {
    match datum {
        VerticalDatum::Orthometric => ("해발", "정고도"),
        VerticalDatum::Ellipsoidal => ("타원체고", "타원체"),
        VerticalDatum::Local => ("현지 Z", "현지 수준점"),
        VerticalDatum::Unknown => ("Z", "기준 미상"),
    }
}

fn unique_photo_id(stem: &str, taken: &HashSet<String>) -> String {
    if !taken.contains(stem) {
        return stem.to_string();
    }
    let mut n = 2usize;
    loop {
        let candidate = format!("{stem}-{n}");
        if !taken.contains(&candidate) {
            return candidate;
        }
        n += 1;
    }
}

fn fmt_coord(v: f64) -> String {
    if v.fract() == 0.0 && v.abs() < 1e12 {
        format!("{}", v as i64)
    } else {
        let s = format!("{v:.6}");
        s.trim_end_matches('0').trim_end_matches('.').to_string()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RightTab {
    Control,
    Measure,
    Demo,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CentralTab {
    PhotoViewer,
    PipelineAndDemo,
    Viewport3D,
}

/// The built-in synthetic dataset: a known 90°-about-z + translation mapping,
/// with ties T0/T1 corrupted so RANSAC has real outliers to reject.
struct Demo {
    frame: SpatialFrame,
    ties: Vec<TiePoint>,
    clean_checks: Vec<ControlPoint>,
    clean_model: ModelMap,
}

impl Demo {
    fn new() -> Self {
        let frame = SpatialFrame::new("LOCAL:demo", LengthUnit::Millimeter)
            .unwrap()
            .with_vertical_datum(VerticalDatum::Local);
        let clear = |p: Point3D| {
            apply_similarity([0.0, 0.0, HALF_SQRT2, HALF_SQRT2], [1.0, 2.0, 3.0], 1.0, p)
        };
        let src: [Point3D; 6] = [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
            [1.0, 1.0, 1.0],
            [2.0, 1.0, 3.0],
        ];
        let mut ties: Vec<TiePoint> = src
            .iter()
            .enumerate()
            .map(|(i, s)| TiePoint::new(format!("T{i}"), *s, clear(*s)))
            .collect();
        ties[0] = TiePoint::new("T0", src[0], [100.0, 100.0, 100.0]);
        ties[1] = TiePoint::new("T1", src[1], [-50.0, 200.0, 0.0]);

        let mk = |id: &str, x: f64, y: f64, z: f64| {
            ControlPoint::new(id, SurveyRole::Check, x, y, z, frame.clone()).unwrap()
        };
        let clean_checks = vec![mk("CHK-A", 0.0, 0.0, 0.0), mk("CHK-B", 10.0, 0.0, 0.0)];
        let mut clean_model = ModelMap::new();
        clean_model.insert("CHK-A".to_string(), [0.1, -0.2, 0.02]);
        clean_model.insert("CHK-B".to_string(), [10.02, 0.0, 0.02]);

        Demo {
            frame,
            ties,
            clean_checks,
            clean_model,
        }
    }
}

struct SyntheticOffsetEngine;
impl BaselineEngine for SyntheticOffsetEngine {
    fn reconstruct(&self, inputs: &BaselineInputs) -> archphoto_core::ContractResult<ModelMap> {
        Ok(inputs
            .control_points
            .iter()
            .map(|p| (p.point_id.clone(), [p.x + 0.05, p.y - 0.05, p.z]))
            .collect())
    }
}

pub struct App {
    // ── Project & survey state ──────────────────────────────────────────
    pub manifest: ProjectManifest,
    pub photos: Vec<Photo>,
    pub selected_photo_idx: Option<usize>,
    pub loaded_viewer_photo_id: Option<String>,
    pub photo_path_input: String,
    pub pending_capture_role: CaptureRole,

    pub control_frame: Option<SpatialFrame>,
    pub crs_input: String,
    pub unit_input: LengthUnit,
    pub axis_input: AxisOrder,
    pub datum_input: VerticalDatum,
    pub geoid_input: String,
    pub frame_status: String,

    pub control_points: Vec<ControlPoint>,
    pub selected_point_idx: Option<usize>,
    pub pt_id_input: String,
    pub pt_role_input: SurveyRole,
    pub pt_x_input: String,
    pub pt_y_input: String,
    pub pt_z_input: String,
    pub pt_sigma_input: String,
    pub pt_source_input: String,

    pub observations: Vec<PhotoObservation>,
    pub measurements: Vec<Measurement>,
    pub measure_a_inputs: [String; 3],
    pub measure_b_inputs: [String; 3],
    pub measure_ref_input: String,
    pub measure_result_text: String,

    pub pipeline_states: HashMap<String, String>,
    pub pipeline_notes: HashMap<String, String>,
    pub readout_text: String,

    // ── Synthetic demo & ledger state ───────────────────────────────────
    demo: Demo,
    pub ledger: PointUsageLedger,
    pub log: Vec<String>,
    fit: Option<SimilarityFit>,
    registration: Option<RegistrationResult>,
    validation: Option<CheckValidation>,
    issues: Vec<String>,
    merge_summary: Option<String>,
    archaeo_summary: Option<String>,
    baseline_summary: Option<String>,
    check_as_constraint_refusal: Option<String>,

    right_tab: RightTab,
    central_tab: CentralTab,
}

impl Default for App {
    fn default() -> Self {
        Self::new()
    }
}

impl App {
    #[must_use]
    pub fn new() -> Self {
        let mut pipeline_states = HashMap::new();
        let mut pipeline_notes = HashMap::new();
        for &(key, _) in PIPELINE_STAGES {
            pipeline_states.insert(key.to_string(), ProcessState::NotStarted.ko_label().into());
            pipeline_notes.insert(key.to_string(), "—".into());
        }

        App {
            manifest: ProjectManifest::new("archphoto-session", "제목 미설정").unwrap(),
            photos: Vec::new(),
            selected_photo_idx: None,
            loaded_viewer_photo_id: None,
            photo_path_input: String::new(),
            pending_capture_role: CaptureRole::Object,

            control_frame: None,
            crs_input: String::new(),
            unit_input: LengthUnit::Meter,
            axis_input: AxisOrder::EastNorth,
            datum_input: VerticalDatum::Orthometric,
            geoid_input: String::new(),
            frame_status: "좌표계 프레임: 미설정 (기준점·측정 전에 적용 필요)".into(),

            control_points: Vec::new(),
            selected_point_idx: None,
            pt_id_input: String::new(),
            pt_role_input: SurveyRole::Gcp,
            pt_x_input: String::new(),
            pt_y_input: String::new(),
            pt_z_input: String::new(),
            pt_sigma_input: String::new(),
            pt_source_input: String::new(),

            observations: Vec::new(),
            measurements: Vec::new(),
            measure_a_inputs: [String::new(), String::new(), String::new()],
            measure_b_inputs: [String::new(), String::new(), String::new()],
            measure_ref_input: String::new(),
            measure_result_text: "결과: —".into(),

            pipeline_states,
            pipeline_notes,
            readout_text: "좌표: —  ·  해발: —".into(),

            demo: Demo::new(),
            ledger: PointUsageLedger::default(),
            log: vec![
                "프로젝트 시작 — 원본은 읽기 전용입니다. 좌표계 프레임을 먼저 적용하세요."
                    .to_string(),
            ],
            fit: None,
            registration: None,
            validation: None,
            issues: Vec::new(),
            merge_summary: None,
            archaeo_summary: None,
            baseline_summary: None,
            check_as_constraint_refusal: None,

            right_tab: RightTab::Control,
            central_tab: CentralTab::PipelineAndDemo,
        }
    }

    pub fn push_log(&mut self, line: impl Into<String>) {
        self.log.push(line.into());
    }

    pub fn log_text(&self) -> String {
        self.log.join("\n")
    }

    // ── Toolbar dispatch ────────────────────────────────────────────────

    pub fn on_tool(&mut self, name: &str) {
        match name {
            "photos" => {
                self.central_tab = CentralTab::PhotoViewer;
            }
            "control" => {
                self.right_tab = RightTab::Control;
            }
            "measure" => {
                self.right_tab = RightTab::Measure;
            }
            other => {
                let label = TOOLBAR_ACTIONS
                    .iter()
                    .find(|&&(k, _)| k == other)
                    .map_or(other, |&(_, v)| v);
                self.push_log(format!("미구현: {label} (스캐폴드 단계 — 가짜 동작 없음)"));
            }
        }
    }

    // ── Photo ingest & role management ──────────────────────────────────

    /// Register original photos in read-only mode (SHA-256 + PNG IHDR size).
    /// Never modifies the original files.
    pub fn import_photo_paths(&mut self, paths: &[PathBuf]) -> Vec<Photo> {
        let mut imported = Vec::new();
        let mut unreadable_size = 0usize;
        let mut known_paths: HashSet<PathBuf> = self
            .photos
            .iter()
            .map(|p| p.path.canonicalize().unwrap_or_else(|_| p.path.clone()))
            .collect();
        let mut taken_ids: HashSet<String> =
            self.photos.iter().map(|p| p.photo_id.clone()).collect();

        for path in paths {
            if !path.is_file() {
                self.push_log(format!("오류(파일 없음): {}", path.display()));
                continue;
            }
            let key = path.canonicalize().unwrap_or_else(|_| path.clone());
            if known_paths.contains(&key) {
                let fname = path.file_name().and_then(|s| s.to_str()).unwrap_or("");
                self.push_log(format!("건너뜀(이미 등록): {fname}"));
                continue;
            }
            let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("photo");
            let photo_id = unique_photo_id(stem, &taken_ids);
            let Ok(photo) = Photo::from_file(&photo_id, &key) else {
                self.push_log(format!("오류(사진 판독 실패): {}", path.display()));
                continue;
            };
            if photo.width_px.is_none() || photo.height_px.is_none() {
                unreadable_size += 1;
            }
            if let Ok(raw_item) = RawItem::from_file(&key, RawKind::Photo) {
                self.manifest.register_raw(raw_item);
            }
            known_paths.insert(key);
            taken_ids.insert(photo_id.clone());
            let fname = path.file_name().and_then(|s| s.to_str()).unwrap_or("");
            self.push_log(format!(
                "사진 등록: {photo_id} ({fname}, 해시 등록, 원본 읽기 전용)"
            ));
            self.photos.push(photo.clone());
            imported.push(photo);
        }

        if !imported.is_empty() {
            self.pipeline_states
                .insert("photos".into(), ProcessState::Succeeded.ko_label().into());
            self.pipeline_notes
                .insert("photos".into(), format!("{}장", self.photos.len()));
            if self.loaded_viewer_photo_id.is_none() {
                self.loaded_viewer_photo_id = self.photos.first().map(|p| p.photo_id.clone());
            }
            if unreadable_size > 0 {
                self.push_log(format!(
                    "크기 미판독 {unreadable_size}장 — 필요 시 원본 형식을 확인하세요."
                ));
            }
        }
        imported
    }

    pub fn apply_selected_photo_role(&mut self, role: CaptureRole) -> bool {
        let Some(idx) = self.selected_photo_idx else {
            self.push_log("역할 적용: 목록에서 사진을 먼저 선택하세요.");
            return false;
        };
        let Some(existing) = self.photos.get(idx).cloned() else {
            return false;
        };
        let photo_id = existing.photo_id.clone();
        self.photos[idx] = existing.with_capture_role(role);
        self.push_log(format!("역할 변경: {photo_id} → {}", capture_role_ko(role)));
        true
    }

    pub fn verify_manifest_integrity(&mut self) -> Vec<String> {
        let bad = self.manifest.verify_raw_integrity();
        if bad.is_empty() {
            self.push_log(format!(
                "원본 무결성 검증: 등록 원자료 {}건 모두 SHA-256 일치 (무훼손)",
                self.manifest.raw_items.len()
            ));
        } else {
            self.push_log(format!(
                "원본 무결성 오류: {}건 불일치 ({})",
                bad.len(),
                bad.join(", ")
            ));
        }
        bad
    }

    // ── SpatialFrame & ControlPoint management ──────────────────────────

    pub fn set_control_frame(
        &mut self,
        crs_id: &str,
        unit: LengthUnit,
        axis_order: AxisOrder,
        vertical_datum: VerticalDatum,
        geoid_model: Option<String>,
    ) -> bool {
        let Ok(base) = SpatialFrame::new(crs_id, unit) else {
            self.push_log("오류: 좌표계 ID가 비어 있습니다. (예: EPSG:5186 또는 LOCAL:현장명)");
            return false;
        };
        let mut frame = base
            .with_axis_order(axis_order)
            .with_vertical_datum(vertical_datum);
        if let Some(g) = geoid_model
            && !g.trim().is_empty()
        {
            frame = frame.with_geoid_model(g.trim());
        }
        if !self.control_points.is_empty() && self.control_frame.as_ref() != Some(&frame) {
            self.push_log(format!(
                "주의: 프레임 변경 — 기존 점 {}개는 이전 프레임을 유지합니다.",
                self.control_points.len()
            ));
        }
        let (_, datum_name) = datum_readout(frame.vertical_datum);
        self.frame_status = format!(
            "좌표계 프레임: {} · {} · {} · {datum_name}",
            frame.crs_id,
            frame.unit.label(),
            frame.axis_order.label()
        );
        self.push_log(format!(
            "좌표계 프레임 적용: {}, 단위 {}, 높이 기준 {datum_name}",
            frame.crs_id,
            frame.unit.label()
        ));
        self.manifest = self.manifest.clone().with_crs_id(frame.crs_id.clone());
        self.control_frame = Some(frame);
        true
    }

    #[allow(clippy::too_many_arguments)]
    pub fn add_control_point(
        &mut self,
        point_id: &str,
        role: SurveyRole,
        x: f64,
        y: f64,
        z: f64,
        sigma: Option<f64>,
        source: &str,
    ) -> Option<ControlPoint> {
        let Some(frame) = self.control_frame.clone() else {
            self.push_log(format!(
                "거부: {} — 좌표계 프레임을 먼저 적용하세요.",
                if point_id.is_empty() {
                    "(이름 없음)"
                } else {
                    point_id
                }
            ));
            return None;
        };
        let mut pt = match ControlPoint::new(point_id, role, x, y, z, frame) {
            Ok(p) => p,
            Err(e) => {
                self.push_log(format!("거부: 기준점 생성 실패 ({e})"));
                return None;
            }
        };
        if let Some(s) = sigma {
            match pt.with_measured_sigma(s) {
                Ok(p) => pt = p,
                Err(e) => {
                    self.push_log(format!("거부: σ 값 오류 ({e})"));
                    return None;
                }
            }
        }
        if !source.trim().is_empty() {
            pt = pt.with_source(source.trim());
        }
        self.control_points.push(pt.clone());
        let idx = self.control_points.len() - 1;
        self.selected_point_idx = Some(idx);
        self.update_readout(&pt);
        self.update_control_note();
        self.push_log(format!(
            "기준점 추가: {} ({})",
            pt.point_id,
            survey_role_label(pt.role)
        ));
        Some(pt)
    }

    pub fn select_control_point(&mut self, idx: usize) {
        if let Some(pt) = self.control_points.get(idx).cloned() {
            self.selected_point_idx = Some(idx);
            self.update_readout(&pt);
        }
    }

    fn update_readout(&mut self, point: &ControlPoint) {
        let frame = &point.frame;
        let (z_name, datum_name) = datum_readout(frame.vertical_datum);
        self.readout_text = format!(
            "X {:.3}  Y {:.3}  {z_name} {:.3}  ·  {} ({}, {datum_name})",
            point.x,
            point.y,
            point.z,
            frame.crs_id,
            frame.unit.label()
        );
    }

    fn update_control_note(&mut self) {
        let gcp = self
            .control_points
            .iter()
            .filter(|p| p.role == SurveyRole::Gcp)
            .count();
        let check = self
            .control_points
            .iter()
            .filter(|p| p.role.is_independent_check())
            .count();
        self.pipeline_notes.insert(
            "control".into(),
            format!(
                "점 {}개 (GCP {gcp}, 검증 {check}, 관측 {}건)",
                self.control_points.len(),
                self.observations.len()
            ),
        );
    }

    pub fn run_user_preflight(&mut self) -> Vec<PreflightIssue> {
        let obs_opt = if self.observations.is_empty() {
            None
        } else {
            Some(self.observations.as_slice())
        };
        let issues = preflight_control(&self.control_points, obs_opt);
        if issues.is_empty() {
            self.push_log("계약 점검: 문제 없음 (데이터 계약 기준 — 측량 검증이 아님)");
        }
        for issue in &issues {
            self.push_log(format!(
                "계약 점검 [{}] {}",
                issue.severity.label(),
                issue.message
            ));
        }
        self.issues = issues
            .iter()
            .map(|i| format!("[{} {}] {}", i.severity.label(), i.code, i.message))
            .collect();
        issues
    }

    // ── Distance measurement ────────────────────────────────────────────

    pub fn fill_measure_from_selected(&mut self, which: char) -> bool {
        let Some(idx) = self.selected_point_idx else {
            self.push_log("측정 채우기: 기준점 테이블에서 점을 먼저 선택하세요.");
            return false;
        };
        let Some(pt) = self.control_points.get(idx) else {
            return false;
        };
        let formatted = [fmt_coord(pt.x), fmt_coord(pt.y), fmt_coord(pt.z)];
        match which {
            'a' | 'A' => self.measure_a_inputs = formatted,
            'b' | 'B' => self.measure_b_inputs = formatted,
            _ => return false,
        }
        true
    }

    pub fn set_measure_point(&mut self, which: char, x: f64, y: f64, z: f64) {
        let formatted = [fmt_coord(x), fmt_coord(y), fmt_coord(z)];
        if which == 'a' || which == 'A' {
            self.measure_a_inputs = formatted;
        } else if which == 'b' || which == 'B' {
            self.measure_b_inputs = formatted;
        }
    }

    pub fn parse_measure_point(&self, which: char) -> Option<Point3D> {
        let arr = if which == 'a' || which == 'A' {
            &self.measure_a_inputs
        } else {
            &self.measure_b_inputs
        };
        let x = arr[0].trim().parse::<f64>().ok()?;
        let y = arr[1].trim().parse::<f64>().ok()?;
        let z = arr[2].trim().parse::<f64>().ok()?;
        Some([x, y, z])
    }

    pub fn run_user_measure(&mut self) -> Option<Measurement> {
        let Some(frame) = self.control_frame.clone() else {
            self.push_log("거부: 측정은 좌표계 프레임을 적용한 뒤 가능합니다.");
            return None;
        };
        let (Some(a), Some(b)) = (self.parse_measure_point('a'), self.parse_measure_point('b'))
        else {
            self.push_log("오류: 측정할 두 점의 좌표를 숫자로 입력하세요.");
            return None;
        };
        let Ok(m) = measure_distance(a, b, &frame) else {
            self.push_log("오류: 측정 좌표가 유한한 숫자가 아닙니다.");
            return None;
        };
        let unit = frame.unit.label();
        let mut text = format!(
            "거리: {:.3} {unit} (좌표 산출값 — 직접 실측이 아님)",
            m.value
        );
        let ref_trimmed = self.measure_ref_input.trim();
        if !ref_trimmed.is_empty() {
            if let Ok(ref_val) = ref_trimmed.parse::<f64>()
                && let Ok(res) = length_residual(&m, ref_val)
            {
                text.push_str(&format!(" · 기준 대차: {res:+.3} {unit}"));
                self.push_log(format!(
                    "측정 A{a:?}→B{b:?} = {:.3} {unit} (기준 {}, 대차 {res:+.3})",
                    m.value,
                    fmt_coord(ref_val)
                ));
            } else {
                self.push_log("오류: 기준 길이는 양의 유한 숫자로 입력하세요.");
            }
        } else {
            self.push_log(format!("측정 A{a:?}→B{b:?} = {:.3} {unit}", m.value));
        }
        self.measure_result_text = text;
        self.measurements.push(m.clone());
        Some(m)
    }

    // ── Photo viewer & pixel observations ───────────────────────────────

    pub fn load_photo_in_viewer(&mut self, photo_id: &str) -> bool {
        if self.photos.iter().any(|p| p.photo_id == photo_id) {
            self.loaded_viewer_photo_id = Some(photo_id.to_string());
            self.central_tab = CentralTab::PhotoViewer;
            true
        } else {
            false
        }
    }

    pub fn record_pixel_observation(
        &mut self,
        point_id: Option<&str>,
        photo_id: Option<&str>,
        x_px: f64,
        y_px: f64,
    ) -> bool {
        let (Some(point_id), Some(photo_id)) = (point_id, photo_id) else {
            self.push_log("거부: 관측할 기준점이 선택되지 않았거나 사진이 로드되지 않았습니다.");
            return false;
        };
        let Some(photo) = self.photos.iter().find(|p| p.photo_id == photo_id).cloned() else {
            self.push_log("거부: 관측할 기준점이 선택되지 않았거나 사진이 로드되지 않았습니다.");
            return false;
        };
        if !self.control_points.iter().any(|p| p.point_id == point_id) {
            self.push_log(format!(
                "거부: 관측 대상 점 {point_id:?}을 찾을 수 없습니다."
            ));
            return false;
        }
        let obs = match PhotoObservation::new_in_photo(point_id, &photo, x_px, y_px) {
            Ok(o) => o,
            Err(e) => {
                self.push_log(format!("거부: {e}"));
                return false;
            }
        };
        self.observations
            .retain(|o| !(o.point_id == point_id && o.photo_id == photo_id));
        self.observations.push(obs);
        self.update_control_note();
        self.push_log(format!(
            "픽셀 관측: {point_id} @ {photo_id} = ({x_px:.1}, {y_px:.1}) px (원본 픽셀)"
        ));
        true
    }

    pub fn viewer_markers_for_loaded_photo(&self) -> Vec<&PhotoObservation> {
        let Some(photo_id) = self.loaded_viewer_photo_id.as_deref() else {
            return Vec::new();
        };
        self.observations
            .iter()
            .filter(|o| o.photo_id == photo_id)
            .collect()
    }
}

impl eframe::App for App {
    fn ui(&mut self, root: &mut egui::Ui, _frame: &mut eframe::Frame) {
        egui::Panel::top("toolbar").show(root, |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.strong("archphoto — 고고학 사진실측 (Rust)");
                ui.separator();
                let actions: Vec<(&str, &str)> = TOOLBAR_ACTIONS.to_vec();
                for (name, label) in actions {
                    if ui.button(label).clicked() {
                        self.on_tool(name);
                    }
                }
            });
        });

        egui::Panel::bottom("statusbar_and_log").show(root, |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.monospace(&self.readout_text);
                ui.separator();
                ui.label(format!(
                    "원장: 구속 {} · 정합 {} · 검증 {}",
                    self.ledger.constraint().len(),
                    self.ledger.alignment().len(),
                    self.ledger.evaluation().len()
                ));
            });
            ui.separator();
            ui.heading("로그");
            egui::ScrollArea::vertical()
                .max_height(120.0)
                .show(ui, |ui| {
                    for line in &self.log {
                        ui.monospace(line);
                    }
                });
        });

        egui::Panel::left("photos")
            .default_size(240.0)
            .show(root, |ui| {
                self.ui_left_photos(ui);
            });

        egui::Panel::right("right_dock")
            .default_size(360.0)
            .show(root, |ui| {
                ui.horizontal(|ui| {
                    ui.selectable_value(&mut self.right_tab, RightTab::Control, "기준점");
                    ui.selectable_value(&mut self.right_tab, RightTab::Measure, "거리 측정");
                    ui.selectable_value(&mut self.right_tab, RightTab::Demo, "합성 데모");
                });
                ui.separator();
                match self.right_tab {
                    RightTab::Control => self.ui_right_control(ui),
                    RightTab::Measure => self.ui_right_measure(ui),
                    RightTab::Demo => self.ui_right_demo(ui),
                }
            });

        egui::CentralPanel::default().show(root, |ui| {
            ui.horizontal(|ui| {
                ui.selectable_value(
                    &mut self.central_tab,
                    CentralTab::PipelineAndDemo,
                    "파이프라인 · 검증 요약",
                );
                ui.selectable_value(
                    &mut self.central_tab,
                    CentralTab::PhotoViewer,
                    "사진 뷰어 (픽셀 관측)",
                );
                ui.selectable_value(
                    &mut self.central_tab,
                    CentralTab::Viewport3D,
                    "3D 뷰포트(예정)",
                );
            });
            ui.separator();
            match self.central_tab {
                CentralTab::PipelineAndDemo => self.ui_central_pipeline(ui),
                CentralTab::PhotoViewer => self.ui_central_photo_viewer(ui),
                CentralTab::Viewport3D => {
                    ui.centered_and_justified(|ui| {
                        ui.label(
                            "3D 메시 뷰포트 — wgpu 렌더 파이프라인 연결 예정 (가짜 뷰포트 없음)",
                        );
                    });
                }
            }
        });
    }
}

impl App {
    fn ui_left_photos(&mut self, ui: &mut egui::Ui) {
        ui.heading("사진 (원본 읽기 전용)");
        ui.horizontal(|ui| {
            ui.text_edit_singleline(&mut self.photo_path_input);
            if ui.button("경로 등록").clicked() {
                let p = PathBuf::from(self.photo_path_input.trim());
                self.import_photo_paths(&[p]);
                self.photo_path_input.clear();
            }
        });

        if self.photos.is_empty() {
            ui.label("등록된 사진 없음");
        } else {
            let mut open_id: Option<String> = None;
            for (idx, p) in self.photos.iter().enumerate() {
                let selected = self.selected_photo_idx == Some(idx);
                let dim_text = match (p.width_px, p.height_px) {
                    (Some(w), Some(h)) => format!("{w}×{h}"),
                    _ => "크기미상".into(),
                };
                let label = format!(
                    "{} [{}] ({dim_text})",
                    p.photo_id,
                    capture_role_ko(p.capture_role)
                );
                let resp = ui.selectable_label(selected, label);
                if resp.clicked() {
                    self.selected_photo_idx = Some(idx);
                }
                if resp.double_clicked() {
                    open_id = Some(p.photo_id.clone());
                }
            }
            if let Some(id) = open_id {
                self.load_photo_in_viewer(&id);
            }
        }

        ui.separator();
        ui.horizontal(|ui| {
            egui::ComboBox::from_id_salt("capture_role_combo")
                .selected_text(capture_role_ko(self.pending_capture_role))
                .show_ui(ui, |ui| {
                    for r in [
                        CaptureRole::Object,
                        CaptureRole::Scale,
                        CaptureRole::Reference,
                        CaptureRole::Unknown,
                    ] {
                        ui.selectable_value(&mut self.pending_capture_role, r, capture_role_ko(r));
                    }
                });
            if ui.button("역할 적용").clicked() {
                let role = self.pending_capture_role;
                self.apply_selected_photo_role(role);
            }
        });

        if ui.button("원본 무결성 검증 (SHA-256)").clicked() {
            self.verify_manifest_integrity();
        }
    }

    fn ui_right_control(&mut self, ui: &mut egui::Ui) {
        ui.strong(&self.frame_status);
        ui.horizontal(|ui| {
            ui.label("CRS:");
            ui.text_edit_singleline(&mut self.crs_input);
        });
        ui.horizontal(|ui| {
            egui::ComboBox::from_id_salt("unit_combo")
                .selected_text(self.unit_input.label())
                .show_ui(ui, |ui| {
                    for u in [
                        LengthUnit::Millimeter,
                        LengthUnit::Centimeter,
                        LengthUnit::Meter,
                    ] {
                        ui.selectable_value(&mut self.unit_input, u, u.label());
                    }
                });
            egui::ComboBox::from_id_salt("axis_combo")
                .selected_text(self.axis_input.label())
                .show_ui(ui, |ui| {
                    for a in [AxisOrder::EastNorth, AxisOrder::NorthEast] {
                        ui.selectable_value(&mut self.axis_input, a, a.label());
                    }
                });
            egui::ComboBox::from_id_salt("datum_combo")
                .selected_text(datum_readout(self.datum_input).1)
                .show_ui(ui, |ui| {
                    for d in [
                        VerticalDatum::Orthometric,
                        VerticalDatum::Ellipsoidal,
                        VerticalDatum::Local,
                        VerticalDatum::Unknown,
                    ] {
                        ui.selectable_value(&mut self.datum_input, d, datum_readout(d).1);
                    }
                });
        });
        if ui.button("좌표계 프레임 적용").clicked() {
            let crs = self.crs_input.trim().to_string();
            let unit = self.unit_input;
            let axis = self.axis_input;
            let datum = self.datum_input;
            let geoid = if self.geoid_input.trim().is_empty() {
                None
            } else {
                Some(self.geoid_input.trim().to_string())
            };
            self.set_control_frame(&crs, unit, axis, datum, geoid);
        }

        ui.separator();
        ui.strong("기준점 / 독립 검증점 추가");
        ui.horizontal(|ui| {
            ui.label("ID:");
            ui.text_edit_singleline(&mut self.pt_id_input);
            egui::ComboBox::from_id_salt("survey_role_combo")
                .selected_text(survey_role_label(self.pt_role_input))
                .show_ui(ui, |ui| {
                    for r in [
                        SurveyRole::Gcp,
                        SurveyRole::Scale,
                        SurveyRole::Constraint,
                        SurveyRole::Check,
                        SurveyRole::CheckLength,
                    ] {
                        ui.selectable_value(&mut self.pt_role_input, r, survey_role_label(r));
                    }
                });
        });
        ui.horizontal(|ui| {
            ui.label("X:");
            ui.text_edit_singleline(&mut self.pt_x_input);
            ui.label("Y:");
            ui.text_edit_singleline(&mut self.pt_y_input);
            ui.label("Z:");
            ui.text_edit_singleline(&mut self.pt_z_input);
        });
        ui.horizontal(|ui| {
            ui.label("σ:");
            ui.text_edit_singleline(&mut self.pt_sigma_input);
            ui.label("출처:");
            ui.text_edit_singleline(&mut self.pt_source_input);
        });
        if ui.button("점 추가").clicked() {
            self.on_click_add_point();
        }

        ui.separator();
        let mut clicked_idx: Option<usize> = None;
        for (idx, pt) in self.control_points.iter().enumerate() {
            let selected = self.selected_point_idx == Some(idx);
            let row = format!(
                "{} | {} | ({}, {}, {})",
                pt.point_id,
                survey_role_label(pt.role),
                fmt_coord(pt.x),
                fmt_coord(pt.y),
                fmt_coord(pt.z)
            );
            if ui.selectable_label(selected, row).clicked() {
                clicked_idx = Some(idx);
            }
        }
        if let Some(idx) = clicked_idx {
            self.select_control_point(idx);
        }

        if ui.button("입력 계약 점검 (preflight)").clicked() {
            self.run_user_preflight();
        }
    }

    fn on_click_add_point(&mut self) {
        let id = self.pt_id_input.trim().to_string();
        if id.is_empty() {
            self.push_log("오류: 점 ID를 입력하세요.");
            return;
        }
        let (Ok(x), Ok(y), Ok(z)) = (
            self.pt_x_input.trim().parse::<f64>(),
            self.pt_y_input.trim().parse::<f64>(),
            self.pt_z_input.trim().parse::<f64>(),
        ) else {
            self.push_log("오류: 좌표 X·Y·Z를 숫자로 입력하세요.");
            return;
        };
        let sigma = if self.pt_sigma_input.trim().is_empty() {
            None
        } else if let Ok(s) = self.pt_sigma_input.trim().parse::<f64>() {
            Some(s)
        } else {
            self.push_log("오류: σ는 숫자로 입력하세요.");
            return;
        };
        let role = self.pt_role_input;
        let source = self.pt_source_input.trim().to_string();
        if self
            .add_control_point(&id, role, x, y, z, sigma, &source)
            .is_some()
        {
            self.pt_id_input.clear();
            self.pt_x_input.clear();
            self.pt_y_input.clear();
            self.pt_z_input.clear();
            self.pt_sigma_input.clear();
            self.pt_source_input.clear();
        }
    }

    fn ui_right_measure(&mut self, ui: &mut egui::Ui) {
        let unit_label = self
            .control_frame
            .as_ref()
            .map_or("미설정", |f| f.unit.label());
        ui.label(format!("단위: {unit_label}"));
        ui.horizontal(|ui| {
            ui.label("A:");
            for edit in &mut self.measure_a_inputs {
                ui.text_edit_singleline(edit);
            }
            if ui.button("선택점 → A").clicked() {
                self.fill_measure_from_selected('a');
            }
        });
        ui.horizontal(|ui| {
            ui.label("B:");
            for edit in &mut self.measure_b_inputs {
                ui.text_edit_singleline(edit);
            }
            if ui.button("선택점 → B").clicked() {
                self.fill_measure_from_selected('b');
            }
        });
        ui.horizontal(|ui| {
            ui.label("기준 길이(선택):");
            ui.text_edit_singleline(&mut self.measure_ref_input);
        });
        if ui.button("측정").clicked() {
            self.run_user_measure();
        }
        ui.separator();
        ui.label(&self.measure_result_text);
    }

    fn ui_right_demo(&mut self, ui: &mut egui::Ui) {
        ui.heading("합성 데모 (실측 아님)");
        ui.separator();
        if ui.button("폐합 정합 실행 (fit_rigid_transform)").clicked() {
            self.run_fit();
        }
        if ui.button("견고 정합 실행 (RANSAC)").clicked() {
            self.run_ransac();
        }
        if ui.button("독립 검증 평가 (evaluate_check)").clicked() {
            self.run_validate();
        }
        if ui.button("입력 사전 점검 (preflight)").clicked() {
            self.run_preflight();
        }
        if ui.button("블록 병합 (merge_blocks)").clicked() {
            self.run_merge();
        }
        if ui
            .button("고고학 산출물 · 사이드카 점검 (치수·단면·정사)")
            .clicked()
        {
            self.run_archaeo_outputs();
        }
        if ui.button("기준선 흐름 시연 (run_baseline)").clicked() {
            self.run_baseline_demo();
        }
        if ui.button("사용 원장 초기화 (PointUsageLedger)").clicked() {
            self.reset_ledger();
        }
        ui.separator();
        ui.strong("거부 계약 시연");
        if ui.button("CHECK 점을 구속으로 투입").clicked() {
            self.run_forbidden_constraint();
        }
        if ui.button("정합 tie를 독립 검증으로 재사용").clicked() {
            self.run_forbidden_evaluation();
        }
    }

    fn ui_central_photo_viewer(&mut self, ui: &mut egui::Ui) {
        let active_pt = self
            .selected_point_idx
            .and_then(|i| self.control_points.get(i))
            .map(|p| (p.point_id.clone(), p.role));
        ui.horizontal(|ui| {
            ui.label("사진:");
            let current_text = self
                .loaded_viewer_photo_id
                .clone()
                .unwrap_or_else(|| "(없음)".into());
            egui::ComboBox::from_id_salt("viewer_photo_combo")
                .selected_text(current_text)
                .show_ui(ui, |ui| {
                    let ids: Vec<String> = self.photos.iter().map(|p| p.photo_id.clone()).collect();
                    for id in ids {
                        if ui
                            .selectable_label(
                                self.loaded_viewer_photo_id.as_deref() == Some(id.as_str()),
                                &id,
                            )
                            .clicked()
                        {
                            self.loaded_viewer_photo_id = Some(id);
                        }
                    }
                });
            ui.separator();
            match &active_pt {
                Some((pt_id, role)) => {
                    ui.label(format!(
                        "관측 대상: {pt_id} ({}) — 캔버스를 클릭해 픽셀 좌표를 기록하세요",
                        survey_role_label(*role)
                    ));
                }
                None => {
                    ui.label("관측 대상: (기준점 테이블에서 점을 먼저 선택하세요)");
                }
            }
        });
        ui.separator();

        let loaded_photo = self
            .loaded_viewer_photo_id
            .as_deref()
            .and_then(|id| self.photos.iter().find(|p| p.photo_id == id))
            .cloned();

        let Some(photo) = loaded_photo else {
            ui.label("로드된 사진이 없습니다. 좌측 사진 패널에서 사진을 등록하세요.");
            return;
        };

        let w_px = f64::from(photo.width_px.unwrap_or(640));
        let h_px = f64::from(photo.height_px.unwrap_or(480));
        let avail = ui.available_size();
        let scale = ((avail.x.max(200.0) - 20.0) / w_px as f32)
            .min((avail.y.max(160.0) - 20.0) / h_px as f32)
            .clamp(0.2, 4.0);
        let canvas_size = egui::vec2(w_px as f32 * scale, h_px as f32 * scale);

        let (rect, response) = ui.allocate_exact_size(canvas_size, egui::Sense::click());
        let painter = ui.painter_at(rect);
        painter.rect_filled(rect, 0.0, egui::Color32::from_rgb(0x28, 0x2c, 0x34));
        painter.rect_stroke(
            rect,
            0.0,
            egui::Stroke::new(1.0, egui::Color32::GRAY),
            egui::StrokeKind::Inside,
        );

        if response.clicked()
            && let Some(pos) = response.interact_pointer_pos()
        {
            let x_px = f64::from((pos.x - rect.min.x) / scale);
            let y_px = f64::from((pos.y - rect.min.y) / scale);
            let pt_id_owned = active_pt.as_ref().map(|(id, _)| id.clone());
            let photo_id_owned = photo.photo_id.clone();
            self.record_pixel_observation(
                pt_id_owned.as_deref(),
                Some(photo_id_owned.as_str()),
                x_px,
                y_px,
            );
        }

        let role_by_id: HashMap<&str, SurveyRole> = self
            .control_points
            .iter()
            .map(|p| (p.point_id.as_str(), p.role))
            .collect();

        for obs in self.viewer_markers_for_loaded_photo() {
            let cx = rect.min.x + (obs.x_px as f32) * scale;
            let cy = rect.min.y + (obs.y_px as f32) * scale;
            let color = role_by_id
                .get(obs.point_id.as_str())
                .copied()
                .map_or(egui::Color32::WHITE, survey_role_color);
            let stroke = egui::Stroke::new(1.8, color);
            painter.line_segment([egui::pos2(cx - 7.0, cy), egui::pos2(cx + 7.0, cy)], stroke);
            painter.line_segment([egui::pos2(cx, cy - 7.0), egui::pos2(cx, cy + 7.0)], stroke);
            painter.circle_stroke(egui::pos2(cx, cy), 4.0, stroke);
            painter.text(
                egui::pos2(cx + 8.0, cy - 8.0),
                egui::Align2::LEFT_BOTTOM,
                &obs.point_id,
                egui::FontId::monospace(12.0),
                color,
            );
        }
    }

    fn ui_central_pipeline(&mut self, ui: &mut egui::Ui) {
        ui.strong("파이프라인 단계 (처리 완료 ≠ 측량 검증 통과)");
        for &(key, label) in PIPELINE_STAGES {
            let state = self
                .pipeline_states
                .get(key)
                .map_or("미실시", String::as_str);
            let note = self.pipeline_notes.get(key).map_or("—", String::as_str);
            ui.monospace(format!("{label:<14} | {state:<8} | {note}"));
        }
        ui.separator();

        ui.strong("정합 결과 (합성)");
        match &self.fit {
            Some(fit) => {
                ui.monospace(format!("쿼터니언(x,y,z,w): {:?}", fit.quaternion_xyzw));
                ui.monospace(format!("이동: {:?}", fit.translation));
                ui.monospace(format!("스케일: {:.6}", fit.scale));
            }
            None => {
                ui.label("실행 전");
            }
        }
        if let Some(reg) = &self.registration {
            ui.monospace(format!("RMS: {:.6}", reg.rms));
            ui.monospace(format!("인라이어: {:?}", reg.inlier_ids));
            ui.monospace(format!("기각됨: {:?}", reg.rejected_ids));
        }
        ui.strong("독립 검증 결과 (합성 · 모델 오차)");
        match &self.validation {
            Some(v) => {
                if let Some(s) = v.stats {
                    ui.monospace(format!(
                        "n={} · 평균 {:.6} · 중앙 {:.6} · 최대 {:.6}",
                        s.count, s.mean, s.median, s.max
                    ));
                }
            }
            None => {
                ui.label("실행 전");
            }
        }
        ui.strong("입력 사전 점검");
        if self.issues.is_empty() {
            ui.label("실행 전 또는 문제 없음");
        } else {
            for line in &self.issues {
                ui.colored_label(egui::Color32::YELLOW, line);
            }
        }
        ui.strong("병합 · 고고학 산출물 · 기준선 흐름 (합성)");
        if let Some(s) = &self.merge_summary {
            ui.monospace(s);
        }
        if let Some(s) = &self.archaeo_summary {
            ui.monospace(s);
        }
        if let Some(s) = &self.baseline_summary {
            ui.monospace(s);
        }
        if let Some(msg) = &self.check_as_constraint_refusal {
            ui.colored_label(egui::Color32::RED, msg);
        }
    }

    // ── Synthetic demo actions ──────────────────────────────────────────

    pub fn reset_ledger(&mut self) {
        self.ledger = PointUsageLedger::default();
        self.check_as_constraint_refusal = None;
        self.push_log("사용 원장(PointUsageLedger) 초기화 완료");
    }

    pub fn run_fit(&mut self) {
        let src: Vec<Point3D> = self.demo.ties.iter().map(|t| t.src_point).collect();
        let dst: Vec<Point3D> = self.demo.ties.iter().map(|t| t.dst_point).collect();
        match fit_rigid_transform(&src, &dst, false) {
            Ok(fit) => {
                self.push_log("폐합 정합 실행 — 합성 tie 6개 (T0·T1 오염 포함)");
                self.push_log(format!("스케일 {:.6}", fit.scale));
                self.fit = Some(fit);
            }
            Err(e) => self.push_log(format!("폐합 정합 실패: {e}")),
        }
    }

    pub fn run_ransac(&mut self) {
        match register_blocks_ransac(&self.demo.ties, 0.1, &mut self.ledger, false, 300, 0) {
            Ok(reg) => {
                self.push_log(format!(
                    "RANSAC 실행 — 기각 {}: 인라이어 {} (원장에 정합 사용 기록됨)",
                    reg.rejected_ids.join(","),
                    reg.inlier_ids.len()
                ));
                self.registration = Some(reg);
            }
            Err(e) => self.push_log(format!("RANSAC 실패: {e}")),
        }
    }

    pub fn run_validate(&mut self) {
        let model = self.demo.clean_model.clone();
        match evaluate_check(&model, &self.demo.clean_checks, &mut self.ledger) {
            Ok(v) => {
                self.push_log(
                    "독립 검증 평가 실행 — 합성 CHK-A·CHK-B, 모델 오차이며 실측 오차가 아님",
                );
                self.validation = Some(v);
            }
            Err(e) => self.push_log(format!("독립 검증 실패: {e}")),
        }
    }

    pub fn run_preflight(&mut self) {
        let issues = preflight_control(&self.demo.clean_checks, None);
        self.issues = issues
            .iter()
            .map(|i| format!("[{} {}] {}", i.severity.label(), i.code, i.message))
            .collect();
        match issues.len() {
            0 => self.push_log("입력 사전 점검 실행 — 문제 없음"),
            _ => self.push_log(format!("입력 사전 점검 실행 — {}건", issues.len())),
        }
    }

    pub fn run_merge(&mut self) {
        let block = |id: u32, base: [f64; 3], origin: Vec<OriginKind>| {
            Block::new(
                format!("b{id}"),
                self.demo.frame.clone(),
                vec![
                    [base[0], base[1], base[2]],
                    [base[0] + 1.0, base[1], base[2]],
                    [base[0], base[1] + 1.0, base[2]],
                ],
                vec![[0, 1, 2]],
                origin,
            )
            .unwrap()
        };
        let b1 = block(1, [0.0; 3], vec![OriginKind::Observed; 3]);
        let b2 = block(2, [2.0, 2.0, 2.0], vec![OriginKind::Interpolated; 3]);
        match merge_blocks(&[b1, b2], self.demo.frame.clone(), ProductKind::Survey) {
            Ok(merged) => {
                let (observed, interpolated) = merged.count_by_origin();
                let sidecar = mesh_sidecar(&merged);
                let ply = write_ply_string(&merged);
                self.merge_summary = Some(format!(
                    "정점 {} · 관측 {observed} · 보간 {interpolated} · 관측비율 {:.2} · sidecar CRS={} · PLY {}B",
                    merged.vertices.len(),
                    merged.observed_fraction(),
                    sidecar.crs_id,
                    ply.len()
                ));
                self.push_log("블록 병합 실행 — 관측/보간 구분 및 sidecar/PLY 메타데이터 유지됨");
            }
            Err(e) => self.push_log(format!("블록 병합 실패: {e}")),
        }
    }

    pub fn run_archaeo_outputs(&mut self) {
        let frame = &self.demo.frame;
        let m = measure_distance([0.0, 0.0, 0.0], [3.0, 4.0, 0.0], frame).unwrap();
        let res = length_residual(&m, 5.0).unwrap();

        let plane = Plane::new([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], frame.clone()).unwrap();
        let verts = vec![[0.0, 0.0, -1.0], [2.0, 0.0, 1.0], [0.0, 2.0, 1.0]];
        let faces = vec![[0, 1, 2]];
        let origins = vec![
            OriginKind::Observed,
            OriginKind::Observed,
            OriginKind::Interpolated,
        ];
        let sec = compute_section(&verts, &faces, &plane, Some(&origins), 1e-9).unwrap();

        let spec = OrthoSpec::new(
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            frame.clone(),
        )
        .unwrap();
        let grid = OrthoGrid::new([0.0, 0.0], 1.0, 10, 10, frame.clone()).unwrap();
        let ortho = OrthoProduct::new(
            vec![spec.project([1.0, 2.0, 9.0]), spec.project([3.0, 4.0, 9.0])],
            vec![OriginKind::Observed, OriginKind::Interpolated],
            ProductKind::Survey,
            spec,
            grid,
        )
        .unwrap();
        let orep = ortho.honesty_report();

        self.archaeo_summary = Some(format!(
            "치수: {:.3} {} (좌표 산출값 — 직접 실측이 아님, 기준 대차 {:+.3}) · 단면 세그먼트 {}개({:?}) · 정사 관측 {}/{}",
            m.value,
            m.unit.label(),
            res,
            sec.segments.len(),
            sec.segment_origin,
            orep.observed_points,
            orep.point_count
        ));
        self.push_log("고고학 산출물 점검 — 치수(좌표 산출값)·단면(보간 전파)·정사 투영 확인");
    }

    pub fn run_baseline_demo(&mut self) {
        let f = self.demo.frame.clone();
        let pts = vec![
            ControlPoint::new("GCP-01", SurveyRole::Gcp, 0.0, 0.0, 0.0, f.clone()).unwrap(),
            ControlPoint::new("CHK-01", SurveyRole::Check, 10.0, 10.0, 10.0, f.clone()).unwrap(),
        ];
        let inputs = BaselineInputs::new(
            pts,
            f,
            vec!["GCP-01".into()],
            vec!["CHK-01".into()],
            vec![],
            HashMap::new(),
        )
        .unwrap();
        if let Ok(res) = run_baseline(Some(&SyntheticOffsetEngine), &inputs) {
            self.baseline_summary = Some(format!(
                "기준선(합성): 구속={:?} · CHK-01 거리 오차={:.4} · 처리={} · 검증={}",
                res.constraint.applied,
                res.validation.distances["CHK-01"],
                res.run.process_state.ko_label(),
                res.run.validation_state.ko_label()
            ));
            self.push_log(
                "기준선 흐름 시연 완료 — 처리 완료(Succeeded)와 검증 상태(NotRun) 분리 유지",
            );
        }
    }

    pub fn run_forbidden_constraint(&mut self) {
        let check = ControlPoint::new(
            "CHK-A",
            SurveyRole::Check,
            0.0,
            0.0,
            0.0,
            self.demo.frame.clone(),
        )
        .unwrap();
        match apply_gcp_constraint(&[check], &mut self.ledger, None) {
            Err(refusal) => {
                self.check_as_constraint_refusal = Some(refusal.clone());
                self.push_log(format!("거부됨(계약): {refusal}"));
            }
            Ok(_) => self.push_log("오류: CHECK 점이 구속으로 받아들여짐 — 계약 이상"),
        }
    }

    pub fn run_forbidden_evaluation(&mut self) {
        self.ledger.mark_alignment("T2");
        let check = ControlPoint::new(
            "T2",
            SurveyRole::Check,
            0.0,
            0.0,
            0.0,
            self.demo.frame.clone(),
        )
        .unwrap();
        let mut model = HashMap::new();
        model.insert("T2".to_string(), [0.0f64, 0.0, 0.0]);
        match evaluate_check(&model, &[check], &mut self.ledger) {
            Err(refusal) => {
                self.check_as_constraint_refusal = Some(refusal.clone());
                self.push_log(format!("거부됨(계약): {refusal}"));
            }
            Ok(_) => self.push_log("오류: 정합 tie가 독립 평가로 받아들여짐 — 계약 이상"),
        }
    }
}

pub fn make_minimal_png_header(path: &Path, width: u32, height: u32) {
    let mut bytes = Vec::with_capacity(32);
    bytes.extend_from_slice(&[137, 80, 78, 71, 13, 10, 26, 10]);
    bytes.extend_from_slice(&13u32.to_be_bytes());
    bytes.extend_from_slice(b"IHDR");
    bytes.extend_from_slice(&width.to_be_bytes());
    bytes.extend_from_slice(&height.to_be_bytes());
    bytes.extend_from_slice(&[8, 2, 0, 0, 0]);
    std::fs::write(path, bytes).unwrap();
}

fn main() -> eframe::Result {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default().with_inner_size([1280.0, 800.0]),
        ..Default::default()
    };
    eframe::run_native(
        "archphoto — 고고학 사진실측",
        options,
        Box::new(|_cc| Ok(Box::new(App::new()))),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn app_persists_ledger_across_ransac_and_refuses_tie_reuse() {
        let mut app = App::new();
        app.run_ransac();
        assert!(app.ledger.alignment().contains("T2"));

        let check = ControlPoint::new(
            "T2",
            SurveyRole::Check,
            0.0,
            0.0,
            0.0,
            app.demo.frame.clone(),
        )
        .unwrap();
        let mut model = HashMap::new();
        model.insert("T2".to_string(), [0.0, 0.0, 0.0]);
        assert!(evaluate_check(&model, &[check], &mut app.ledger).is_err());

        app.reset_ledger();
        assert!(app.ledger.alignment().is_empty());
    }

    #[test]
    fn app_runs_merge_archaeo_and_baseline_honestly() {
        let mut app = App::new();
        app.run_merge();
        assert!(
            app.merge_summary
                .as_ref()
                .unwrap()
                .contains("sidecar CRS=LOCAL:demo")
        );

        app.run_archaeo_outputs();
        let summary = app.archaeo_summary.as_ref().unwrap();
        assert!(summary.contains("좌표 산출값 — 직접 실측이 아님"));
        assert!(summary.contains("Interpolated"));

        app.run_baseline_demo();
        let base = app.baseline_summary.as_ref().unwrap();
        assert!(base.contains("처리=완료") && base.contains("검증=미실시"));
    }

    #[test]
    fn interactive_control_flow_and_readout_match_reference_gui() {
        let mut app = App::new();
        // Control point requires frame first
        assert!(
            app.add_control_point("GCP-01", SurveyRole::Gcp, 0.0, 0.0, 0.0, None, "")
                .is_none()
        );
        assert!(app.log_text().contains("좌표계"));

        assert!(app.set_control_frame(
            "LOCAL:site",
            LengthUnit::Meter,
            AxisOrder::EastNorth,
            VerticalDatum::Orthometric,
            None,
        ));
        let gcp = app
            .add_control_point(
                "GCP-01",
                SurveyRole::Gcp,
                1.5,
                2.5,
                3.5,
                Some(0.005),
                "total-station",
            )
            .unwrap();
        assert!(gcp.role.used_in_calibration());
        assert!(app.readout_text.contains("해발") && app.readout_text.contains("3.500"));

        // Without a check point, preflight warns
        let issues_warn = app.run_user_preflight();
        assert!(issues_warn.iter().any(|i| i.code == "no_check_point"));

        // Adding a check point clears the warning, and never marks validation as done
        app.add_control_point("CHK-01", SurveyRole::Check, 3.0, 4.0, 0.0, None, "");
        let issues_clean = app.run_user_preflight();
        assert!(issues_clean.is_empty());
        assert_eq!(app.pipeline_states["validate"], "미실시");

        // Unknown vertical datum never claims "해발"
        app.set_control_frame(
            "LOCAL:b",
            LengthUnit::Meter,
            AxisOrder::EastNorth,
            VerticalDatum::Unknown,
            None,
        );
        app.add_control_point("GCP-02", SurveyRole::Gcp, 1.0, 2.0, 3.0, None, "");
        assert!(!app.readout_text.contains("해발"));
        assert!(app.readout_text.contains("기준 미상"));
    }

    #[test]
    fn interactive_measure_and_photo_pixel_observations_work_end_to_end() {
        let mut app = App::new();
        app.set_measure_point('a', 0.0, 0.0, 0.0);
        app.set_measure_point('b', 3.0, 4.0, 0.0);
        assert!(app.run_user_measure().is_none());

        app.set_control_frame(
            "EPSG:5186",
            LengthUnit::Meter,
            AxisOrder::EastNorth,
            VerticalDatum::Orthometric,
            None,
        );
        app.measure_ref_input = "5.0".into();
        let m = app.run_user_measure().unwrap();
        assert!((m.value - 5.0).abs() < 1e-12);
        assert!(app.measure_result_text.contains("직접 실측이 아님"));
        assert!(app.measure_result_text.contains("+0.000"));

        // 6-7 digit TM coordinate fill preserves millimeter decimals
        app.add_control_point(
            "GCP-TM",
            SurveyRole::Gcp,
            123456.789,
            4123456.125,
            30.0,
            None,
            "",
        );
        assert!(app.fill_measure_from_selected('b'));
        assert_eq!(
            app.parse_measure_point('b'),
            Some([123456.789, 4123456.125, 30.0])
        );

        // Photo import + pixel observation + per-photo marker filter + integrity check
        let dir = std::env::temp_dir();
        let pid = std::process::id();
        let p1 = dir.join(format!("IMG_GUI_1_{pid}.png"));
        let p2 = dir.join(format!("IMG_GUI_2_{pid}.png"));
        make_minimal_png_header(&p1, 64, 48);
        make_minimal_png_header(&p2, 80, 60);

        let imported = app.import_photo_paths(&[p1.clone(), p2.clone()]);
        assert_eq!(imported.len(), 2);
        assert_eq!(imported[0].width_px, Some(64));
        assert_eq!(imported[0].height_px, Some(48));
        assert!(app.verify_manifest_integrity().is_empty());

        let id1 = imported[0].photo_id.clone();
        let id2 = imported[1].photo_id.clone();
        app.load_photo_in_viewer(&id1);
        assert!(app.record_pixel_observation(Some("GCP-TM"), Some(&id1), 30.0, 24.0));
        // Replace observation on same photo
        assert!(app.record_pixel_observation(Some("GCP-TM"), Some(&id1), 40.0, 30.0));
        assert_eq!(app.observations.len(), 1);
        assert!((app.observations[0].x_px - 40.0).abs() < 1e-9);
        // Out of bounds pixel is refused
        assert!(!app.record_pixel_observation(Some("GCP-TM"), Some(&id1), 999.0, 30.0));

        // Second photo observation and marker filtering by loaded photo
        app.load_photo_in_viewer(&id2);
        assert!(app.record_pixel_observation(Some("GCP-TM"), Some(&id2), 20.0, 20.0));
        assert_eq!(app.observations.len(), 2);
        assert_eq!(app.viewer_markers_for_loaded_photo().len(), 1);

        let _ = std::fs::remove_file(&p1);
        let _ = std::fs::remove_file(&p2);
    }
}
