"""Application entry point."""
from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow
from .version import APP_NAME, __version__


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    window = MainWindow()
    window.show()
    return app.exec()
