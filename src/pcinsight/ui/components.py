"""Reusable UI building blocks shared by every page."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)


def _label(text: str, name: str = "", wrap: bool = True) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.title_label = _label(title, "PageTitle", wrap=False)
        lay.addWidget(self.title_label)
        if subtitle:
            lay.addWidget(_label(subtitle, "Muted"))


class EmptyState(QFrame):
    """Honest placeholder shown instead of fabricated data."""

    def __init__(self, title: str, message: str, badge: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("EmptyPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 32, 32, 32)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if badge:
            b = _label(badge, "Badge", wrap=False)
            b.setAlignment(Qt.AlignmentFlag.AlignCenter)
            b.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            lay.addWidget(b, alignment=Qt.AlignmentFlag.AlignCenter)
        t = _label(title, "EmptyTitle")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        m = _label(message, "Muted")
        m.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        lay.addWidget(m)


class InfoCard(QFrame):
    """Dashboard card. Shows only real collected values or an honest status."""

    def __init__(self, title: str, description: str, status: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumHeight(130)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(6)
        lay.addWidget(_label(title, "CardTitle"))
        self.description_label = _label(description, "Muted")
        lay.addWidget(self.description_label)
        self.summary_label = _label("", "Summary")
        self.summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary_label.setVisible(False)
        lay.addWidget(self.summary_label)
        lay.addStretch()
        self.status_label = _label(status, "Badge", wrap=False)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        lay.addWidget(self.status_label)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_summary(self, text: str | None) -> None:
        self.summary_label.setText(text or "")
        self.summary_label.setVisible(bool(text))
        self.description_label.setVisible(not text)


class ReflowGrid(QWidget):
    """Grid whose column count adapts to the available width."""

    def __init__(self, min_col_width: int = 300, parent: QWidget | None = None):
        super().__init__(parent)
        self._min = min_col_width
        self._items: list[QWidget] = []
        self._cols = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(16)

    def add(self, w: QWidget) -> None:
        self._items.append(w)
        self._relayout(max(self._cols, 1))

    @property
    def columns(self) -> int:
        return self._cols

    def _relayout(self, cols: int) -> None:
        self._cols = cols
        for w in self._items:
            self._grid.removeWidget(w)
        for i, w in enumerate(self._items):
            self._grid.addWidget(w, i // cols, i % cols)
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)

    def resizeEvent(self, e) -> None:  # noqa: N802 (Qt API)
        cols = max(1, self.width() // (self._min + self._grid.spacing()))
        if cols != self._cols:
            self._relayout(cols)
        super().resizeEvent(e)


class ScanStatusBar(QFrame):
    """Scan timestamp, progress indicator and rescan button (wired up in Module 2)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ScanBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        self.status_label = _label("Last scan: never", "Muted", wrap=False)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setVisible(False)
        self.progress.setFixedWidth(160)
        self.rescan_button = QPushButton("Scan now")
        self.rescan_button.setObjectName("Primary")
        self.rescan_button.setEnabled(False)
        self.rescan_button.setToolTip("Scanning is added in Module 2.")
        lay.addWidget(self.status_label, 1)
        lay.addWidget(self.progress)
        lay.addWidget(self.rescan_button)


class FieldTable(QFrame):
    """Label / value / copy rows. Distinguishes real values, blank values and unavailable data."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(18, 14, 18, 14)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(14)
        self._grid.setColumnStretch(1, 1)
        self.copy_buttons: dict[str, QPushButton] = {}
        self.value_labels: dict[str, QLabel] = {}

    def clear(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.copy_buttons.clear()
        self.value_labels.clear()

    def set_fields(self, fields) -> None:
        from ..core.models import Status
        self.clear()
        for row, f in enumerate(fields):
            label = _label(f.label, "FieldLabel")
            label.setMinimumWidth(160)
            label.setAlignment(Qt.AlignmentFlag.AlignTop)
            if f.status is Status.OK:
                text, name = f.value or "", ""
            elif f.status is Status.EMPTY:
                text, name = "Reported as empty", "ValueMissing"
            else:
                text, name = "Unavailable", "ValueMissing"
            value = _label(text, name)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            detail_text = f"Source: {f.source}" + (f"  \u00b7  {f.note}" if f.note else "")
            detail = _label(detail_text, "Detail")
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(2)
            bl.addWidget(value)
            bl.addWidget(detail)
            btn = QPushButton("Copy")
            btn.setObjectName("Ghost")
            btn.setAccessibleName(f"Copy {f.label}")
            btn.setEnabled(f.status is Status.OK)
            if f.status is Status.OK:
                btn.clicked.connect(lambda _=False, b=btn, t=f.value or "": self._copy(b, t))
            self._grid.addWidget(label, row, 0, Qt.AlignmentFlag.AlignTop)
            self._grid.addWidget(box, row, 1)
            self._grid.addWidget(btn, row, 2, Qt.AlignmentFlag.AlignTop)
            self.copy_buttons[f.key] = btn
            self.value_labels[f.key] = value

    @staticmethod
    def _copy(button: QPushButton, text: str) -> None:
        QApplication.clipboard().setText(text)
        button.setText("Copied")

        def reset() -> None:
            try:
                button.setText("Copy")
            except RuntimeError:  # button was replaced by a newer scan
                pass
        QTimer.singleShot(1200, reset)
