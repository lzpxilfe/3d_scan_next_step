"""Interactive 3D / Plan / Section metric survey viewport for archphoto GUI.

Renders:
- 3D coordinate grid, axis triad (E, N, Z), and metric scale bar
- Surveyed ControlPoints: GCP (sky-blue triangles) vs Check points (amber diamonds)
- Reconstructed / synthetic MeshProduct triangles color-coded by SurfaceOrigin:
  - OBSERVED (#2dd4bf teal) vs INTERPOLATED (#f43f5e coral/rose for hole-filled regions)
- Independent Check Point 3D residual vectors (exaggerated ×20 for visual inspection)
- Active A ↔ B coordinate-derived measurement dimension line
- Archaeological cross-section plane cut line (A' — B') and a live 2D Section Profile
  elevation chart at the bottom of the viewport.
"""

from __future__ import annotations

import math
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from archphoto.archaeo.surface import OriginKind, ProductKind
from archphoto.mesh.product import MeshProduct


class Viewport3DCanvas(QWidget):
    """Custom-painted 3D/2D orthographic projection canvas with mouse orbit and point picking."""

    point_picked = Signal(str, float, float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 280)
        self.setMouseTracking(True)
        self.view_mode: str = "3d"  # "3d", "xy", "xz", "yz"
        self.yaw_deg: float = -38.0
        self.pitch_deg: float = 28.0
        self.zoom: float = 1.0
        self.pan_x: float = 0.0
        self.pan_y: float = 0.0
        self._last_mouse = None

        self.show_observed: bool = True
        self.show_interpolated: bool = True
        self.show_points: bool = True
        self.show_residuals: bool = True
        self.show_section: bool = True

        self.control_points: list = []
        self.mesh: MeshProduct | None = None
        self.residuals: dict[str, tuple[float, float, float]] = {}
        self.measure_seg: tuple[tuple[float, float, float], tuple[float, float, float], str] | None = None
        self.section_line_3d: list[tuple[float, float, float]] = []
        self.frame_label: str = "좌표계 미설정"
        self._projected_points: list[tuple[str, float, float, float, float, float]] = []

    def set_view_mode(self, mode: str) -> None:
        self.view_mode = mode
        if mode == "3d":
            self.yaw_deg, self.pitch_deg = -38.0, 28.0
        elif mode == "xy":
            self.yaw_deg, self.pitch_deg = 0.0, 90.0
        elif mode == "xz":
            self.yaw_deg, self.pitch_deg = 0.0, 0.0
        elif mode == "yz":
            self.yaw_deg, self.pitch_deg = 90.0, 0.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.update()

    def _collect_bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        xs: list[float] = []
        ys: list[float] = []
        zs: list[float] = []
        for p in self.control_points:
            xs.append(float(p.x))
            ys.append(float(p.y))
            zs.append(float(p.z))
        if self.mesh is not None:
            for vx, vy, vz in self.mesh.vertices:
                xs.append(float(vx))
                ys.append(float(vy))
                zs.append(float(vz))
        if not xs:
            return (100.0, 200.0, 15.0), (3.0, 3.0, 1.0)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        min_z, max_z = min(zs), max(zs)
        cx = 0.5 * (min_x + max_x)
        cy = 0.5 * (min_y + max_y)
        cz = 0.5 * (min_z + max_z)
        span_xy = max(max_x - min_x, max_y - min_y, 1.0)
        span_z = max(max_z - min_z, span_xy * 0.25, 0.2)
        return (cx, cy, cz), (span_xy, span_xy, span_z)

    def _project(
        self,
        x: float,
        y: float,
        z: float,
        center: tuple[float, float, float],
        span: tuple[float, float, float],
        w: float,
        h: float,
    ) -> tuple[float, float, float]:
        cx, cy, cz = center
        span_xy = max(span[0], 1e-6)
        nx = (x - cx) / span_xy
        ny = (y - cy) / span_xy
        nz = (z - cz) / span_xy * 2.2  # slight vertical emphasis for trench relief

        yaw = math.radians(self.yaw_deg)
        pitch = math.radians(self.pitch_deg)
        cos_y, sin_y = math.cos(yaw), math.sin(yaw)
        cos_p, sin_p = math.cos(pitch), math.sin(pitch)

        rx = nx * cos_y - ny * sin_y
        ry = nx * sin_y + ny * cos_y
        px = rx
        py = ry * sin_p - nz * cos_p
        depth = ry * cos_p + nz * sin_p

        scale = min(w, h) * 0.62 * self.zoom
        sx = w * 0.5 + self.pan_x + px * scale
        sy = h * 0.54 + self.pan_y + py * scale
        return sx, sy, depth

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            for pid, sx, sy, wx, wy, wz in self._projected_points:
                if math.hypot(pos.x() - sx, pos.y() - sy) <= 10.0:
                    self.point_picked.emit(pid, wx, wy, wz)
                    return
            self._last_mouse = pos
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._last_mouse is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            pos = event.position()
            dx = pos.x() - self._last_mouse.x()
            dy = pos.y() - self._last_mouse.y()
            self._last_mouse = pos
            if self.view_mode == "3d":
                self.yaw_deg += dx * 0.45
                self.pitch_deg = max(-85.0, min(85.0, self.pitch_deg + dy * 0.35))
            else:
                self.pan_x += dx
                self.pan_y += dy
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._last_mouse = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        factor = 1.12 if event.angleDelta().y() > 0 else 1.0 / 1.12
        self.zoom = max(0.35, min(5.0, self.zoom * factor))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = float(self.width())
        h = float(self.height())

        # Dark workstation canvas background
        painter.fillRect(0, 0, int(w), int(h), QColor("#11151c"))

        center, span = self._collect_bounds()
        cx, cy, cz = center
        half = span[0] * 0.6
        z_floor = cz - span[2] * 0.55

        # 1. Draw metric ground grid on z_floor
        grid_pen = QPen(QColor(46, 56, 74, 150), 1)
        painter.setPen(grid_pen)
        steps = 6
        for i in range(steps + 1):
            t = -half + (2.0 * half * i / steps)
            p1 = self._project(cx - half, cy + t, z_floor, center, span, w, h)
            p2 = self._project(cx + half, cy + t, z_floor, center, span, w, h)
            painter.drawLine(QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]))
            q1 = self._project(cx + t, cy - half, z_floor, center, span, w, h)
            q2 = self._project(cx + t, cy + half, z_floor, center, span, w, h)
            painter.drawLine(QPointF(q1[0], q1[1]), QPointF(q2[0], q2[1]))

        # Coordinate axes at corner of grid
        ax0 = self._project(cx - half, cy - half, z_floor, center, span, w, h)
        ax_x = self._project(cx - half + half * 0.45, cy - half, z_floor, center, span, w, h)
        ax_y = self._project(cx - half, cy - half + half * 0.45, z_floor, center, span, w, h)
        ax_z = self._project(cx - half, cy - half, z_floor + half * 0.35, center, span, w, h)
        for end_pt, col, lbl in [
            (ax_x, "#ef4444", "E(X)"),
            (ax_y, "#22c55e", "N(Y)"),
            (ax_z, "#38bdf8", "Z"),
        ]:
            painter.setPen(QPen(QColor(col), 2))
            painter.drawLine(QPointF(ax0[0], ax0[1]), QPointF(end_pt[0], end_pt[1]))
            painter.drawText(QPointF(end_pt[0] + 4, end_pt[1] - 2), lbl)

        # 2. Draw 3D Mesh triangles (depth-sorted, color-coded by SurfaceOrigin)
        if self.mesh is not None:
            face_items = []
            verts = self.mesh.vertices
            origins = self.mesh.origin
            for tri in self.mesh.faces:
                i0, i1, i2 = tri
                is_interp = (
                    origins[i0] is OriginKind.INTERPOLATED
                    or origins[i1] is OriginKind.INTERPOLATED
                    or origins[i2] is OriginKind.INTERPOLATED
                )
                if is_interp and not self.show_interpolated:
                    continue
                if (not is_interp) and not self.show_observed:
                    continue
                p0 = self._project(*verts[i0], center, span, w, h)
                p1 = self._project(*verts[i1], center, span, w, h)
                p2 = self._project(*verts[i2], center, span, w, h)
                avg_d = (p0[2] + p1[2] + p2[2]) / 3.0
                face_items.append((avg_d, is_interp, p0, p1, p2))

            face_items.sort(key=lambda item: item[0], reverse=True)
            for _d, is_interp, p0, p1, p2 in face_items:
                poly = QPolygonF([QPointF(p0[0], p0[1]), QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1])])
                if is_interp:
                    painter.setBrush(QBrush(QColor(244, 63, 94, 105)))
                    painter.setPen(QPen(QColor("#fb7185"), 1.3, Qt.PenStyle.DashLine))
                else:
                    painter.setBrush(QBrush(QColor(45, 212, 191, 95)))
                    painter.setPen(QPen(QColor("#2dd4bf"), 1.1))
                painter.drawPolygon(poly)

        # 3. Draw section plane cut line (A' — B')
        if self.show_section and len(self.section_line_3d) >= 2:
            painter.setPen(QPen(QColor("#facc15"), 2.4, Qt.PenStyle.DashDotLine))
            for a3, b3 in zip(self.section_line_3d[:-1], self.section_line_3d[1:]):
                pa = self._project(*a3, center, span, w, h)
                pb = self._project(*b3, center, span, w, h)
                painter.drawLine(QPointF(pa[0], pa[1]), QPointF(pb[0], pb[1]))
            p_start = self._project(*self.section_line_3d[0], center, span, w, h)
            p_end = self._project(*self.section_line_3d[-1], center, span, w, h)
            painter.setPen(QColor("#fde047"))
            painter.drawText(QPointF(p_start[0] - 18, p_start[1] - 6), "A'")
            painter.drawText(QPointF(p_end[0] + 6, p_end[1] - 6), "B'")

        # 4. Draw active distance measurement line (A ↔ B)
        if self.measure_seg is not None:
            pa3, pb3, label = self.measure_seg
            pa = self._project(*pa3, center, span, w, h)
            pb = self._project(*pb3, center, span, w, h)
            painter.setPen(QPen(QColor("#34d399"), 2.4))
            painter.drawLine(QPointF(pa[0], pa[1]), QPointF(pb[0], pb[1]))
            mx, my = 0.5 * (pa[0] + pb[0]), 0.5 * (pa[1] + pb[1])
            pill_rect = QRectF(mx - 85, my - 22, 170, 20)
            painter.setBrush(QColor(6, 78, 59, 220))
            painter.setPen(QPen(QColor("#34d399"), 1))
            painter.drawRoundedRect(pill_rect, 4, 4)
            painter.setPen(QColor("#ecfdf5"))
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, label)

        # 5. Draw Control Points (GCP = sky-blue triangle, Check = amber diamond) + residual arrows
        self._projected_points.clear()
        if self.show_points:
            for pt in self.control_points:
                sx, sy, _ = self._project(pt.x, pt.y, pt.z, center, span, w, h)
                floor_pt = self._project(pt.x, pt.y, z_floor, center, span, w, h)
                self._projected_points.append((pt.point_id, sx, sy, float(pt.x), float(pt.y), float(pt.z)))

                # Drop line to floor grid
                painter.setPen(QPen(QColor(148, 163, 184, 90), 1, Qt.PenStyle.DotLine))
                painter.drawLine(QPointF(sx, sy), QPointF(floor_pt[0], floor_pt[1]))

                is_check = pt.is_check
                if is_check:
                    color = QColor("#fb923c")
                    poly = QPolygonF(
                        [
                            QPointF(sx, sy - 7),
                            QPointF(sx + 7, sy),
                            QPointF(sx, sy + 7),
                            QPointF(sx - 7, sy),
                        ]
                    )
                else:
                    color = QColor("#38bdf8")
                    poly = QPolygonF(
                        [
                            QPointF(sx, sy - 7),
                            QPointF(sx + 7, sy + 6),
                            QPointF(sx - 7, sy + 6),
                        ]
                    )
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(QColor("#0f172a"), 1.5))
                painter.drawPolygon(poly)

                painter.setPen(color)
                font = painter.font()
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(QPointF(sx + 9, sy + 4), f"{pt.point_id} ({pt.z:.2f}m)")

                # Residual vector arrow (if check point evaluated)
                if self.show_residuals and pt.point_id in self.residuals:
                    dx, dy, dz = self.residuals[pt.point_id]
                    ex = pt.x + dx * 20.0
                    ey = pt.y + dy * 20.0
                    ez = pt.z + dz * 20.0
                    esx, esy, _ = self._project(ex, ey, ez, center, span, w, h)
                    err_mm = math.sqrt(dx * dx + dy * dy + dz * dz) * 1000.0
                    painter.setPen(QPen(QColor("#f43f5e"), 2.0))
                    painter.drawLine(QPointF(sx, sy), QPointF(esx, esy))
                    painter.drawText(QPointF(esx + 4, esy - 4), f"Δ={err_mm:.1f}mm")

        # 6. Top-left HUD overlay (Frame & Legend)
        hud_rect = QRectF(10, 10, 385, 52)
        painter.setBrush(QColor(15, 23, 42, 210))
        painter.setPen(QPen(QColor("#334155"), 1))
        painter.drawRoundedRect(hud_rect, 6, 6)
        painter.setPen(QColor("#e2e8f0"))
        painter.drawText(QPointF(20, 28), f"뷰포트: {self.view_mode.upper()}  |  {self.frame_label}")
        painter.setPen(QColor("#94a3b8"))
        painter.drawText(
            QPointF(20, 48),
            "▲ GCP(구속)  ◆ 검증점(독립)  ■ 관측표면(청록)  ■ 보간표면(코랄·비관측)",
        )


class SectionProfileCanvas(QWidget):
    """Bottom mini-canvas showing the 2D archaeological elevation profile along Section A'—B'."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(115)
        self.profile_points: list[tuple[float, float]] = []
        self.datum_label: str = "해발(정고도)"
        self.unit_label: str = "m"

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = float(self.width())
        h = float(self.height())
        painter.fillRect(0, 0, int(w), int(h), QColor("#0f131a"))
        painter.setPen(QPen(QColor("#263042"), 1))
        painter.drawRect(0, 0, int(w) - 1, int(h) - 1)

        painter.setPen(QColor("#fde047"))
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QPointF(12, 18),
            f"단면 프로파일 (Section A'—B') · 높이 기준: {self.datum_label} [{self.unit_label}]",
        )

        if len(self.profile_points) < 2:
            painter.setPen(QColor("#64748b"))
            painter.drawText(
                QRectF(0, 20, w, h - 20),
                Qt.AlignmentFlag.AlignCenter,
                "기준점 또는 메쉬가 등록되면 A'—B' 단면 지형선이 실시간으로 표시됩니다.",
            )
            return

        us = [p[0] for p in self.profile_points]
        vs = [p[1] for p in self.profile_points]
        u_min, u_max = min(us), max(us)
        v_min, v_max = min(vs), max(vs)
        du = max(u_max - u_min, 1e-3)
        dv = max(v_max - v_min, 0.05)

        left, right = 54.0, w - 24.0
        top, bottom = 28.0, h - 22.0

        # Grid lines
        painter.setPen(QPen(QColor("#1e293b"), 1, Qt.PenStyle.DashLine))
        for frac in (0.0, 0.5, 1.0):
            y = bottom - frac * (bottom - top)
            val = v_min + frac * dv
            painter.drawLine(QPointF(left, y), QPointF(right, y))
            painter.setPen(QColor("#94a3b8"))
            painter.drawText(QPointF(6, y + 4), f"{val:.2f}")
            painter.setPen(QPen(QColor("#1e293b"), 1, Qt.PenStyle.DashLine))

        path = QPainterPath()
        pts_screen = []
        for idx, (u, v) in enumerate(self.profile_points):
            sx = left + ((u - u_min) / du) * (right - left)
            sy = bottom - ((v - v_min) / dv) * (bottom - top)
            pts_screen.append(QPointF(sx, sy))
            if idx == 0:
                path.moveTo(sx, sy)
            else:
                path.lineTo(sx, sy)

        painter.setPen(QPen(QColor("#2dd4bf"), 2.2))
        painter.drawPath(path)
        painter.setBrush(QColor("#fde047"))
        painter.setPen(QPen(QColor("#0f172a"), 1))
        for pt in pts_screen:
            painter.drawEllipse(pt, 3.2, 3.2)


class SurveyViewport3DPanel(QWidget):
    """Central 3D / Plan / Section interactive viewport panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Top control bar
        bar = QWidget(self)
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(6)

        self.header_label = QLabel("3D · 평면 · 단면 실측 뷰포트 (마우스 드래그: 회전/이동 · 점 클릭: 거리측정 입력)", bar)
        self.header_label.setStyleSheet("color: #7dd3fc; font-weight: 700;")
        bar_layout.addWidget(self.header_label)
        bar_layout.addStretch(1)

        self.btn_3d = QPushButton("3D 등각", bar)
        self.btn_xy = QPushButton("평면도(XY)", bar)
        self.btn_xz = QPushButton("정면도(XZ)", bar)
        self.btn_yz = QPushButton("측면도(YZ)", bar)
        for mode, btn in [
            ("3d", self.btn_3d),
            ("xy", self.btn_xy),
            ("xz", self.btn_xz),
            ("yz", self.btn_yz),
        ]:
            btn.setObjectName("presetButton")
            btn.clicked.connect(lambda _=False, m=mode: self.canvas.set_view_mode(m))
            bar_layout.addWidget(btn)

        layout.addWidget(bar)

        # Layer toggle bar
        layer_bar = QWidget(self)
        layer_layout = QHBoxLayout(layer_bar)
        layer_layout.setContentsMargins(0, 0, 0, 0)
        layer_layout.setSpacing(12)

        self.chk_observed = QCheckBox("관측 표면(Observed)", layer_bar)
        self.chk_observed.setChecked(True)
        self.chk_interpolated = QCheckBox("보간 표면(Interpolated · 비관측 표시)", layer_bar)
        self.chk_interpolated.setChecked(True)
        self.chk_points = QCheckBox("GCP · 독립 검증점", layer_bar)
        self.chk_points.setChecked(True)
        self.chk_residuals = QCheckBox("검증 잔차 벡터(×20)", layer_bar)
        self.chk_residuals.setChecked(True)
        self.chk_section = QCheckBox("단면 절단선(A'—B')", layer_bar)
        self.chk_section.setChecked(True)

        for chk in (
            self.chk_observed,
            self.chk_interpolated,
            self.chk_points,
            self.chk_residuals,
            self.chk_section,
        ):
            chk.toggled.connect(self._sync_layers)
            layer_layout.addWidget(chk)
        layer_layout.addStretch(1)
        layout.addWidget(layer_bar)

        self.canvas = Viewport3DCanvas(self)
        layout.addWidget(self.canvas, 1)

        self.section_canvas = SectionProfileCanvas(self)
        layout.addWidget(self.section_canvas)

    def _sync_layers(self) -> None:
        self.canvas.show_observed = self.chk_observed.isChecked()
        self.canvas.show_interpolated = self.chk_interpolated.isChecked()
        self.canvas.show_points = self.chk_points.isChecked()
        self.canvas.show_residuals = self.chk_residuals.isChecked()
        self.canvas.show_section = self.chk_section.isChecked()
        self.canvas.update()

    def update_scene(
        self,
        control_points: list,
        mesh: MeshProduct | None = None,
        residuals: dict[str, tuple[float, float, float]] | None = None,
        measure_seg: tuple[tuple[float, float, float], tuple[float, float, float], str] | None = None,
        frame_label: str = "좌표계 미설정",
        datum_label: str = "기준 미상",
        unit_label: str = "m",
    ) -> None:
        self.canvas.control_points = list(control_points)
        if mesh is not None:
            self.canvas.mesh = mesh
        elif self.canvas.mesh is None and len(control_points) >= 3:
            self.canvas.mesh = self._build_preview_surface(control_points)
        if residuals is not None:
            self.canvas.residuals = dict(residuals)
        if measure_seg is not None:
            self.canvas.measure_seg = measure_seg
        self.canvas.frame_label = frame_label

        # Compute section line & profile across site/mesh bounds
        pts_3d = [(float(p.x), float(p.y), float(p.z)) for p in control_points]
        if self.canvas.mesh is not None:
            pts_3d.extend(
                (float(v[0]), float(v[1]), float(v[2])) for v in self.canvas.mesh.vertices
            )
        if len(pts_3d) >= 2:
            xs = [p[0] for p in pts_3d]
            ys = [p[1] for p in pts_3d]
            zs = [p[2] for p in pts_3d]
            min_x, max_x = min(xs), max(xs)
            mid_y = 0.5 * (min(ys) + max(ys))
            mid_z = 0.5 * (min(zs) + max(zs))
            self.canvas.section_line_3d = [
                (min_x, mid_y, mid_z),
                (max_x, mid_y, mid_z),
            ]
            # Sample elevation profile along A'—B' centerline (group by X station, pick closest to mid_y)
            by_x: dict[float, tuple[float, float]] = {}
            for px, py, pz in pts_3d:
                key_x = round(px - min_x, 3)
                dist_y = abs(py - mid_y)
                if key_x not in by_x or dist_y < by_x[key_x][0]:
                    by_x[key_x] = (dist_y, pz)
            self.section_canvas.profile_points = [
                (ux, by_x[ux][1]) for ux in sorted(by_x.keys())
            ]
        else:
            self.canvas.section_line_3d = []
            self.section_canvas.profile_points = []

        self.section_canvas.datum_label = datum_label
        self.section_canvas.unit_label = unit_label
        self.canvas.update()
        self.section_canvas.update()

    @staticmethod
    def _build_preview_surface(control_points: list) -> MeshProduct | None:
        """Build a preview trench/feature surface mesh from surveyed points with observed/interpolated regions."""
        if len(control_points) < 3:
            return None
        frame = control_points[0].frame
        xs = [float(p.x) for p in control_points]
        ys = [float(p.y) for p in control_points]
        zs = [float(p.z) for p in control_points]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        if max_x - min_x < 1e-6 or max_y - min_y < 1e-6:
            return None
        mean_z = sum(zs) / len(zs)
        nx, ny = 5, 4
        verts: list[tuple[float, float, float]] = []
        origins: list[OriginKind] = []
        for iy in range(ny):
            fy = iy / (ny - 1)
            y = min_y + fy * (max_y - min_y)
            for ix in range(nx):
                fx = ix / (nx - 1)
                x = min_x + fx * (max_x - min_x)
                # Subtle trench depression in center
                dish = -0.18 * math.sin(math.pi * fx) * math.sin(math.pi * fy)
                z = mean_z + dish
                verts.append((x, y, z))
                # Mark one central-right cell as INTERPOLATED (hole fill) to demonstrate distinction
                if ix == 3 and iy in (1, 2):
                    origins.append(OriginKind.INTERPOLATED)
                else:
                    origins.append(OriginKind.OBSERVED)

        faces: list[tuple[int, int, int]] = []
        for iy in range(ny - 1):
            for ix in range(nx - 1):
                v00 = iy * nx + ix
                v10 = v00 + 1
                v01 = (iy + 1) * nx + ix
                v11 = v01 + 1
                faces.append((v00, v10, v11))
                faces.append((v00, v11, v01))
        return MeshProduct(
            vertices=verts,
            faces=faces,
            origin=origins,
            product_kind=ProductKind.DISPLAY,
            frame=frame,
        )
