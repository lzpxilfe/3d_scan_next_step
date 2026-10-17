"""Validate the hand-made SVG icon assets. SYNTHETIC only.

Checks each icon is well-formed SVG XML with a viewBox and a stroke-based style,
so broken asset files never reach the GUI.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

ICONS = Path(__file__).resolve().parent.parent / "assets" / "icons"

EXPECTED = {
    "photos.svg",
    "camera.svg",
    "control.svg",
    "measure.svg",
    "stitch.svg",
    "section.svg",
    "mesh.svg",
    "validate.svg",
    "export.svg",
}


def test_expected_icons_exist() -> None:
    present = {p.name for p in ICONS.glob("*.svg")}
    assert EXPECTED <= present


def test_icons_are_wellformed_svg() -> None:
    for name in EXPECTED:
        root = ET.parse(ICONS / name).getroot()  # raises if malformed
        assert root.tag.endswith("svg"), name
        assert root.get("viewBox") == "0 0 24 24", name
        assert root.get("stroke") == "currentColor", name
