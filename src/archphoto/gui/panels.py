"""Reusable panels for the main window.

Each panel owns its widgets only; cross-panel orchestration (manifest, hashing,
contracts) lives in :mod:`archphoto.gui.main_window`. Panels expose small
Python-side accessors (``*_state`` / row counts) so offscreen tests can verify
content without poking at Qt internals.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from archphoto.runlog.record import ProcessState, ValidationState

# --- vocabulary (explicit, per AGENTS.md) -----------------------------------

ROLE_LABELS = {
    "gcp": "GCP(구속)",
    "check": "검증점",
    "scale": "축척",
    "check_length": "검증길이",
    "constraint": "구속",
}

ROLE_COLORS = {
    "gcp": "#2563eb",
    "check": "#d97706",
    "scale": "#0d9488",
    "check_length": "#9333ea",
    "constraint": "#6b7280",
}

PROCESS_LABELS = {
    ProcessState.NOT_STARTED: "미시작",
    ProcessState.RUNNING: "진행중",
    ProcessState.SUCCEEDED: "완료",
    ProcessState.FAILED: "실패",
    ProcessState.PARTIAL: "부분",
}

VALIDATION_LABELS = {
    ValidationState.NOT_RUN: "미실시",
    ValidationState.PASSED: "통과",
    ValidationState.FAILED: "미달",
    ValidationState.INCONCLUSIVE: "판단불가",
}

# Pipeline rows: (key, 표시명). 검증(독립) uses ValidationState vocabulary.
PIPELINE_STEPS = [
    ("photos", "사진"),
    ("camera", "카메라"),
    ("control", "기준점(구속)"),
    ("stitch", "정합(붙이기)"),
    ("mesh", "메시"),
    ("validate", "검증(독립)"),
]


def _now_stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


class LogConsole(QPlainTextEdit):
    """Read-only run log console."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)

    def log(self, message: str) -> None:
        self.appendPlainText(f"[{_now_stamp()}] {message}")

    def log_text(self) -> str:
        return self.toPlainText()


class PhotoPanel(QWidget):
    """Left dock: imported photos with capture role and integrity info."""

    open_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.list = QListWidget(self)
        self.list.itemDoubleClicked.connect(self._emit_open)
        layout.addWidget(self.list)

        form = QWidget(self)
        form_layout = QHBoxLayout(form)
        self.role_combo = QComboBox(form)
        self.role_combo.addItem("피사체(OBJECT)", "object")
        self.role_combo.addItem("축척기준(SCALE)", "scale")
        self.role_combo.addItem("참고(REFERENCE)", "reference")
        self.apply_role_button = QPushButton("역할 적용", form)
        form_layout.addWidget(self.role_combo)
        form_layout.addWidget(self.apply_role_button)
        layout.addWidget(form)

    def add_photo_item(self, photo_id: str, role_label: str, tooltip: str) -> None:
        item = QListWidgetItem(f"{photo_id}  [{role_label}]", self.list)
        item.setData(Qt.ItemDataRole.UserRole, photo_id)
        item.setToolTip(tooltip)

    def update_selected_role(self, role_label: str) -> str | None:
        item = self.list.currentItem()
        if item is None:
            return None
        photo_id = item.data(Qt.ItemDataRole.UserRole)
        item.setText(f"{photo_id}  [{role_label}]")
        return str(photo_id)

    def photo_ids(self) -> list[str]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def _emit_open(self, item: QListWidgetItem) -> None:
        photo_id = item.data(Qt.ItemDataRole.UserRole)
        if photo_id:
            self.open_requested.emit(str(photo_id))


class ControlPanel(QWidget):
    """Right dock: coordinate frame editor + surveyed point table.

    The frame (CRS/unit/axis order/vertical datum) MUST be applied before any
    point can be added — the UI enforces the same contract as the data model.
    """

    COLUMNS = ["ID", "역할", "X", "Y", "Z", "σ", "출처"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        frame_box = QWidget(self)
        form = QFormLayout(frame_box)
        self.crs_edit = QLineEdit(frame_box)
        self.crs_edit.setPlaceholderText('예: EPSG:5186 또는 LOCAL:현장명')
        self.unit_combo = QComboBox(frame_box)
        for label, value in [("m", "m"), ("cm", "cm"), ("mm", "mm"), ("ft", "ft")]:
            self.unit_combo.addItem(label, value)
        self.axis_combo = QComboBox(frame_box)
        self.axis_combo.addItem("E-N (동-북)", "EN")
        self.axis_combo.addItem("N-E (북-동)", "NE")
        self.datum_combo = QComboBox(frame_box)
        for label, value in [
            ("정고도(평균해수면)", "orthometric"),
            ("타원체고", "ellipsoidal"),
            ("현지 기준(수준점)", "local"),
            ("미상 — 반드시 확인", "unknown"),
        ]:
            self.datum_combo.addItem(label, value)
        self.geoid_edit = QLineEdit(frame_box)
        self.geoid_edit.setPlaceholderText("지오이드 모델(타원체↔정고 변환 시)")
        self.apply_frame_button = QPushButton("좌표계 프레임 적용", frame_box)
        form.addRow("좌표계", self.crs_edit)
        form.addRow("단위", self.unit_combo)
        form.addRow("축 순서", self.axis_combo)
        form.addRow("높이 기준", self.datum_combo)
        form.addRow("지오이드", self.geoid_edit)
        form.addRow(self.apply_frame_button)
        layout.addWidget(frame_box)

        self.frame_status = QLabel("좌표계 프레임: 미설정 — 점 추가 금지", self)
        layout.addWidget(self.frame_status)

        entry = QWidget(self)
        entry_form = QFormLayout(entry)
        self.id_edit = QLineEdit(entry)
        self.role_combo = QComboBox(entry)
        for value, label in ROLE_LABELS.items():
            self.role_combo.addItem(label, value)
        coords = QWidget(entry)
        coords_row = QHBoxLayout(coords)
        self.x_edit = QLineEdit(coords)
        self.y_edit = QLineEdit(coords)
        self.z_edit = QLineEdit(coords)
        for edit, axis in [(self.x_edit, "X"), (self.y_edit, "Y"), (self.z_edit, "Z")]:
            edit.setPlaceholderText(axis)
            coords_row.addWidget(edit)
        self.sigma_edit = QLineEdit(entry)
        self.sigma_edit.setPlaceholderText("측량 σ (선택)")
        self.source_edit = QLineEdit(entry)
        self.source_edit.setPlaceholderText('예: total-station')
        self.add_point_button = QPushButton("점 추가", entry)
        entry_form.addRow("ID", self.id_edit)
        entry_form.addRow("역할", self.role_combo)
        entry_form.addRow("좌표 X·Y·Z", coords)
        entry_form.addRow("σ", self.sigma_edit)
        entry_form.addRow("출처", self.source_edit)
        entry_form.addRow(self.add_point_button)
        layout.addWidget(entry)

        self.table = QTableWidget(0, len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        layout.addWidget(self.table)

        self.preflight_button = QPushButton("계약 점검(프리플라이트)", self)
        layout.addWidget(self.preflight_button)

    def set_frame_status(self, text: str, ok: bool) -> None:
        self.frame_status.setText(text)
        color = "#0d9488" if ok else "#b91c1c"
        self.frame_status.setStyleSheet(f"color: {color};")

    def add_point_row(self, point_id: str, role_label: str, values: list[str]) -> int:
        row = self.table.rowCount()
        self.table.insertRow(row)
        cells = [point_id, role_label, *values]
        for col, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if col == 1:
                role_value = next(k for k, v in ROLE_LABELS.items() if v == role_label)
                item.setForeground(QBrush(QColor(ROLE_COLORS[role_value])))
            self.table.setItem(row, col, item)
        return row

    def row_texts(self) -> list[list[str]]:
        out = []
        for r in range(self.table.rowCount()):
            out.append(
                [self.table.item(r, c).text() if self.table.item(r, c) else "" for c in range(len(self.COLUMNS))]
            )
        return out


class PipelinePanel(QWidget):
    """Bottom dock: per-step processing state (and the separate validation state).

    Data entry does NOT move states to 완료/통과 — only actual processing does.
    Entry progress is shown in the 비고 column.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["단계", "상태", "비고"])
        layout.addWidget(self.tree)

        self._rows: dict[str, QTreeWidgetItem] = {}
        self._is_validation: dict[str, bool] = {}
        for key, label in PIPELINE_STEPS:
            is_validation = key == "validate"
            state_text = VALIDATION_LABELS[ValidationState.NOT_RUN] if is_validation else PROCESS_LABELS[ProcessState.NOT_STARTED]
            item = QTreeWidgetItem([label, state_text, ""])
            self.tree.addTopLevelItem(item)
            self._rows[key] = item
            self._is_validation[key] = is_validation

    def set_note(self, key: str, note: str) -> None:
        self._rows[key].setText(2, note)

    def mark_process(self, key: str, state: ProcessState, note: str = "") -> None:
        assert not self._is_validation[key], "검증 단계에는 ProcessState를 쓰지 않습니다"
        self._rows[key].setText(1, PROCESS_LABELS[state])
        if note:
            self._rows[key].setText(2, note)

    def set_validation(self, state: ValidationState, note: str = "") -> None:
        self._rows["validate"].setText(1, VALIDATION_LABELS[state])
        if note:
            self._rows["validate"].setText(2, note)

    def states(self) -> dict[str, str]:
        return {k: self._rows[k].text(1) for k in self._rows}

    def notes(self) -> dict[str, str]:
        return {k: self._rows[k].text(2) for k in self._rows}


class MeasurePanel(QWidget):
    """거리 측정 패널.

    두 3D 좌표 사이 거리를 계산해 표시한다. 결과는 항상 "좌표 산출값"(derived)이고
    직접 실측(줄자·측량기)이 아님을 결과 문구에 명시한다. 기준 길이를 입력하면
    부호 있는 대차(잔차)를 함께 보여준다(CHECK_LENGTH 검증 보조).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self.unit_label = QLabel("단위: 좌표계 프레임 필요", self)
        layout.addWidget(self.unit_label)

        row_a = QWidget(self)
        row_a_layout = QHBoxLayout(row_a)
        self.a_x = QLineEdit(row_a)
        self.a_y = QLineEdit(row_a)
        self.a_z = QLineEdit(row_a)
        for edit, axis in [(self.a_x, "A X"), (self.a_y, "A Y"), (self.a_z, "A Z")]:
            edit.setPlaceholderText(axis)
            row_a_layout.addWidget(edit)
        self.fill_a_button = QPushButton("선택점 → A", row_a)
        row_a_layout.addWidget(self.fill_a_button)
        layout.addWidget(row_a)

        row_b = QWidget(self)
        row_b_layout = QHBoxLayout(row_b)
        self.b_x = QLineEdit(row_b)
        self.b_y = QLineEdit(row_b)
        self.b_z = QLineEdit(row_b)
        for edit, axis in [(self.b_x, "B X"), (self.b_y, "B Y"), (self.b_z, "B Z")]:
            edit.setPlaceholderText(axis)
            row_b_layout.addWidget(edit)
        self.fill_b_button = QPushButton("선택점 → B", row_b)
        row_b_layout.addWidget(self.fill_b_button)
        layout.addWidget(row_b)

        self.ref_edit = QLineEdit(self)
        self.ref_edit.setPlaceholderText("기준 길이(선택, 같은 단위) — 대차 표시")
        layout.addWidget(self.ref_edit)

        self.measure_button = QPushButton("측정", self)
        layout.addWidget(self.measure_button)

        self.result_label = QLabel("결과: —", self)
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)
        layout.addStretch(1)

    def set_unit(self, text: str) -> None:
        self.unit_label.setText(f"단위: {text}")

    def set_point(self, which: str, x: float, y: float, z: float) -> None:
        edits = {"a": (self.a_x, self.a_y, self.a_z), "b": (self.b_x, self.b_y, self.b_z)}
        for edit, value in zip(edits[which], (x, y, z)):
            edit.setText(f"{value:g}")

    def point(self, which: str) -> tuple[float, float, float] | None:
        edits = {"a": (self.a_x, self.a_y, self.a_z), "b": (self.b_x, self.b_y, self.b_z)}
        values = []
        for edit in edits[which]:
            try:
                values.append(float(edit.text()))
            except ValueError:
                return None
        return (values[0], values[1], values[2])

    def reference(self) -> float | None:
        try:
            return float(self.ref_edit.text())
        except ValueError:
            return None

    def show_result(self, text: str) -> None:
        self.result_label.setText(text)
