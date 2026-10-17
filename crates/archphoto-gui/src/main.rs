//! archphoto GUI shell (egui 0.37) — ported from the PySide6 layout logic
//! (D-2026-10-12-09 → D-2026-10-12-11). This slice proves the toolchain and
//! the dock-like structure; panels, icons and contracts land in later slices.

use eframe::egui;

struct App;

impl eframe::App for App {
    fn ui(&mut self, root: &mut egui::Ui, _frame: &mut eframe::Frame) {
        egui::Panel::top("toolbar").show(root, |ui| {
            ui.horizontal_wrapped(|ui| {
                ui.strong("archphoto — 고고학 사진실측");
                ui.separator();
                ui.label(
                    "사진 · 카메라 · 기준점 · 측정 · 정합 · 단면 · 메시 · 검증 · 내보내기 (구현 예정)",
                );
            });
        });

        egui::Panel::left("photos").show(root, |ui| {
            ui.heading("사진");
            ui.label("등록된 사진 없음");
            ui.small("원본은 항상 읽기 전용 — 이식 예정");
        });

        egui::Panel::right("control").show(root, |ui| {
            ui.heading("기준점");
            ui.label("좌표계 프레임을 먼저 적용해야 점을 추가할 수 있습니다.");
            ui.label("GCP와 독립 검증점은 분리됩니다.");
            ui.small("이식 예정");
        });

        egui::Panel::bottom("statusbar").show(root, |ui| {
            ui.label("좌표: —  ·  해발: — ");
        });

        egui::CentralPanel::default().show(root, |ui| {
            ui.heading("3D 메시 뷰포트");
            ui.label("구현 예정 — 사진 뷰어·픽셀 관측도 이 곳에 탭으로 들어갑니다.");
        });
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
        Box::new(|_cc| Ok(Box::new(App))),
    )
}
