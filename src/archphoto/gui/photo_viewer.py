"""Photo viewer panel: zoomable image + pixel observation marking.

사진 위에서 기준점의 픽셀 위치를 찍어 관측(05 §2)을 기록하는 뷰어다. 픽셀 좌표는
원본 이미지 좌표계(왼쪽 위 원점)로 반환한다. 관측 기록 자체는 콜백(main window)이
담당하고, 뷰어는 표시와 좌표 변환만 한다 — 관측 소스는 단일(main.observations)다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ObservationView(QGraphicsView):
    """Zoomable image view. Left-click reports the image-space (scene) position."""

    def __init__(self, on_scene_clicked=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_scene_clicked = on_scene_clicked
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor("#202020"))
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.button() == Qt.MouseButton.LeftButton and self._on_scene_clicked is not None:
            pos = self.mapToScene(event.position().toPoint())
            self._on_scene_clicked(pos.x(), pos.y())
        super().mousePressEvent(event)


class PhotoViewerPanel(QWidget):
    """중앙 탭의 사진 뷰어: 확대·맞춤·관측 마커."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        top = QWidget(self)
        top_layout = QHBoxLayout(top)
        self.photo_combo = QComboBox(top)
        self.photo_combo.currentIndexChanged.connect(self._on_combo_change)
        self.fit_button = QPushButton("맞춤", top)
        self.fit_button.clicked.connect(self.fit)
        self.status_label = QLabel("사진 없음", top)
        top_layout.addWidget(self.photo_combo, 1)
        top_layout.addWidget(self.fit_button)
        top_layout.addWidget(self.status_label)
        layout.addWidget(top)

        self.current_point_label = QLabel("관측할 점: (기준점 테이블에서 선택)", self)
        layout.addWidget(self.current_point_label)

        self.view = ObservationView(self._forward_click, self)
        self._scene = QGraphicsScene(self)
        self.view.setScene(self._scene)
        layout.addWidget(self.view, 1)

        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._photos: dict[str, object] = {}
        self._marker_groups: list[list] = []
        self._last_marker_args: tuple | None = None
        self._observation_callback = None
        self.current_point: tuple[str | None, str] = (None, "")

    # ── 사진 관리 ───────────────────────────────────────────────────────

    def refresh_photos(self, photos) -> None:
        previous = self.photo_combo.currentData()
        self._photos = {p.photo_id: p for p in photos}
        self.photo_combo.blockSignals(True)
        self.photo_combo.clear()
        for photo_id in self._photos:
            self.photo_combo.addItem(photo_id, photo_id)
        if previous in self._photos:
            index = self.photo_combo.findData(previous)
            if index >= 0:
                self.photo_combo.setCurrentIndex(index)
        self.photo_combo.blockSignals(False)
        if not self._photos:
            self.status_label.setText("사진 없음")

    def load_photo(self, photo_id: str) -> bool:
        photo = self._photos.get(photo_id)
        if photo is None:
            self.status_label.setText("사진 없음")
            return False
        image = QImage(str(photo.path))
        if image.isNull():
            self.status_label.setText(f"판독 실패: {photo_id}")
            return False
        index = self.photo_combo.findData(photo_id)
        if index >= 0:
            self.photo_combo.blockSignals(True)
            self.photo_combo.setCurrentIndex(index)
            self.photo_combo.blockSignals(False)
        if self._pixmap_item is not None:
            self._scene.removeItem(self._pixmap_item)
        self._pixmap_item = QGraphicsPixmapItem(QPixmap.fromImage(image))
        self._scene.setSceneRect(0, 0, image.width(), image.height())
        self._scene.addItem(self._pixmap_item)
        self.view.resetTransform()
        self.view.centerOn(0, 0)
        self.status_label.setText(f"사진: {photo_id} ({image.width()}×{image.height()} px)")
        if self._last_marker_args is not None:
            self._draw_markers(*self._last_marker_args)
        return True

    def current_photo_id(self) -> str | None:
        return self.photo_combo.currentData()

    # ── 관측 점 / 클릭 ──────────────────────────────────────────────────

    def set_observation_callback(self, fn) -> None:
        self._observation_callback = fn

    def _forward_click(self, x: float, y: float) -> None:
        if self._pixmap_item is None:
            return
        photo_id = self.current_photo_id()
        point_id, _role = self.current_point
        if self._observation_callback is None:
            return
        accepted = self._observation_callback(point_id, photo_id, x, y)
        if not accepted:
            self.status_label.setText(f"거부됨: 점 미선택 또는 범위 밖 ({photo_id})")

    def set_current_point(self, point_id: str | None, role_label: str = "") -> None:
        self.current_point = (point_id, role_label)
        if point_id:
            self.current_point_label.setText(f"관측할 점: {point_id} ({role_label})")
        else:
            self.current_point_label.setText("관측할 점: (기준점 테이블에서 선택)")

    # ── 마커 ───────────────────────────────────────────────────────────

    def refresh_markers(self, observations, role_colors, point_role_of) -> None:
        self._last_marker_args = (tuple(observations), dict(role_colors), dict(point_role_of))
        self._draw_markers(*self._last_marker_args)

    def _draw_markers(self, observations, role_colors, point_role_of) -> None:
        for group in self._marker_groups:
            for item in group:
                self._scene.removeItem(item)
        self._marker_groups.clear()
        photo_id = self.current_photo_id()
        if photo_id is None:
            return
        for obs in observations:
            if obs.photo_id != photo_id:
                continue
            color_hex = role_colors.get(point_role_of.get(obs.point_id, ""), "#ffffff")
            color = QColor(color_hex)
            pen = QPen(color, 2)
            x, y = obs.x_px, obs.y_px
            group: list = []
            for x1, y1, x2, y2 in [(x - 8, y, x + 8, y), (x, y - 8, x, y + 8)]:
                line = QGraphicsLineItem(x1, y1, x2, y2)
                line.setPen(pen)
                self._scene.addItem(line)
                group.append(line)
            circle = QGraphicsEllipseItem(x - 6, y - 6, 12, 12)
            circle.setPen(pen)
            circle.setBrush(QColor(0, 0, 0, 0))
            self._scene.addItem(circle)
            group.append(circle)
            label = QGraphicsSimpleTextItem(obs.point_id)
            label.setBrush(color)
            label.setPos(x + 8, y - 14)
            self._scene.addItem(label)
            group.append(label)
            self._marker_groups.append(group)

    def marker_group_count(self) -> int:
        return len(self._marker_groups)

    # ── 기타 ───────────────────────────────────────────────────────────

    def fit(self) -> None:
        rect = self._scene.itemsBoundingRect()
        if not rect.isEmpty():
            self.view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _on_combo_change(self, index: int) -> None:  # noqa: N802 (Qt naming)
        photo_id = self.photo_combo.itemData(index)
        if photo_id:
            self.load_photo(photo_id)

    def image_size(self) -> tuple[int, int] | None:
        if self._pixmap_item is None:
            return None
        pixmap = self._pixmap_item.pixmap()
        return (pixmap.width(), pixmap.height())
