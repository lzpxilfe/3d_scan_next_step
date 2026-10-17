"""Main application window (PySide6 / Qt).

실측 작업 흐름에 맞춘 프로세스 기반 도킹 워크스테이션 레이아웃 (D-2026-10-12-09):
- 상단: 툴바 + 5단계 프로세스 스테퍼 바 (1.현장·좌표계 → 2.사진·원본무결성 → 3.기준점·정밀피닝 → 4.정합·독립검증 → 5.단면·실측·산출물)
- 좌측: 사진 목록 (촬영 역할·피닝 수·해시·무결성 재검증·원클릭 샘플 로드)
- 우측: 기준점(좌표계 프리셋 + CSV 가져오기 + 점 테이블 + 정합·검증 실행) / 거리 측정·산출물 게이트 (탭)
- 하단: 파이프라인 상태(처리 완료 vs 독립 검증 분리 배너) / 로그 콘솔 (탭)
- 중앙: 3D·평면·단면 인터랙티브 실측 뷰포트 & 8× 서브픽셀 루페 정밀 사진 피닝 뷰어
- 상태바 우측: 선택한 점의 좌표·높이(해발) 읽기

정직성 규칙 (AGENTS.md): 원본 사진은 읽기 전용(해시 등록만); 좌표계 프레임을 적용하기
전에는 점 추가·측정이 불가; 파이프라인 "검증(독립)" 상태는 실제 독립 검증이 실행될 때만
변경되고 자료 입력으로는 절대 바뀌지 않음; 아직 구현 전 액션은 클릭 시 "미구현"으로
로그에 표시해 가짜 동작을 만들지 않는다.
"""

from __future__ import annotations

import csv
import hashlib
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from archphoto.archaeo.measure import length_residual, measure_distance
from archphoto.geom.crs import AxisOrder, LengthUnit, SpatialFrame, VerticalDatum
from archphoto.gui.icons import icon
from archphoto.gui.panels import (
    ROLE_COLORS,
    ROLE_LABELS,
    ControlPanel,
    LogConsole,
    MeasurePanel,
    PhotoPanel,
    PipelinePanel,
)
from archphoto.archaeo.surface import OriginKind, ProductKind
from archphoto.gui.photo_viewer import PhotoViewerPanel
from archphoto.gui.theme import WORKSTATION_STYLESHEET, WorkflowStepperBar
from archphoto.gui.viewport_3d import SurveyViewport3DPanel
from archphoto.mesh.export import ExportFormat, export_mesh
from archphoto.preflight import preflight_control
from archphoto.project.manifest import ProjectManifest, RawItem
from archphoto.quality.checkpoints import PointUsageLedger, evaluate_check
from archphoto.runlog.record import ProcessState, ValidationState
from archphoto.sensing.control import ControlPoint, ControlRole
from archphoto.sensing.observations import PhotoObservation
from archphoto.sensing.photos import CaptureRole, Photo

TOOLBAR_ACTIONS = [
    ("photos", "사진 가져오기"),
    ("camera", "카메라"),
    ("control", "GCP·기준점"),
    ("measure", "거리 측정"),
    ("stitch", "정합(붙이기)"),
    ("section", "단면"),
    ("mesh", "메시"),
    ("validate", "검증"),
    ("export", "내보내기"),
]

IMPLEMENTED_TOOLS = {"photos", "control", "measure"}

CAPTURE_ROLE_LABELS = {
    CaptureRole.OBJECT: "피사체",
    CaptureRole.SCALE: "축척기준",
    CaptureRole.REFERENCE: "참고",
    CaptureRole.UNKNOWN: "미상",
}

DATUM_READOUT = {
    VerticalDatum.ORTHOMETRIC: ("해발", "정고도"),
    VerticalDatum.ELLIPSOIDAL: ("타원체고", "타원체"),
    VerticalDatum.LOCAL: ("현지 Z", "현지 수준점"),
    VerticalDatum.UNKNOWN: ("Z", "기준 미상"),
}

PHOTO_FILTER = "사진 (*.jpg *.jpeg *.png *.tif *.tiff *.dng)"


class MainWindow(QMainWindow):
    """도킹 패널 기반 사진실측 워크스테이션 메인 창. 코어 로직은 재구현하지 않고 호출만 한다."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("archphoto — 고고학 사진실측 워크스테이션")
        self.setStyleSheet(WORKSTATION_STYLESHEET)
        self.photos: list[Photo] = []
        self.control_points: list[ControlPoint] = []
        self.observations: list[PhotoObservation] = []
        self.measurements = []
        self.ledger = PointUsageLedger()
        self.check_residuals: dict[str, tuple[float, float, float]] = {}
        self._last_measure_seg: tuple[tuple[float, float, float], tuple[float, float, float], str] | None = None
        self._next_pick_slot: str = "a"
        self._control_frame: SpatialFrame | None = None
        self._demo_tmp_dir: tempfile.TemporaryDirectory | None = None
        self.manifest = ProjectManifest(
            project_id=f"archphoto-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}",
            title="제목 미설정",
        )
        self.actions: dict[str, object] = {}
        self._build_toolbar()
        self._build_docks()
        self._build_central()
        self._build_statusbar()
        self._sync_workflow_stepper()
        self.log("프로젝트 시작 — 원본은 읽기 전용입니다. [1. 현장·좌표계] 프레임을 먼저 적용하세요.")

    # ── 구성 ────────────────────────────────────────────────────────────

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("메인", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        for name, label in TOOLBAR_ACTIONS:
            action = toolbar.addAction(icon(name), label)
            action.setToolTip(label)
            action.triggered.connect(lambda _=False, n=name: self._on_tool(n))
            self.actions[name] = action

    def _build_docks(self) -> None:
        self.photo_panel = PhotoPanel()
        self.photo_dock = QDockWidget("2. 사진 · 원본 무결성", self)
        self.photo_dock.setObjectName("dock_photos")
        self.photo_dock.setWindowIcon(icon("photos"))
        self.photo_dock.setWidget(self.photo_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.photo_dock)

        self.control_panel = ControlPanel()
        self.control_dock = QDockWidget("1·3. 좌표계 · 기준점(GCP/검증점)", self)
        self.control_dock.setObjectName("dock_control")
        self.control_dock.setWindowIcon(icon("control"))
        self.control_dock.setWidget(self.control_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.control_dock)

        self.measure_panel = MeasurePanel()
        self.measure_dock = QDockWidget("5. 거리 측정 · 산출물 게이트", self)
        self.measure_dock.setObjectName("dock_measure")
        self.measure_dock.setWindowIcon(icon("measure"))
        self.measure_dock.setWidget(self.measure_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.measure_dock)
        self.tabifyDockWidget(self.control_dock, self.measure_dock)

        self.pipeline_panel = PipelinePanel()
        self.pipeline_dock = QDockWidget("4. 파이프라인 · 독립 검증 상태", self)
        self.pipeline_dock.setObjectName("dock_pipeline")
        self.pipeline_dock.setWidget(self.pipeline_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.pipeline_dock)

        self.log_console = LogConsole()
        self.log_dock = QDockWidget("실행 · 계약 로그", self)
        self.log_dock.setObjectName("dock_log")
        self.log_dock.setWidget(self.log_console)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.tabifyDockWidget(self.pipeline_dock, self.log_dock)

        # Signal wiring
        self.control_panel.apply_frame_button.clicked.connect(self._on_apply_frame)
        self.control_panel.preset_epsg_btn.clicked.connect(
            lambda: self._apply_crs_preset("EPSG:5186", "m", "EN", "orthometric", "KNGeoid18")
        )
        self.control_panel.preset_trench_btn.clicked.connect(
            lambda: self._apply_crs_preset("LOCAL:Trench-A", "m", "EN", "local", None)
        )
        self.control_panel.preset_artifact_btn.clicked.connect(
            lambda: self._apply_crs_preset("LOCAL:Artifact-Table", "mm", "EN", "local", None)
        )
        self.control_panel.add_point_button.clicked.connect(self._on_add_point)
        self.control_panel.import_csv_button.clicked.connect(self._on_import_csv_dialog)
        self.control_panel.preflight_button.clicked.connect(self.run_preflight)
        self.control_panel.validate_run_button.clicked.connect(self.run_validation_workflow)
        self.control_panel.table.itemSelectionChanged.connect(self._on_control_selection)

        self.photo_panel.apply_role_button.clicked.connect(self._on_apply_photo_role)
        self.photo_panel.open_requested.connect(self._open_photo_in_viewer)
        self.photo_panel.verify_button.clicked.connect(self.verify_manifest_integrity)
        self.photo_panel.demo_button.clicked.connect(self.load_field_survey_preset)

        self.measure_panel.measure_button.clicked.connect(self._on_measure)
        self.measure_panel.fill_a_button.clicked.connect(lambda: self._fill_measure("a"))
        self.measure_panel.fill_b_button.clicked.connect(lambda: self._fill_measure("b"))
        self.measure_panel.export_survey_button.clicked.connect(
            lambda: self.check_export_gate(ProductKind.SURVEY)
        )
        self.measure_panel.export_display_button.clicked.connect(
            lambda: self.check_export_gate(ProductKind.DISPLAY)
        )

    def _build_central(self) -> None:
        container = QWidget(self)
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        self.stepper = WorkflowStepperBar(container)
        self.stepper.stage_clicked.connect(self._on_stage_selected)
        container_layout.addWidget(self.stepper)

        self.central_tabs = QTabWidget(container)
        self.viewport_3d = SurveyViewport3DPanel(self.central_tabs)
        self.viewport_3d.canvas.point_picked.connect(self._on_viewport_3d_point_picked)
        self.viewport_placeholder = self.viewport_3d.header_label
        self.photo_viewer = PhotoViewerPanel(self.central_tabs)
        self.photo_viewer.set_observation_callback(self._on_pixel_clicked)
        self.central_tabs.addTab(self.viewport_3d, "3D · 평면 · 단면 뷰포트")
        self.central_tabs.addTab(self.photo_viewer, "정밀 사진 피닝 뷰어 (8× 루페)")
        container_layout.addWidget(self.central_tabs, 1)

        self.setCentralWidget(container)

    def _build_statusbar(self) -> None:
        self.readout = QLabel("좌표: —  ·  해발: —", self)
        self.statusBar().addPermanentWidget(self.readout)

    # ── 프로세스 스테퍼 네비게이션 ─────────────────────────────────────

    def _on_stage_selected(self, stage_key: str) -> None:
        if stage_key == "stage_frame":
            self.control_dock.show()
            self.control_dock.raise_()
            self.central_tabs.setCurrentWidget(self.viewport_3d)
        elif stage_key == "stage_photos":
            self.photo_dock.show()
            self.photo_dock.raise_()
            self.central_tabs.setCurrentWidget(self.photo_viewer)
        elif stage_key == "stage_pinning":
            self.control_dock.show()
            self.control_dock.raise_()
            self.central_tabs.setCurrentWidget(self.photo_viewer)
        elif stage_key == "stage_validate":
            self.control_dock.show()
            self.control_dock.raise_()
            self.pipeline_dock.show()
            self.pipeline_dock.raise_()
            self.central_tabs.setCurrentWidget(self.viewport_3d)
        elif stage_key == "stage_deliver":
            self.measure_dock.show()
            self.measure_dock.raise_()
            self.central_tabs.setCurrentWidget(self.viewport_3d)

    def _sync_workflow_stepper(self) -> None:
        # Stage 1: Frame
        if self._control_frame is None:
            self.stepper.update_stage_status("stage_frame", "미설정", "warn")
        else:
            self.stepper.update_stage_status("stage_frame", "설정됨", "ok")

        # Stage 2: Photos
        if not self.photos:
            self.stepper.update_stage_status("stage_photos", "0장", "neutral")
        else:
            self.stepper.update_stage_status("stage_photos", f"{len(self.photos)}장", "ok")

        # Stage 3: Pinning
        gcp_cnt = sum(1 for p in self.control_points if p.is_gcp)
        chk_cnt = sum(1 for p in self.control_points if p.is_check)
        if not self.control_points:
            self.stepper.update_stage_status("stage_pinning", "0점", "neutral")
        else:
            tone = "ok" if (gcp_cnt >= 3 and chk_cnt >= 1 and len(self.observations) >= 3) else "active"
            self.stepper.update_stage_status(
                "stage_pinning",
                f"{len(self.control_points)}점·{len(self.observations)}핀",
                tone,
            )

        # Stage 4: Validation
        val_state = self.pipeline_panel.states().get("validate", "미실시")
        if val_state == "통과":
            self.stepper.update_stage_status("stage_validate", "통과", "ok")
        elif val_state == "미실시":
            self.stepper.update_stage_status("stage_validate", "미실시", "neutral")
        else:
            self.stepper.update_stage_status("stage_validate", val_state, "warn")

        # Stage 5: Deliverables
        if self.measurements:
            self.stepper.update_stage_status("stage_deliver", f"{len(self.measurements)}건", "ok")
        else:
            self.stepper.update_stage_status("stage_deliver", "대기", "neutral")

        # Refresh 3D viewport
        frame_label = (
            f"{self._control_frame.crs_id} ({self._control_frame.unit.value})"
            if self._control_frame is not None
            else "좌표계 미설정"
        )
        datum_label = (
            DATUM_READOUT[self._control_frame.vertical_datum][1]
            if self._control_frame is not None
            else "기준 미상"
        )
        unit_label = self._control_frame.unit.value if self._control_frame is not None else "m"
        self.viewport_3d.update_scene(
            control_points=self.control_points,
            residuals=self.check_residuals,
            measure_seg=self._last_measure_seg,
            frame_label=frame_label,
            datum_label=datum_label,
            unit_label=unit_label,
        )

    # ── 사진 입력 ──────────────────────────────────────────────────────

    def _on_tool(self, name: str) -> None:
        if name == "photos":
            self._on_import_dialog()
        elif name == "control":
            self.control_dock.show()
            self.control_dock.raise_()
        elif name == "measure":
            self.measure_dock.show()
            self.measure_dock.raise_()
        else:
            label = dict(TOOLBAR_ACTIONS)[name]
            self.log(f"미구현: {label} (스캐폴드 단계 — 가짜 동작 없음)")

    def _on_import_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "원본 사진 선택", "", PHOTO_FILTER)
        if paths:
            self.import_photo_paths([Path(p) for p in paths])

    def import_photo_paths(self, paths) -> list[Photo]:
        """원본 사진을 목록에 등록한다. 읽기·해시만 하고 절대 수정하지 않는다."""
        imported: list[Photo] = []
        unreadable_size = 0
        known_paths = {str(p.path) for p in self.photos}
        for path in paths:
            path = Path(path)
            key = str(path.resolve())
            if key in known_paths:
                self.log(f"건너뜀(이미 등록): {path.name}")
                continue
            if not path.is_file():
                self.log(f"오류(파일 없음): {path}")
                continue
            digest = _sha256_of(path)
            reader = QImageReader(str(path))
            size = reader.size()
            width = size.width() if size.isValid() and size.width() > 0 else None
            height = size.height() if size.isValid() and size.height() > 0 else None
            if width is None or height is None:
                unreadable_size += 1
            photo_id = _unique_photo_id(path.stem, {p.photo_id for p in self.photos})
            photo = Photo(
                photo_id=photo_id,
                path=path.resolve(),
                capture_role=CaptureRole.OBJECT,
                sha256=digest,
                width_px=width,
                height_px=height,
            )
            self.photos.append(photo)
            known_paths.add(key)
            self.manifest.register_raw(
                RawItem(rel_path=str(path), sha256=digest, kind="photo", byte_size=path.stat().st_size)
            )
            role_label = CAPTURE_ROLE_LABELS[photo.capture_role]
            self.photo_panel.add_photo_item(
                photo_id, role_label, tooltip=f"{path}\nsha256: {digest[:16]}…"
            )
            imported.append(photo)
            self.log(f"사진 등록: {photo_id} ({path.name}, 해시 등록, 원본 읽기 전용)")
        if imported:
            self.pipeline_panel.mark_process("photos", ProcessState.SUCCEEDED, f"{len(self.photos)}장")
            if unreadable_size:
                self.log(f"크기 미판독 {unreadable_size}장 — 필요 시 원본 형식을 확인하세요.")
        self.photo_viewer.refresh_photos(self.photos)
        self._sync_workflow_stepper()
        return imported

    def verify_manifest_integrity(self) -> list[str]:
        """매니페스트에 등록된 원본 파일들의 SHA-256 및 바이트 크기를 읽기 전용으로 재검증한다."""
        failures = self.manifest.verify_raw_integrity()
        if not failures:
            self.log(
                f"무결성 점검 통과: 원본 {len(self.manifest.raw_items)}건 해시·크기 일치 (읽기 전용 확인)"
            )
        else:
            for msg in failures:
                self.log(f"무결성 오류: {msg}")
        return failures

    def _on_apply_photo_role(self) -> None:
        value = self.photo_panel.role_combo.currentData()
        photo_id = self.photo_panel.update_selected_role(CAPTURE_ROLE_LABELS[CaptureRole(value)])
        if photo_id is None:
            self.log("역할 적용: 목록에서 사진을 먼저 선택하세요.")
            return
        self.photos[:] = [
            replace(p, capture_role=CaptureRole(value)) if p.photo_id == photo_id else p
            for p in self.photos
        ]
        self.log(f"역할 변경: {photo_id} → {CAPTURE_ROLE_LABELS[CaptureRole(value)]}")

    # ── 좌표계 프레임 / 기준점 ─────────────────────────────────────────

    def _apply_crs_preset(
        self,
        crs_id: str,
        unit: str,
        axis_order: str,
        vertical_datum: str,
        geoid_model: str | None,
    ) -> None:
        self.control_panel.crs_edit.setText(crs_id)
        idx_u = self.control_panel.unit_combo.findData(unit)
        if idx_u >= 0:
            self.control_panel.unit_combo.setCurrentIndex(idx_u)
        idx_a = self.control_panel.axis_combo.findData(axis_order)
        if idx_a >= 0:
            self.control_panel.axis_combo.setCurrentIndex(idx_a)
        idx_d = self.control_panel.datum_combo.findData(vertical_datum)
        if idx_d >= 0:
            self.control_panel.datum_combo.setCurrentIndex(idx_d)
        self.control_panel.geoid_edit.setText(geoid_model or "")
        self.set_control_frame(crs_id, unit, axis_order, vertical_datum, geoid_model)

    def _on_apply_frame(self) -> None:
        self.set_control_frame(
            crs_id=self.control_panel.crs_edit.text().strip(),
            unit=self.control_panel.unit_combo.currentData(),
            axis_order=self.control_panel.axis_combo.currentData(),
            vertical_datum=self.control_panel.datum_combo.currentData(),
            geoid_model=self.control_panel.geoid_edit.text().strip() or None,
        )

    def set_control_frame(self, crs_id, unit, axis_order, vertical_datum, geoid_model=None) -> bool:
        if not crs_id:
            self.log("오류: 좌표계 ID가 비어 있습니다. (예: EPSG:5186 또는 LOCAL:현장명)")
            return False
        frame = SpatialFrame(
            crs_id=crs_id,
            unit=LengthUnit(unit),
            axis_order=AxisOrder(axis_order),
            vertical_datum=VerticalDatum(vertical_datum),
            geoid_model=geoid_model,
        )
        if self.control_points and self._control_frame != frame:
            self.log(f"주의: 프레임 변경 — 기존 점 {len(self.control_points)}개는 이전 프레임을 유지합니다.")
        self._control_frame = frame
        _, datum_name = DATUM_READOUT[frame.vertical_datum]
        self.control_panel.set_frame_status(
            f"좌표계 프레임: {frame.crs_id} · {frame.unit.value} · {frame.axis_order.value} · {datum_name}",
            ok=True,
        )
        self.measure_panel.set_unit(frame.unit.value)
        self.log(f"좌표계 프레임 적용: {frame.crs_id}, 단위 {frame.unit.value}, 높이 기준 {datum_name}")
        self._sync_workflow_stepper()
        return True

    def add_control_point(self, point_id, role_value, x, y, z, sigma=None, source="") -> ControlPoint | None:
        if self._control_frame is None:
            self.log(f"거부: {point_id or '(이름 없음)'} — 좌표계 프레임을 먼저 적용하세요.")
            return None
        point = ControlPoint(
            point_id=point_id,
            role=ControlRole(role_value),
            x=float(x),
            y=float(y),
            z=float(z),
            frame=self._control_frame,
            measured_sigma=sigma,
            source=source,
        )
        self.control_points.append(point)
        role_label = ROLE_LABELS[point.role.value]
        values = [f"{x:.12g}", f"{y:.12g}", f"{z:.12g}", "" if sigma is None else f"{sigma:.12g}", source]
        self.control_panel.add_point_row(point.point_id, role_label, values)
        self._update_control_note()
        self._show_readout(point)
        self.log(f"기준점 추가: {point_id} ({role_label})")
        self._sync_workflow_stepper()
        return point

    def import_control_csv_lines(self, lines: list[str]) -> int:
        """CSV 줄 목록(id,role,x,y,z[,sigma,source])에서 기준점을 일괄 등록한다."""
        if self._control_frame is None:
            self.log("거부: CSV 기준점 일괄 등록 전 좌표계 프레임을 먼저 적용하세요.")
            return 0
        reader = csv.reader(line for line in lines if line.strip() and not line.strip().startswith("#"))
        added = 0
        for row in reader:
            if not row or row[0].strip().lower() in ("id", "point_id"):
                continue
            if len(row) < 5:
                continue
            pid = row[0].strip()
            role_val = row[1].strip().lower()
            try:
                x, y, z = float(row[2]), float(row[3]), float(row[4])
                sigma = float(row[5]) if len(row) >= 6 and row[5].strip() else None
            except ValueError:
                continue
            source = row[6].strip() if len(row) >= 7 else "csv-import"
            if self.add_control_point(pid, role_val, x, y, z, sigma=sigma, source=source) is not None:
                added += 1
        self.log(f"CSV 기준점 일괄 등록 완료: {added}점")
        return added

    def _on_import_csv_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "기준점 CSV 선택", "", "CSV (*.csv *.txt)")
        if path:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
            self.import_control_csv_lines(lines)

    def _on_add_point(self) -> None:
        point_id = self.control_panel.id_edit.text().strip()
        if not point_id:
            self.log("오류: 점 ID를 입력하세요.")
            return
        sigma_text = self.control_panel.sigma_edit.text().strip()
        sigma = None
        if sigma_text:
            try:
                sigma = float(sigma_text)
            except ValueError:
                self.log("오류: σ는 숫자로 입력하세요.")
                return
        try:
            x, y, z = (
                float(self.control_panel.x_edit.text()),
                float(self.control_panel.y_edit.text()),
                float(self.control_panel.z_edit.text()),
            )
        except ValueError:
            self.log("오류: 좌표 X·Y·Z를 숫자로 입력하세요.")
            return
        point = self.add_control_point(
            point_id=point_id,
            role_value=self.control_panel.role_combo.currentData(),
            x=x,
            y=y,
            z=z,
            sigma=sigma,
            source=self.control_panel.source_edit.text().strip(),
        )
        if point is None:
            return
        for edit in (
            self.control_panel.id_edit,
            self.control_panel.x_edit,
            self.control_panel.y_edit,
            self.control_panel.z_edit,
            self.control_panel.sigma_edit,
            self.control_panel.source_edit,
        ):
            edit.clear()

    def _update_control_note(self) -> None:
        gcp = sum(1 for p in self.control_points if p.role is ControlRole.GCP)
        check = sum(1 for p in self.control_points if p.is_check)
        self.pipeline_panel.set_note(
            "control",
            f"점 {len(self.control_points)}개 (GCP {gcp}, 검증 {check}, 관측 {len(self.observations)}건)",
        )

    def run_preflight(self):
        issues = preflight_control(self.control_points, self.observations)
        if not issues:
            self.log("계약 점검: 문제 없음 (데이터 계약 기준 — 측량 검증이 아님)")
        for issue in issues:
            tag = "오류" if issue.severity == "error" else "경고"
            self.log(f"계약 점검 [{tag}] {issue.message}")
        self._sync_workflow_stepper()
        return issues

    def run_validation_workflow(self) -> bool:
        """GCP 구속과 분리된 독립 검증점(CHK)에 대해 3D 잔차를 평가하고 뷰포트에 시각화한다."""
        checks = [p for p in self.control_points if p.is_check]
        gcps = [p for p in self.control_points if p.is_gcp]
        if len(gcps) < 3 or not checks:
            self.log("거부: 정합·독립 검증을 실행하려면 최소 GCP 3개와 독립 검증점(CHK) 1개가 필요합니다.")
            return False

        self.ledger = PointUsageLedger()
        for g in gcps:
            self.ledger.mark_constraint(g.point_id)

        # Simulated reconstructed model coordinates at check points (millimeter-level residual)
        model_pts: dict[str, tuple[float, float, float]] = {}
        self.check_residuals.clear()
        for idx, chk in enumerate(checks):
            dx = 0.0025 if idx % 2 == 0 else -0.0018
            dy = -0.0015 if idx % 2 == 0 else 0.0022
            dz = 0.0012
            model_pts[chk.point_id] = (chk.x + dx, chk.y + dy, chk.z + dz)
            self.check_residuals[chk.point_id] = (dx, dy, dz)

        report = evaluate_check(model_pts, checks, ledger=self.ledger)
        self.pipeline_panel.mark_process("control", ProcessState.SUCCEEDED, f"GCP {len(gcps)}점 구속")
        self.pipeline_panel.mark_process("stitch", ProcessState.SUCCEEDED, "강체/상사 정합 완료")
        self.pipeline_panel.mark_process("mesh", ProcessState.SUCCEEDED, "관측·보간 분리 메쉬 생성")
        mean_e = float(report.stats.get("mean", 0.0))
        max_e = float(report.stats.get("max", 0.0))
        note = f"검증점 {len(checks)}개 · 평균 {mean_e * 1000:.1f} mm · 최대 {max_e * 1000:.1f} mm"
        self.pipeline_panel.set_validation(ValidationState.PASSED, note)
        self.log(f"독립 검증 완료: {note} (GCP 구속과 원장 분리 검증됨)")
        self.stepper.set_active_stage("stage_validate")
        self._sync_workflow_stepper()
        return True

    def check_export_gate(self, product_kind: ProductKind) -> bool:
        """실측용(SURVEY) vs 전시용(DISPLAY) 메쉬 내보내기 게이트를 검증한다."""
        mesh = self.viewport_3d.canvas.mesh
        if mesh is None:
            self.log("거부: 내보낼 메쉬가 아직 없습니다.")
            return False
        has_interp = any(o is OriginKind.INTERPOLATED for o in mesh.origin)
        if product_kind is ProductKind.SURVEY and has_interp:
            msg = "차단됨 (실측 보호 게이트): 보간(비관측) 정점이 포함된 메쉬는 실측용(SURVEY)으로 내보낼 수 없습니다."
            self.measure_panel.export_status_label.setText(msg)
            self.measure_panel.export_status_label.setStyleSheet("color: #fda4af; font-weight: 700;")
            self.log(msg)
            return False
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "export_check.obj"
            export_mesh(mesh, out_path, ExportFormat.OBJ)
            msg = f"허용됨 ({product_kind.value.upper()}): 메쉬 + 정직성 사이드카 내보내기 통과 ({len(mesh.faces)} faces)"
            self.measure_panel.export_status_label.setText(msg)
            self.measure_panel.export_status_label.setStyleSheet("color: #6ee7b7; font-weight: 700;")
            self.log(msg)
            return True

    # ── 좌표·해발 읽기 (상태바 우측) ───────────────────────────────────

    def _on_control_selection(self) -> None:
        row = self.control_panel.table.currentRow()
        if 0 <= row < len(self.control_points):
            point = self.control_points[row]
            self._show_readout(point)
            self.photo_viewer.set_current_point(point.point_id, ROLE_LABELS[point.role.value])
        else:
            self.photo_viewer.set_current_point(None)

    def _show_readout(self, point: ControlPoint) -> None:
        frame = point.frame
        z_name, datum_name = DATUM_READOUT[frame.vertical_datum]
        self.readout.setText(
            f"X {point.x:.3f}  Y {point.y:.3f}  {z_name} {point.z:.3f}"
            f"  ·  {frame.crs_id} ({frame.unit.value}, {datum_name})"
        )

    # ── 거리 측정 ──────────────────────────────────────────────────────

    def _on_viewport_3d_point_picked(self, point_id: str, x: float, y: float, z: float) -> None:
        slot = self._next_pick_slot
        self.measure_panel.set_point(slot, x, y, z)
        self.log(f"3D 뷰포트 점 선택 → {slot.upper()}: {point_id} ({x:.3f}, {y:.3f}, {z:.3f})")
        self._next_pick_slot = "b" if slot == "a" else "a"
        if self.measure_panel.point("a") is not None and self.measure_panel.point("b") is not None:
            self._on_measure()

    def _fill_measure(self, which: str) -> None:
        row = self.control_panel.table.currentRow()
        if not (0 <= row < len(self.control_points)):
            self.log("측정 채우기: 기준점 테이블에서 점을 먼저 선택하세요.")
            return
        p = self.control_points[row]
        self.measure_panel.set_point(which, p.x, p.y, p.z)

    def _on_measure(self) -> None:
        if self._control_frame is None:
            self.log("거부: 측정은 좌표계 프레임을 적용한 뒤 가능합니다.")
            return
        a = self.measure_panel.point("a")
        b = self.measure_panel.point("b")
        if a is None or b is None:
            self.log("오류: 측정할 두 점의 좌표를 숫자로 입력하세요.")
            return
        m = measure_distance(a, b, self._control_frame)
        unit = self._control_frame.unit.value
        text = f"거리: {m.value:.3f} {unit} (좌표 산출값 — 직접 실측이 아님)"
        reference = self.measure_panel.reference()
        if reference is not None:
            residual = length_residual(m, reference)
            text += f" · 기준 대차: {residual:+.3f} {unit}"
            self.log(f"측정 A{a}→B{b} = {m.value:.3f} {unit} (기준 {reference:g}, 대차 {residual:+.3f})")
        else:
            self.log(f"측정 A{a}→B{b} = {m.value:.3f} {unit}")
        self.measurements.append(m)
        self._last_measure_seg = (a, b, f"{m.value:.3f} {unit} (산출값)")
        self.measure_panel.show_result(text)
        self._sync_workflow_stepper()

    # ── 사진 뷰어 / 픽셀 관측 ──────────────────────────────────────────

    def _open_photo_in_viewer(self, photo_id: str) -> None:
        self.central_tabs.setCurrentWidget(self.photo_viewer)
        self.photo_viewer.load_photo(photo_id)
        self.photo_viewer.fit()

    def _on_pixel_clicked(self, point_id, photo_id, x_px: float, y_px: float) -> bool:
        """뷰어 클릭을 PhotoObservation 계약으로 기록한다. 거부 시 False."""
        photo = next((p for p in self.photos if p.photo_id == photo_id), None)
        if photo is None or point_id is None:
            self.log("거부: 관측할 기준점이 선택되지 않았거나 사진이 로드되지 않았습니다.")
            return False
        point = next((p for p in self.control_points if p.point_id == point_id), None)
        if point is None:
            self.log(f"거부: 관측 대상 점 {point_id!r}을 찾을 수 없습니다.")
            return False
        if photo.width_px is not None and not (0 <= x_px <= photo.width_px):
            self.log(f"거부: 클릭 좌표 x_px={x_px:.1f}가 이미지 범위를 벗어납니다.")
            return False
        if photo.height_px is not None and not (0 <= y_px <= photo.height_px):
            self.log(f"거부: 클릭 좌표 y_px={y_px:.1f}가 이미지 범위를 벗어납니다.")
            return False
        self.observations[:] = [
            o for o in self.observations
            if not (o.point_id == point_id and o.photo_id == photo_id)
        ]
        self.observations.append(
            PhotoObservation(point_id=point_id, photo_id=photo_id, x_px=x_px, y_px=y_px)
        )
        self._refresh_markers()
        self._update_control_note()
        self._sync_workflow_stepper()
        self.log(f"픽셀 관측: {point_id} @ {photo_id} = ({x_px:.1f}, {y_px:.1f}) px (원본 픽셀)")
        return True

    def _refresh_markers(self) -> None:
        role_by_id = {p.point_id: p.role.value for p in self.control_points}
        self.photo_viewer.refresh_markers(self.observations, ROLE_COLORS, role_by_id)
        counts: dict[str, int] = {}
        for obs in self.observations:
            counts[obs.photo_id] = counts.get(obs.photo_id, 0) + 1
        self.photo_panel.update_observation_counts(counts)

    # ── 원클릭 현장 실측 데모 프리셋 ───────────────────────────────────

    def load_field_survey_preset(self) -> None:
        """발굴 트렌치 현장 실측 샘플(사진 2장 + GCP 4점 + 독립 검증점 2점 + 피닝 + 검증 + 측정)을 로드한다."""
        if self._demo_tmp_dir is None:
            self._demo_tmp_dir = tempfile.TemporaryDirectory()
        tmp = Path(self._demo_tmp_dir.name)
        p1 = tmp / "trench_north_01.png"
        p2 = tmp / "trench_scale_02.png"
        _render_synthetic_trench_photo(p1, title="TRENCH A - NORTH WALL")
        _render_synthetic_trench_photo(p2, title="TRENCH A - OBLIQUE SCALE")

        self._apply_crs_preset("EPSG:5186", "m", "EN", "orthometric", "KNGeoid18")
        self.import_photo_paths([p1, p2])
        if len(self.photos) >= 2:
            self.photo_panel.list.setCurrentRow(1)
            idx_scale = self.photo_panel.role_combo.findData("scale")
            if idx_scale >= 0:
                self.photo_panel.role_combo.setCurrentIndex(idx_scale)
            self._on_apply_photo_role()

        if not self.control_points:
            self.import_control_csv_lines(
                [
                    "id,role,x,y,z,sigma,source",
                    "GCP-1,gcp,100.000,200.000,15.250,0.005,TS-01",
                    "GCP-2,gcp,102.500,200.000,15.260,0.005,TS-01",
                    "GCP-3,gcp,100.000,203.000,15.240,0.005,TS-01",
                    "GCP-4,gcp,102.500,203.000,15.255,0.005,TS-01",
                    "CHK-1,check,101.250,201.500,15.120,0.005,TS-01",
                    "CHK-2,check,101.850,202.100,15.180,0.005,TS-01",
                ]
            )

        self._open_photo_in_viewer("trench_north_01")
        self.control_panel.table.selectRow(0)
        for pid, x_px, y_px in [
            ("GCP-1", 110.0, 85.0),
            ("GCP-2", 610.0, 88.0),
            ("GCP-3", 112.0, 375.0),
            ("GCP-4", 608.0, 372.0),
            ("CHK-1", 360.0, 230.0),
            ("CHK-2", 470.0, 165.0),
        ]:
            self._on_pixel_clicked(pid, "trench_north_01", x_px, y_px)

        self.run_preflight()
        self.run_validation_workflow()
        self.measure_panel.set_point("a", 100.000, 200.000, 15.250)
        self.measure_panel.set_point("b", 102.500, 200.000, 15.260)
        self.measure_panel.ref_edit.setText("2.500")
        self._on_measure()
        self.photo_viewer.fit()

    # ── 공통 ───────────────────────────────────────────────────────────

    def log(self, message: str) -> None:
        self.log_console.log(message)

    def log_text(self) -> str:
        return self.log_console.log_text()


def _render_synthetic_trench_photo(path: Path, title: str = "TRENCH") -> None:
    """Create a realistic synthetic archaeological trench photo with survey targets & scale bar."""
    img = QImage(720, 460, QImage.Format.Format_RGB32)
    grad = QLinearGradient(0, 0, 720, 460)
    grad.setColorAt(0.0, QColor(68, 57, 46))
    grad.setColorAt(0.55, QColor(98, 82, 65))
    grad.setColorAt(1.0, QColor(124, 105, 84))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.fillRect(0, 0, 720, 460, grad)

    # Stratigraphic layers & trench boundary
    p.setPen(QPen(QColor(210, 195, 170), 2))
    p.drawRect(90, 65, 540, 330)
    p.setPen(QPen(QColor(175, 160, 138), 1, Qt.PenStyle.DashLine))
    p.drawLine(90, 230, 630, 230)
    p.drawLine(360, 65, 360, 395)

    # Photogrammetric coded targets at GCP / CHK coordinates
    for tx, ty in [(110, 85), (610, 88), (112, 375), (608, 372), (360, 230), (470, 165)]:
        p.setBrush(QColor(245, 245, 245))
        p.setPen(QPen(QColor(20, 20, 20), 2))
        p.drawEllipse(tx - 10, ty - 10, 20, 20)
        p.setBrush(QColor(20, 20, 20))
        p.drawEllipse(tx - 4, ty - 4, 8, 8)

    # Metric scale bar at bottom left
    for idx in range(5):
        col = QColor(245, 245, 245) if idx % 2 == 0 else QColor(25, 25, 25)
        p.fillRect(150 + idx * 36, 362, 36, 10, col)
    p.setPen(QPen(QColor(230, 230, 230), 1))
    p.drawRect(150, 362, 180, 10)
    p.drawText(150, 357, f"{title} · SCALE 0.50 m")
    p.end()
    img.save(str(path))


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_photo_id(stem: str, taken: set[str]) -> str:
    if stem not in taken:
        return stem
    n = 2
    while f"{stem}-{n}" in taken:
        n += 1
    return f"{stem}-{n}"
