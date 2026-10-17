"""Icon loading: hand-made SVG icons -> Qt QIcon.

Icons live in ``assets/icons`` as framework-agnostic SVG (see that folder's
README). This maps a logical name (e.g. ``"stitch"``) to its SVG and wraps it in
a ``QIcon`` for use on QActions / QToolButtons. The SVGs use ``currentColor`` so
they follow the theme.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QIcon, QPixmap

ICONS_DIR = Path(__file__).resolve().parents[3] / "assets" / "icons"


def icon_path(name: str) -> Path:
    return ICONS_DIR / f"{name}.svg"


def icon(name: str, color: str = "#7dd3fc") -> QIcon:
    """Return a QIcon for the named SVG asset, tinted for the dark workstation theme."""
    p = icon_path(name)
    if not p.exists():
        raise FileNotFoundError(f"icon asset not found: {p}")
    svg_text = p.read_text(encoding="utf-8").replace("currentColor", color)
    pixmap = QPixmap()
    if pixmap.loadFromData(QByteArray(svg_text.encode("utf-8")), "SVG"):
        return QIcon(pixmap)
    return QIcon(str(p))

