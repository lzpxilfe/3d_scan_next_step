"""Icon loading: hand-made SVG icons -> Qt QIcon.

Icons live in ``assets/icons`` as framework-agnostic SVG (see that folder's
README). This maps a logical name (e.g. ``"stitch"``) to its SVG and wraps it in
a ``QIcon`` for use on QActions / QToolButtons. The SVGs use ``currentColor`` so
they follow the theme.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon

ICONS_DIR = Path(__file__).resolve().parents[3] / "assets" / "icons"


def icon_path(name: str) -> Path:
    return ICONS_DIR / f"{name}.svg"


def icon(name: str) -> QIcon:
    """Return a QIcon for the named SVG asset."""
    p = icon_path(name)
    if not p.exists():
        raise FileNotFoundError(f"icon asset not found: {p}")
    return QIcon(str(p))
