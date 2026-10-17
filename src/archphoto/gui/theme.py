"""Dark workstation theme and 5-stage process stepper bar for archphoto GUI.

Designed for archaeological photogrammetry and metric survey work:
- Neutral dark-gray canvas (#13161c ~ #1b1f27) prevents brightness/color cast bias
  when inspecting soil stratigraphy, stone texture, Munsell charts, and markers.
- Semantic color coding for GCP (#38bdf8), Check Points (#fb923c), Observed
  surfaces (#2dd4bf), and Interpolated hole-filled surfaces (#f43f5e).
- Process-driven 5-stage workflow stepper guides the user from coordinate frame
  definition through photo ingest, sub-pixel pinning, registration & independent
  validation, to section/ortho/mesh export.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
     QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

WORKSTATION_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #14171f;
    color: #e2e8f0;
    font-size: 12px;
}
QToolBar {
    background-color: #0f1218;
    border-bottom: 1px solid #262c3a;
    spacing: 6px;
    padding: 4px 8px;
}
QToolBar QToolButton {
    background-color: #1b202b;
    color: #e2e8f0;
    border: 1px solid #2b3242;
    border-radius: 5px;
    padding: 5px 10px;
    font-weight: 600;
}
QToolBar QToolButton:hover {
    background-color: #252d3d;
    border-color: #38bdf8;
}
QDockWidget {
    color: #cbd5e1;
    font-weight: 700;
    titlebar-close-icon: url(none);
    titlebar-normal-icon: url(none);
}
QDockWidget::title {
    background-color: #1b202b;
    border: 1px solid #283040;
    padding: 6px 10px;
    text-align: left;
}
QTabWidget::pane {
    border: 1px solid #283040;
    background-color: #161a23;
}
QTabBar::tab {
    background-color: #1a1f29;
    color: #94a3b8;
    border: 1px solid #283040;
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    padding: 6px 14px;
    margin-right: 2px;
    font-weight: 600;
}
QTabBar::tab:selected {
    background-color: #0284c7;
    color: #ffffff;
    border-color: #38bdf8;
}
QTabBar::tab:hover:!selected {
    background-color: #242b38;
    color: #e2e8f0;
}
QLineEdit, QComboBox, QPlainTextEdit, QListWidget, QTableWidget, QTreeWidget {
    background-color: #1c222d;
    color: #f1f5f9;
    border: 1px solid #2e3748;
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: #0369a1;
    selection-color: #ffffff;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #38bdf8;
}
QHeaderView::section {
    background-color: #1e2532;
    color: #94a3b8;
    border: 1px solid #2b3344;
    padding: 4px 6px;
    font-weight: 700;
}
QPushButton {
    background-color: #232a38;
    color: #e2e8f0;
    border: 1px solid #333d52;
    border-radius: 5px;
    padding: 5px 10px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #2d3748;
    border-color: #38bdf8;
}
QPushButton:pressed {
    background-color: #0369a1;
}
QPushButton#primaryActionButton {
    background-color: #0284c7;
    color: #ffffff;
    border: 1px solid #38bdf8;
}
QPushButton#primaryActionButton:hover {
    background-color: #0369a1;
}
QPushButton#presetButton {
    background-color: #1b2432;
    color: #7dd3fc;
    border: 1px solid #0369a1;
    padding: 3px 8px;
    font-size: 11px;
}
QStatusBar {
    background-color: #0f1218;
    color: #cbd5e1;
    border-top: 1px solid #262c3a;
}
"""


PROCESS_STAGES = [
    ("stage_frame", "1. 현장·좌표계", "CRS · 높이 기준 설정"),
    ("stage_photos", "2. 사진·무결성", "원본 등록 · 해시 검증"),
    ("stage_pinning", "3. 기준점·피닝", "GCP/검증점 · 8× 루페"),
    ("stage_validate", "4. 정합·독립검증", "RANSAC · 잔차 평가"),
    ("stage_deliver", "5. 단면·산출물", "3D 실측 · 단면 · 내보내기"),
]


class WorkflowStepperBar(QFrame):
    """5-stage process navigation header showing workflow progress and honesty gates."""

    stage_clicked = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workflowStepperBar")
        self.setStyleSheet(
            "#workflowStepperBar { background-color: #11151d; border-bottom: 1px solid #283040; }"
        )
        outer = QHBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 6)
        outer.setSpacing(8)

        self._cards: dict[str, QPushButton] = {}
        self._badges: dict[str, QLabel] = {}
        self._active_stage: str = "stage_frame"

        for key, title, subtitle in PROCESS_STAGES:
            card = QPushButton(self)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setMinimumHeight(48)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 5, 10, 5)
            card_layout.setSpacing(2)

            top_row = QHBoxLayout()
            top_row.setSpacing(6)
            title_lbl = QLabel(title, card)
            title_lbl.setStyleSheet(
                "color: #f1f5f9; font-weight: 700; font-size: 12px; background: transparent;"
            )
            badge_lbl = QLabel("대기", card)
            badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge_lbl.setStyleSheet(
                "background-color: #262f3f; color: #94a3b8; border-radius: 3px; "
                "padding: 1px 6px; font-size: 10px; font-weight: 700;"
            )
            top_row.addWidget(title_lbl)
            top_row.addStretch(1)
            top_row.addWidget(badge_lbl)

            sub_lbl = QLabel(subtitle, card)
            sub_lbl.setStyleSheet("color: #94a3b8; font-size: 10px; background: transparent;")

            card_layout.addLayout(top_row)
            card_layout.addWidget(sub_lbl)

            card.clicked.connect(lambda _=False, k=key: self._on_click(k))
            outer.addWidget(card, 1)
            self._cards[key] = card
            self._badges[key] = badge_lbl

        self._refresh_card_styles()

    def _on_click(self, key: str) -> None:
        self.set_active_stage(key)
        self.stage_clicked.emit(key)

    def set_active_stage(self, key: str) -> None:
        if key in self._cards:
            self._active_stage = key
            self._refresh_card_styles()

    def active_stage(self) -> str:
        return self._active_stage

    def update_stage_status(self, key: str, badge_text: str, tone: str = "neutral") -> None:
        """Update stage pill text and semantic tone ('neutral', 'active', 'ok', 'warn', 'error')."""
        badge = self._badges.get(key)
        if badge is None:
            return
        badge.setText(badge_text)
        palette = {
            "neutral": ("#262f3f", "#94a3b8"),
            "active": ("#0369a1", "#e0f2fe"),
            "ok": ("#065f46", "#6ee7b7"),
            "warn": ("#78350f", "#fde68a"),
            "error": ("#7f1d1d", "#fecaca"),
        }
        bg, fg = palette.get(tone, palette["neutral"])
        badge.setStyleSheet(
            f"background-color: {bg}; color: {fg}; border-radius: 3px; "
            "padding: 1px 6px; font-size: 10px; font-weight: 700;"
        )

    def _refresh_card_styles(self) -> None:
        for key, card in self._cards.items():
            if key == self._active_stage:
                card.setStyleSheet(
                    "QPushButton { background-color: #1e293b; border: 1px solid #38bdf8; border-radius: 6px; }"
                )
            else:
                card.setStyleSheet(
                    "QPushButton { background-color: #161b24; border: 1px solid #262e3d; border-radius: 6px; }"
                    "QPushButton:hover { background-color: #1c2330; border-color: #475569; }"
                )
