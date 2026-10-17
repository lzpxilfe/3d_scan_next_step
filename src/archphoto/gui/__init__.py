"""User interface layer (PySide6 / Qt).

The GUI is a thin presentation layer over the core packages (recon, mesh,
quality, archaeo). Framework: PySide6 (DECISIONS D-2026-10-12-08). Requires
PySide6 installed to import/run. Icons are hand-made SVGs in ``assets/icons``.
"""

from archphoto.gui.main_window import MainWindow

__all__ = ["MainWindow"]
