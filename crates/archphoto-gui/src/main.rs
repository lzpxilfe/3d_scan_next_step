//! archphoto GUI shell (egui 0.37) with core contracts wired in
//! (D-2026-10-12-09 layout → D-2026-10-12-11 Rust switch).
//!
//! COVERAGE — honest, slice-scoped:
//!   * every button runs the REAL ported core (archphoto-core):
//!     fit_rigid_transform / register_blocks_ransac / evaluate_check /
//!     preflight_control / apply_transform + merge_blocks;
//!   * ALL numbers come from the built-in SYNTHETIC dataset and are labelled
//!     as such ("합성") — nothing here pretends to be survey results;
//!   * refusal contracts (CHECK point fed as constraint, tie reused as check)
//!     can be exercised live so the honesty rules are visible, not just told;
//!   * photo ingestion, pixel observation editing and the 3D viewport are NOT
//!     implemented yet and say so.

use std::collections::HashMap;

use eframe::egui;

use archphoto_core::Point3D;
use archphoto_core::crs::{LengthUnit, SpatialFrame, VerticalDatum};
use archphoto_core::mesh::{OriginKind, ProductKind};
use archphoto_core::preflight::preflight_control;
use archphoto_core::quality::{
    CheckValidation, ModelMap, PointUsageLedger, apply_gcp_constraint, evaluate_check,
};
use archphoto_core::register::{
    Block, RegistrationResult, SimilarityFit, TiePoint, apply_similarity, fit_rigid_transform,
    merge_blocks, register_blocks_ransac,
};
use archphoto_core::sensing::{ControlPoint, SurveyRole};

const HALF_SQRT2: f64 = std::f64::consts::FRAC_1_SQRT_2;

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

        // Two independent CHECK points with small model residuals.
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

struct App {
    demo: Demo,
    log: Vec<String>,
    fit: Option<SimilarityFit>,
    registration: Option<RegistrationResult>,
    validation: Option<CheckValidation>,
    issues: Vec<String>,
    merge_summary: Option<String>,
    check_as_constraint_refusal: Option<String>,
}

impl App {
    fn new() -> Self {
        App {
            demo: Demo::new(),
            log: vec!["합성 데모 — 이 화면의 모든 값은 실측이 아닙니다.".to_string()],
            fit: None,
            registration: None,
            validation: None,
            issues: Vec::new(),
            merge_summary: None,
            check_as_constraint_refusal: None,
        }
    }

    fn push_log(&mut self, line: impl Into<String>) {
        self.log.push(line.into());
    }
}

impl eframe::App for App {
    fn ui(&mut self, root: &mut egui::Ui, _frame: &mut eframe::Frame) {
        egui::Panel::top("toolbar").show(root, |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.strong("archphoto — 고고학 사진실측 (Rust 이식 단계)");
                ui.separator();
                ui.label(format!("{}", self.demo.frame));
            });
        });

        egui::Panel::left("photos").show(root, |ui| {
            ui.heading("사진");
            ui.label("등록된 사진 없음");
            ui.small("원본은 항상 읽기 전용 — 사진 입력 이식 예정");
        });

        egui::Panel::right("actions").show(root, |ui| {
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
            ui.separator();
            ui.strong("거부 계약 시연");
            if ui.button("CHECK 점을 구속으로 투입").clicked() {
                self.run_forbidden_constraint();
            }
            if ui.button("정합 tie를 독립 검증으로 재사용").clicked() {
                self.run_forbidden_evaluation();
            }
        });

        egui::Panel::bottom("logfile").show(root, |ui| {
            ui.heading("로그");
            egui::ScrollArea::vertical()
                .max_height(140.0)
                .show(ui, |ui| {
                    for line in &self.log {
                        ui.monospace(line);
                    }
                });
        });

        egui::CentralPanel::default().show(root, |ui| {
            ui.heading("파이프라인");
            ui.label("3D 뷰포트 · 사진 뷰어 · 픽셀 관측 — 이 탭은 아직 구현 예정입니다.");
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
                for (id, d) in &reg.residuals {
                    ui.monospace(format!("  {id}: {d:.6}"));
                }
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
                    for (id, d) in &v.distances {
                        ui.monospace(format!("  {id}: {d:.6}"));
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
            ui.strong("병합 (정직성 축 보존)");
            match &self.merge_summary {
                Some(s) => {
                    ui.monospace(s);
                }
                None => {
                    ui.label("실행 전");
                }
            }
            if let Some(msg) = &self.check_as_constraint_refusal {
                ui.colored_label(egui::Color32::RED, msg);
            }
        });
    }
}

impl App {
    fn run_fit(&mut self) {
        let src: Vec<Point3D> = self.demo.ties.iter().map(|t| t.src_point).collect();
        let dst: Vec<Point3D> = self.demo.ties.iter().map(|t| t.dst_point).collect();
        match fit_rigid_transform(&src, &dst, false) {
            Ok(fit) => {
                self.push_log("폐합 정합 실행 — 합성 tie 6개 (T0·T1 오염 포함) ");
                self.push_log(format!("스케일 {:.6}", fit.scale));
                self.fit = Some(fit);
            }
            Err(e) => self.push_log(format!("폐합 정합 실패: {e}")),
        }
    }

    fn run_ransac(&mut self) {
        let mut ledger = PointUsageLedger::default();
        match register_blocks_ransac(&self.demo.ties, 0.1, &mut ledger, false, 300, 0) {
            Ok(reg) => {
                self.push_log(format!(
                    "RANSAC 실행 — 기각 {}: 인라이어 {}",
                    reg.rejected_ids.join(","),
                    reg.inlier_ids.len()
                ));
                self.registration = Some(reg);
            }
            Err(e) => self.push_log(format!("RANSAC 실패: {e}")),
        }
    }

    fn run_validate(&mut self) {
        let mut ledger = PointUsageLedger::default();
        let model = self.demo.clean_model.clone();
        match evaluate_check(&model, &self.demo.clean_checks, &mut ledger) {
            Ok(v) => {
                self.push_log(
                    "독립 검증 평가 실행 — 합성 CHK-A·CHK-B, 모델 오차이며 실측 오차가 아님",
                );
                self.validation = Some(v);
            }
            Err(e) => self.push_log(format!("독립 검증 실패: {e}")),
        }
    }

    fn run_preflight(&mut self) {
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

    fn run_merge(&mut self) {
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
                self.merge_summary = Some(format!(
                    "정점 {} · 관측 {observed} · 보간 {interpolated} · 관측비율 {:.2}",
                    merged.vertices.len(),
                    merged.observed_fraction()
                ));
                self.push_log("블록 병합 실행 — 관측/보간 구분 유지됨");
            }
            Err(e) => self.push_log(format!("블록 병합 실패: {e}")),
        }
    }

    fn run_forbidden_constraint(&mut self) {
        // CHECK point pointed at the constraint API — must be refused.
        let check = ControlPoint::new(
            "CHK-A",
            SurveyRole::Check,
            0.0,
            0.0,
            0.0,
            self.demo.frame.clone(),
        )
        .unwrap();
        let mut ledger = PointUsageLedger::default();
        match apply_gcp_constraint(&[check], &mut ledger, None) {
            Err(refusal) => {
                self.check_as_constraint_refusal = Some(refusal.clone());
                self.push_log(format!("거부됨(계약): {refusal}"));
            }
            Ok(_) => self.push_log("오류: CHECK 점이 구속으로 받아들여짐 — 계약 이상"),
        }
    }

    fn run_forbidden_evaluation(&mut self) {
        // Simulate the real sequence: ties were consumed as ALIGNMENT use, then
        // someone relabels T0 as CHECK and feeds it to evaluate_check — refused.
        let mut ledger = PointUsageLedger::default();
        for t in &self.demo.ties {
            ledger.mark_alignment(&t.tie_id);
        }
        let check = ControlPoint::new(
            "T0",
            SurveyRole::Check,
            0.0,
            0.0,
            0.0,
            self.demo.frame.clone(),
        )
        .unwrap();
        let mut model = HashMap::new();
        model.insert("T0".to_string(), [0.0f64, 0.0, 0.0]);
        match evaluate_check(&model, &[check], &mut ledger) {
            Err(refusal) => {
                self.check_as_constraint_refusal = Some(refusal.clone());
                self.push_log(format!("거부됨(계약): {refusal}"));
            }
            Ok(_) => self.push_log("오류: 정합 tie가 독립 평가로 받아들여짐 — 계약 이상"),
        }
    }
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
