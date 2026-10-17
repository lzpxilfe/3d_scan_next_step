"""Photo viewer panel: zoomable image + 8x sub-pixel magnifier loupe + pixel observation marking.

사진 위에서 기준점의 픽셀 위치를 찍어 관측(05 §2)을 기록하는 뷰어다. 픽셀 좌표는
원본 이미지 좌표계(왼쪽 위 원점)로 반환한다. 관측 기록 자체는 콜백(main window)이
담당하고, 뷰어는 표시와 좌표 변환만 한다 — 관측 소스는 단일(main.observations)다.
우측 상단에는 8× 서브픽셀 확대 루페(Loupe) 오버레이를 그려 정밀 타겟 피닝을 돕는다.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
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
    """Zoomable image view with 8x sub-pixel magnifier loupe overlay."""

    def __init__(self, on_scene_clicked=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_scene_clicked = on_scene_clicked
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor("#10141c"))
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)

        self.loupe_enabled: bool = True
        self.loupe_zoom: float = 8.0
        self._source_image: QImage | None = None
        self._focus_scene_pos: tuple[float, float] | None = None
        self._focus_label: str = ""

    def set_source_image(self, image: QImage | None) -> None:
        self._source_image = image
        if image is not None and not image.isNull():
            self._focus_scene_pos = (image.width() * 0.5, image.height() * 0.5)
        else:
            self._focus_scene_pos = None
        self.viewport().update()

    def set_loupe_focus(self, x_px: float, y_px: float, label: str = "") -> None:
        self._focus_scene_pos = (float(x_px), float(y_px))
        if label:
            self._focus_label = label
        self.viewport().update()

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if self._source_image is not None:
            pos = self.mapToScene(event.position().toPoint())
            if (
                0.0 <= pos.x() <= self._source_image.width()
                and 0.0 <= pos.y() <= self._source_image.height()
            ):
                self._focus_scene_pos = (pos.x(), pos.y())
                self.viewport().update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        if event.button() == Qt.MouseButton.LeftButton and self._on_scene_clicked is not None:
            pos = self.mapToScene(event.position().toPoint())
            self._focus_scene_pos = (pos.x(), pos.y())
            self._on_scene_clicked(pos.x(), pos.y())
            self.viewport().update()
        super().mousePressEvent(event)

    def drawForeground(self, painter: QPainter, _rect) -> None:  # noqa: N802 (Qt naming)
        if not self.loupe_enabled or self._source_image is None or self._focus_scene_pos is None:
            return
        vw = self.viewport().width()
        vh = self.viewport().height()
        if vw < 220 or vh < 180:
            return

        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        box_size = 136.0
        margin = 12.0
        bx = float(vw) - box_size - margin
        by = margin
        loupe_rect = QRectF(bx, by, box_size, box_size)

        # Loupe background & border
        painter.setBrush(QColor(15, 23, 42, 235))
        painter.setPen(QPen(QColor("#38bdf8"), 1.6))
        painter.drawRoundedRect(QRectF(bx - 4, by - 4, box_size + 8, box_size + 36), 6, 6)

        fx, fy = self._focus_scene_pos
        half_span = (box_size / self.loupe_zoom) * 0.5
        src_rect = QRectF(fx - half_span, fy - half_span, half_span * 2.0, half_span * 2.0)

        painter.save()
        painter.setClipRect(loupe_rect)
        painter.fillRect(loupe_rect, QColor("#0b0f17"))
        painter.drawImage(loupe_rect, self._source_image, src_rect)

        # Subtle sub-pixel grid inside loupe
        grid_pen = QPen(QColor(148, 163, 184, 45), 1)
        painter.setPen(grid_pen)
        step_px = self.loupe_zoom * 2.0
        cx = bx + box_size * 0.5
        cy = by + box_size * 0.5
        offset = step_px
        while offset < box_size * 0.5:
            painter.drawLine(QPointF(cx + offset, by), QPointF(cx + offset, by + box_size))
            painter.drawLine(QPointF(cx - offset, by), QPointF(cx - offset, by + box_size))
            painter.drawLine(QPointF(bx, cy + offset), QPointF(bx + box_size, cy + offset))
            painter.drawLine(QPointF(bx, cy - offset), QPointF(bx + box_size, cy - offset))
            offset += step_px

        # Precision crosshair at loupe center
        painter.setPen(QPen(QColor("#38bdf8"), 1.4))
        painter.drawLine(QPointF(cx - 18, cy), QPointF(cx - 4, cy))
        painter.drawLine(QPointF(cx + 4, cy), QPointF(cx + 18, cy))
        painter.drawLine(QPointF(cx, cy - 18), QPointF(cx, cy - 4))
        painter.drawLine(QPointF(cx, cy + 4), QPointF(cx, cy + 18))
        painter.drawEllipse(QPointF(cx, cy), 4.0, 4.0)
        painter.restore()

        painter.setPen(QPen(QColor("#475569"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(loupe_rect)

        # Top badge inside loupe
        badge_rect = QRectF(bx + 4, by + 4, 86, 18)
        painter.setBrush(QColor(2, 132, 199, 210))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, 3, 3)
        painter.setPen(QColor("#ffffff"))
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, f"8× 루페 {self._focus_label}")

        # Bottom sub-pixel readout under loupe
        painter.setPen(QColor("#e2e8f0"))
        painter.drawText(
            QRectF(bx, by + box_size + 4, box_size, 24),
            Qt.AlignmentFlag.AlignCenter,
            f"px ({fx:.1f}, {fy:.1f})",
        )
        painter.restore()


class PhotoViewerPanel(QWidget):
    """중앙 탭의 정밀 사진 피닝 뷰어: 확대·맞춤·8× 서브픽셀 루페·관측 마커."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        top = QWidget(self)
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        self.photo_combo = QComboBox(top)
        self.photo_combo.currentIndexChanged.connect(self._on_combo_change)
        self.fit_button = QPushButton("맞춤", top)
        self.fit_button.clicked.connect(self.fit)
        self.loupe_check = QCheckBox("8× 정밀 루페", top)
        self.loupe_check.setChecked(True)
        self.loupe_check.toggled.connect(self._on_loupe_toggled)
        self.status_label = QLabel("사진 없음", top)
        self.obs_badge = QLabel("이 사진 관측: 0건", top)
        self.obs_badge.setStyleSheet(
            "background-color: #1e293b; color: #38bdf8; border: 1px solid #334155; "
            "border-radius: 4px; padding: 2px 8px; font-weight: 700;"
        )
        top_layout.addWidget(self.photo_combo, 1)
        top_layout.addWidget(self.fit_button)
        top_layout.addWidget(self.loupe_check)
        top_layout.addWidget(self.obs_badge)
        top_layout.addWidget(self.status_label)
        layout.addWidget(top)

        self.current_point_label = QLabel("관측할 점: (기준점 테이블에서 선택)", self)
        self.current_point_label.setStyleSheet("color: #7dd3fc; font-weight: 600;")
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

    def _on_loupe_toggled(self, checked: bool) -> None:
        self.view.loupe_enabled = checked
        self.view.viewport().update()

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
        self.view.set_source_image(image)
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
        if accepted and point_id:
            self.view.set_loupe_focus(x, y, point_id)
        elif not accepted:
            self.status_label.setText(f"거부됨: 점 미선택 또는 범위 밖 ({photo_id})")

    def set_current_point(self, point_id: str | None, role_label: str = "") -> None:
        self.current_point = (point_id, role_label)
        if point_id:
            self.current_point_label.setText(f"관측할 점: {point_id} ({role_label}) — 사진을 클릭해 정밀 피닝")
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
            self.obs_badge.setText("이 사진 관측: 0건")
            return
        gcp_cnt = 0
        chk_cnt = 0
        last_obs = None
        for obs in observations:
            if obs.photo_id != photo_id:
                continue
            last_obs = obs
            role_key = point_role_of.get(obs.point_id, "")
            if role_key == "gcp":
                gcp_cnt += 1
            elif role_key in ("check", "check_length"):
                chk_cnt += 1
            color_hex = role_colors.get(role_key, "#ffffff")
            color = QColor(color_hex)
            pen = QPen(color, 2.2)
            x, y = obs.x_px, obs.y_px
            group: list = []
            for x1, y1, x2, y2 in [(x - 9, y, x + 9, y), (x, y - 9, x, y + 9)]:
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
            label.setPos(x + 9, y - 15)
            self._scene.addItem(label)
            group.append(label)
            self._marker_groups.append(group)

        total = len(self._marker_groups)
        self.obs_badge.setText(f"이 사진 관측: {total}건 (GCP {gcp_cnt} · 검증 {chk_cnt})")
        if last_obs is not None:
            self.view.set_loupe_focus(last_obs.x_px, last_obs.y_px, last_obs.point_id)

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
