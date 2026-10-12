"""Main window: sidebar navigation, scan status bar and stacked pages."""
from __future__ import annotations

from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ..version import APP_NAME
from .components import ScanStatusBar
from .pages import build_pages
from .theme import THEMES, build_stylesheet


class MainWindow(QMainWindow):
    def __init__(self, theme: str = "light"):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)
        self.setMinimumSize(820, 560)
        self.theme_name = theme

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
        self.apply_theme(theme)

    def apply_theme(self, name: str) -> None:
        self.theme_name = name
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_stylesheet(THEMES[name]))
        self.theme_button.setText("Switch to dark theme" if name == "light" else "Switch to light theme")

    def toggle_theme(self) -> None:
        self.apply_theme("dark" if self.theme_name == "light" else "light")
