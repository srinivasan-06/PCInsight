"""Small Qt helpers that tests can replace (so no real dialog ever blocks a test)."""
from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox


def ask_confirmation(title: str, text: str) -> bool:
    """Yes/No question; the safe answer (No) is the default."""
    answer = QMessageBox.question(None, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                  QMessageBox.StandardButton.No)
    return answer == QMessageBox.StandardButton.Yes


def open_path(path: str) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))
