"""GUI tests (PySide6, offscreen). Skipped when PySide6 is not installed.

Covers: icon loading into toolbar widgets, the photogrammetry dock layout,
photo ingest (hash + read-only originals), control-point entry (frame contract,
GCP/check separation), preflight wiring, the coordinate/elevation readout, and
distance measurement. The measurement is honestly labeled as coordinate-derived.
"""

from __future__ import annotations

import hashlib
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6", reason="PySide6 설치 필요 (GUI 테스트)")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from archphoto.gui.main_window import TOOLBAR_ACTIONS, MainWindow  # noqa: E402


def _make_png(path, width: int = 64, height: int = 48) -> None:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(0xFF888888)
    assert image.save(str(path), "PNG")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_window_builds_with_icons(app) -> None:
    win = MainWindow()
    assert win.windowTitle()
    for name, _label in TOOLBAR_ACTIONS:
        action = win.actions[name]
        assert not action.icon().isNull(), f"icon failed to load: {name}"


def test_dock_layout_exists(app) -> None:
    win = MainWindow()
    for dock in (
        win.photo_dock,
        win.control_dock,
        win.measure_dock,
        win.pipeline_dock,
        win.log_dock,
    ):
        assert dock.widget() is not None


def test_import_photos_hashes_and_lists(app, tmp_path) -> None:
    win = MainWindow()
    p1 = tmp_path / "IMG_001.jpg"
    p1.write_bytes(b"\xff\xd8fake-jpeg")
    p2 = tmp_path / "IMG_002.jpg"
    p2.write_bytes(b"\xff\xd8fake-jpeg-2")
    original_1 = p1.read_bytes()

    imported = win.import_photo_paths([p1, p2])

    assert [ph.photo_id for ph in imported] == ["IMG_001", "IMG_002"]
    assert win.photo_panel.photo_ids() == ["IMG_001", "IMG_002"]
    assert len(win.manifest.raw_items) == 2
    assert imported[0].sha256 == hashlib.sha256(b"\xff\xd8fake-jpeg").hexdigest()
    assert imported[0].width_px is None  # fake bytes: size unreadable, honestly None
    assert p1.read_bytes() == original_1  # original untouched
    assert win.pipeline_panel.states()["photos"] == "완료"
    assert "2장" in win.pipeline_panel.notes()["photos"]

    # re-import is skipped, not duplicated
    assert win.import_photo_paths([p1]) == []
    assert len(win.photos) == 2


def test_control_point_requires_frame_first(app) -> None:
    win = MainWindow()
    assert win.add_control_point("GCP-01", "gcp", 0, 0, 0) is None
    assert "좌표계" in win.log_text()
    assert win.control_panel.row_texts() == []


def test_control_flow_and_preflight_clean(app) -> None:
    win = MainWindow()
    assert win.set_control_frame("LOCAL:site", "m", "EN", "orthometric") is True
    assert "프레임 적용" in win.log_text()

    gcp = win.add_control_point("GCP-01", "gcp", 0.0, 0.0, 0.0, source="total-station")
    chk = win.add_control_point("CHK-01", "check", 3.0, 4.0, 0.0)
    assert gcp.is_gcp and chk.is_check

    rows = win.control_panel.row_texts()
    assert rows[0][0] == "GCP-01" and rows[0][1].startswith("GCP")
    assert rows[1][0] == "CHK-01" and rows[1][1] == "검증점"

    issues = win.run_preflight()
    assert issues == []
    assert "점 2개" in win.pipeline_panel.notes()["control"]
    assert "검증 1" in win.pipeline_panel.notes()["control"]

    # data entry never marks independent validation as done
    assert win.pipeline_panel.states()["validate"] == "미실시"


def test_preflight_warns_without_check_point(app) -> None:
    win = MainWindow()
    win.set_control_frame("LOCAL:site", "m", "EN", "orthometric")
    win.add_control_point("GCP-01", "gcp", 0, 0, 0)
    issues = win.run_preflight()
    assert any(i.code == "no_check_point" for i in issues)


def test_readout_labels_height_reference_honestly(app) -> None:
    win = MainWindow()
    win.set_control_frame("LOCAL:a", "m", "EN", "orthometric")
    win.add_control_point("GCP-01", "gcp", 1.5, 2.5, 3.5)
    assert "해발" in win.readout.text() and "3.500" in win.readout.text()

    win.set_control_frame("LOCAL:b", "m", "EN", "unknown")
    win.add_control_point("GCP-02", "gcp", 1.0, 2.0, 3.0)
    assert "해발" not in win.readout.text()
    assert "기준 미상" in win.readout.text()


def test_measure_requires_frame(app) -> None:
    win = MainWindow()
    win.measure_panel.set_point("a", 0, 0, 0)
    win.measure_panel.set_point("b", 3, 4, 0)
    win.measure_panel.measure_button.click()
    assert win.measure_panel.result_label.text() == "결과: —"
    assert "좌표계" in win.log_text()
    assert win.measurements == []


def test_measure_distance_and_reference_residual(app) -> None:
    win = MainWindow()
    win.set_control_frame("LOCAL:m", "m", "EN", "orthometric")
    panel = win.measure_panel
    panel.set_point("a", 0, 0, 0)
    panel.set_point("b", 3, 4, 0)
    panel.ref_edit.setText("5.0")
    panel.measure_button.click()

    assert "거리: 5.000 m" in panel.result_label.text()
    assert "직접 실측이 아님" in panel.result_label.text()
    assert "+0.000" in panel.result_label.text()
    assert len(win.measurements) == 1

    panel.ref_edit.setText("4.0")
    panel.measure_button.click()
    assert "+1.000" in panel.result_label.text()


def test_measure_fill_from_selected_point(app) -> None:
    win = MainWindow()
    win.set_control_frame("LOCAL:m", "m", "EN", "orthometric")
    win.add_control_point("GCP-01", "gcp", 10.0, 20.0, 30.0)
    win.control_panel.table.selectRow(0)
    win.measure_panel.fill_b_button.click()
    assert win.measure_panel.point("b") == (10.0, 20.0, 30.0)


def test_unimplemented_actions_log_honestly(app) -> None:
    win = MainWindow()
    states_before = win.pipeline_panel.states()
    win._on_tool("mesh")
    assert "미구현" in win.log_text()
    assert win.pipeline_panel.states() == states_before


def test_png_import_reads_dimensions(app, tmp_path) -> None:
    win = MainWindow()
    path = tmp_path / "REAL_001.png"
    _make_png(path, 64, 48)
    imported = win.import_photo_paths([path])
    assert imported[0].width_px == 64
    assert imported[0].height_px == 48
    assert win.photo_viewer.photo_combo.count() == 1


def test_pixel_observation_recorded_on_click(app, tmp_path) -> None:
    win = MainWindow()
    path = tmp_path / "IMG_001.png"
    _make_png(path)
    win.import_photo_paths([path])
    win.set_control_frame("LOCAL:site", "m", "EN", "orthometric")
    win.add_control_point("GCP-01", "gcp", 0, 0, 0)
    win.control_panel.table.selectRow(0)
    win.photo_viewer.load_photo("IMG_001")
    win.resize(1000, 700)
    win.show()
    app.processEvents()

    QTest.mouseClick(
        win.photo_viewer.view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(30, 24)
    )

    assert len(win.observations) == 1
    obs = win.observations[0]
    assert obs.point_id == "GCP-01" and obs.photo_id == "IMG_001"
    assert abs(obs.x_px - 30) <= 1.0 and abs(obs.y_px - 24) <= 1.0
    assert obs.photo_undistorted is False
    assert win.photo_viewer.marker_group_count() == 1
    assert "픽셀 관측" in win.log_text()
    assert "관측 1건" in win.pipeline_panel.notes()["control"]


def test_observation_replaces_same_point_photo(app, tmp_path) -> None:
    win = MainWindow()
    path = tmp_path / "IMG_001.png"
    _make_png(path)
    win.import_photo_paths([path])
    win.set_control_frame("LOCAL:site", "m", "EN", "orthometric")
    win.add_control_point("GCP-01", "gcp", 0, 0, 0)
    win.control_panel.table.selectRow(0)
    win.photo_viewer.load_photo("IMG_001")
    win.resize(1000, 700)
    win.show()
    app.processEvents()

    QTest.mouseClick(
        win.photo_viewer.view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(30, 24)
    )
    QTest.mouseClick(
        win.photo_viewer.view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(40, 30)
    )

    assert len(win.observations) == 1
    assert abs(win.observations[0].x_px - 40) <= 1.0
    assert abs(win.observations[0].y_px - 30) <= 1.0
    assert win.photo_viewer.marker_group_count() == 1


def test_observation_refused_without_point_selection(app, tmp_path) -> None:
    win = MainWindow()
    path = tmp_path / "IMG_001.png"
    _make_png(path)
    win.import_photo_paths([path])
    win.photo_viewer.load_photo("IMG_001")
    win.resize(1000, 700)
    win.show()
    app.processEvents()

    QTest.mouseClick(
        win.photo_viewer.view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(30, 24)
    )

    assert win.observations == []
    assert "거부" in win.log_text()


def test_markers_filter_by_loaded_photo(app, tmp_path) -> None:
    win = MainWindow()
    path_a = tmp_path / "IMG_001.png"
    path_b = tmp_path / "IMG_002.png"
    _make_png(path_a)
    _make_png(path_b)
    win.import_photo_paths([path_a, path_b])
    win.set_control_frame("LOCAL:site", "m", "EN", "orthometric")
    win.add_control_point("GCP-01", "gcp", 0, 0, 0)
    win.control_panel.table.selectRow(0)
    win.resize(1000, 700)
    win.show()
    app.processEvents()

    win.photo_viewer.load_photo("IMG_001")
    QTest.mouseClick(
        win.photo_viewer.view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(30, 24)
    )
    win.photo_viewer.load_photo("IMG_002")
    QTest.mouseClick(
        win.photo_viewer.view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(20, 20)
    )

    assert len(win.observations) == 2
    assert win.photo_viewer.marker_group_count() == 1  # IMG_002 only
    win.photo_viewer.load_photo("IMG_001")
    assert win.photo_viewer.marker_group_count() == 1  # IMG_001 only
    assert {o.photo_id for o in win.observations} == {"IMG_001", "IMG_002"}
