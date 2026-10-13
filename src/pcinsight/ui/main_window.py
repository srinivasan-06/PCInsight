"""Main window: sidebar navigation, scan status bar and stacked pages."""
from __future__ import annotations

from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ..core.models import format_timestamp
from ..core.connectivity import run_connectivity_checks
from ..core.scan import run_scan
from ..version import APP_NAME
from .scan_controller import ScanController
from .components import ScanStatusBar
from .pages import build_pages
from .theme import THEMES, build_stylesheet


class MainWindow(QMainWindow):
    def __init__(self, theme: str = "light", scan_fn=None, connectivity_fn=None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)
        self.setMinimumSize(820, 560)
        self.theme_name = theme
        self.controller = ScanController(scan_fn or run_scan, self)
        self._gateways: list[str] = []
        self.connectivity_controller = ScanController(
            connectivity_fn or (lambda: run_connectivity_checks(list(self._gateways))), self)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        # Sidebar
        self.sidebar = QWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(220)
        sl = QVBoxLayout(self.sidebar)
        sl.setContentsMargins(0, 20, 0, 16)
        sl.setSpacing(2)
        brand = QLabel(APP_NAME); brand.setObjectName("Brand")
        sub = QLabel("PC hardware & network analyzer"); sub.setObjectName("BrandSub")
        brand.setContentsMargins(16, 0, 16, 0); sub.setContentsMargins(16, 0, 16, 14)
        sl.addWidget(brand); sl.addWidget(sub)

        # Content
        content = QWidget(); content.setObjectName("Content")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(28, 24, 28, 24)
        cl.setSpacing(16)
        self.scan_bar = ScanStatusBar()
        self.stack = QStackedWidget()
        cl.addWidget(self.scan_bar)
        cl.addWidget(self.stack, 1)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        self.pages: dict[str, QWidget] = {}
        for i, (name, page) in enumerate(build_pages()):
            self.pages[name] = page
            self.stack.addWidget(page)
            btn = QPushButton(name)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setAccessibleName(f"Navigate to {name}")
            btn.clicked.connect(lambda _=False, idx=i: self.stack.setCurrentIndex(idx))
            self.nav_group.addButton(btn)
            self.nav_buttons.append(btn)
            sl.addWidget(btn)
        self.nav_buttons[0].setChecked(True)

        sl.addStretch()
        self.theme_button = QPushButton()
        self.theme_button.setObjectName("ThemeButton")
        self.theme_button.clicked.connect(self.toggle_theme)
        wrap = QVBoxLayout(); wrap.setContentsMargins(16, 0, 16, 0); wrap.addWidget(self.theme_button)
        sl.addLayout(wrap)

        row.addWidget(self.sidebar)
        row.addWidget(content, 1)
        self.scan_bar.rescan_button.setEnabled(True)
        self.scan_bar.rescan_button.setToolTip("Collect fresh data from this computer.")
        self.scan_bar.rescan_button.clicked.connect(self.controller.start)
        self.controller.scan_started.connect(self._on_scan_started)
        self.controller.scan_finished.connect(self._on_scan_finished)
        self.controller.scan_failed.connect(self._on_scan_failed)
        net = self.pages["Network"]
        net.run_button.clicked.connect(self.connectivity_controller.start)
        self.connectivity_controller.scan_started.connect(net.set_connectivity_running)
        self.connectivity_controller.scan_finished.connect(net.show_connectivity)
        self.connectivity_controller.scan_failed.connect(net.set_connectivity_failed)
        self.apply_theme(theme)

    def _on_scan_started(self) -> None:
        self.scan_bar.rescan_button.setEnabled(False)
        self.scan_bar.progress.setVisible(True)
        self.scan_bar.status_label.setText("Scanning\u2026")
        self.pages["Dashboard"].set_scanning()

    def _on_scan_finished(self, result) -> None:
        self.scan_bar.progress.setVisible(False)
        self.scan_bar.rescan_button.setEnabled(True)
        self.scan_bar.rescan_button.setText("Rescan")
        text = f"Last scan: {format_timestamp(result.scanned_at)}"
        errors = getattr(result, "errors", [])
        if errors:
            text += f"  \u00b7  {len(errors)} problem(s): " + "; ".join(errors)
        self.scan_bar.status_label.setText(text)
        self.pages["Dashboard"].show_result(result)
        self.pages["Hardware"].show_result(result)
        self.pages["Network"].show_result(result)
        self.pages["Port Analyzer"].show_result(result)
        self._gateways = list(getattr(result, "gateways", []))

    def _on_scan_failed(self, message: str) -> None:
        self.scan_bar.progress.setVisible(False)
        self.scan_bar.rescan_button.setEnabled(True)
        self.scan_bar.status_label.setText(f"Scan failed: {message}. Previous results (if any) are still shown.")
        self.pages["Dashboard"].system_card.set_status("Scan failed")

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        self.controller.shutdown()
        self.connectivity_controller.shutdown()
        super().closeEvent(event)

    def apply_theme(self, name: str) -> None:
        self.theme_name = name
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_stylesheet(THEMES[name]))
        self.theme_button.setText("Switch to dark theme" if name == "light" else "Switch to light theme")

    def toggle_theme(self) -> None:
        self.apply_theme("dark" if self.theme_name == "light" else "light")
