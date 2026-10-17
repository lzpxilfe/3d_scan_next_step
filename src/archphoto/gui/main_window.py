"""Main application window (PySide6 / Qt).

실측 작업 흐름에 맞춘 도킹 레이아웃 (D-2026-10-12-09):
- 좌측: 사진 목록 (촬영 역할·해시)
- 우측: 기준점(좌표계 편집기 + 점 테이블) / 거리 측정 (탭)
- 하단: 파이프라인 상태 / 로그 콘솔 (탭)
- 중앙: 3D 뷰포트 (플레이스홀더)
- 상태바 우측: 선택한 점의 좌표·높이(해발) 읽기

정직성 규칙 (AGENTS.md): 원본 사진은 읽기 전용(해시 등록만); 좌표계 프레임을 적용하기
전에는 점 추가·측정이 불가; 파이프라인 "검증(독립)" 상태는 실제 독립 검증이 실행될 때만
변경되고 자료 입력으로는 절대 바뀌지 않음; 아직 구현 전 액션은 클릭 시 "미구현"으로
로그에 표시해 가짜 동작을 만들지 않는다.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader
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
from archphoto.gui.photo_viewer import PhotoViewerPanel
from archphoto.preflight import preflight_control
from archphoto.project.manifest import ProjectManifest, RawItem
from archphoto.runlog.record import ProcessState
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
    """도킹 패널 기반 메인 창. 코어 로직은 재구현하지 않고 호출만 한다."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("archphoto — 고고학 사진실측")
        self.photos: list[Photo] = []
        self.control_points: list[ControlPoint] = []
        self.observations = []
        self.measurements = []
        self._control_frame: SpatialFrame | None = None
        self.manifest = ProjectManifest(
            project_id=f"archphoto-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}",
            title="제목 미설정",
        )
        self.actions: dict[str, object] = {}
        self._build_toolbar()
        self._build_docks()
        self._build_central()
        self._build_statusbar()
        self.log("프로젝트 시작 — 원본은 읽기 전용입니다. 좌표계 프레임을 먼저 적용하세요.")

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
        self.photo_dock = QDockWidget("사진", self)
        self.photo_dock.setObjectName("dock_photos")
        self.photo_dock.setWindowIcon(icon("photos"))
        self.photo_dock.setWidget(self.photo_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.photo_dock)

        self.control_panel = ControlPanel()
        self.control_dock = QDockWidget("기준점", self)
        self.control_dock.setObjectName("dock_control")
        self.control_dock.setWindowIcon(icon("control"))
        self.control_dock.setWidget(self.control_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.control_dock)

        self.measure_panel = MeasurePanel()
        self.measure_dock = QDockWidget("거리 측정", self)
        self.measure_dock.setObjectName("dock_measure")
        self.measure_dock.setWindowIcon(icon("measure"))
        self.measure_dock.setWidget(self.measure_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.measure_dock)
        self.tabifyDockWidget(self.control_dock, self.measure_dock)

        self.pipeline_panel = PipelinePanel()
        self.pipeline_dock = QDockWidget("파이프라인", self)
        self.pipeline_dock.setObjectName("dock_pipeline")
        self.pipeline_dock.setWidget(self.pipeline_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.pipeline_dock)

        self.log_console = LogConsole()
        self.log_dock = QDockWidget("로그", self)
        self.log_dock.setObjectName("dock_log")
        self.log_dock.setWidget(self.log_console)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.tabifyDockWidget(self.pipeline_dock, self.log_dock)

        self.control_panel.apply_frame_button.clicked.connect(self._on_apply_frame)
        self.control_panel.add_point_button.clicked.connect(self._on_add_point)
        self.control_panel.preflight_button.clicked.connect(self.run_preflight)
        self.control_panel.table.itemSelectionChanged.connect(self._on_control_selection)
        self.photo_panel.apply_role_button.clicked.connect(self._on_apply_photo_role)
        self.photo_panel.open_requested.connect(self._open_photo_in_viewer)
        self.measure_panel.measure_button.clicked.connect(self._on_measure)
        self.measure_panel.fill_a_button.clicked.connect(lambda: self._fill_measure("a"))
        self.measure_panel.fill_b_button.clicked.connect(lambda: self._fill_measure("b"))

    def _build_central(self) -> None:
        self.central_tabs = QTabWidget(self)
        self.viewport_placeholder = QLabel(
            "3D 메시 뷰포트 — PySide6 OpenGL 위젯으로 구현 예정", self
        )
        self.viewport_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.photo_viewer = PhotoViewerPanel()
        self.photo_viewer.set_observation_callback(self._on_pixel_clicked)
        self.central_tabs.addTab(self.viewport_placeholder, "3D 뷰포트(예정)")
        self.central_tabs.addTab(self.photo_viewer, "사진 뷰어")
        self.setCentralWidget(self.central_tabs)

    def _build_statusbar(self) -> None:
        self.readout = QLabel("좌표: —  ·  해발: —", self)
        self.statusBar().addPermanentWidget(self.readout)

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
        return imported

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
        return point

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
        return issues

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
        self.measure_panel.show_result(text)

    # ── 사진 뷰어 / 픽셀 관측 ──────────────────────────────────────────

    def _open_photo_in_viewer(self, photo_id: str) -> None:
        self.central_tabs.setCurrentWidget(self.photo_viewer)
        self.photo_viewer.load_photo(photo_id)

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
        self.log(f"픽셀 관측: {point_id} @ {photo_id} = ({x_px:.1f}, {y_px:.1f}) px (원본 픽셀)")
        return True

    def _refresh_markers(self) -> None:
        role_by_id = {p.point_id: p.role.value for p in self.control_points}
        self.photo_viewer.refresh_markers(self.observations, ROLE_COLORS, role_by_id)

    # ── 공통 ───────────────────────────────────────────────────────────

    def log(self, message: str) -> None:
        self.log_console.log(message)

    def log_text(self) -> str:
        return self.log_console.log_text()


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
