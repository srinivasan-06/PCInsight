"""Pages for each navigation item. Module 1: structure and empty states only."""
from __future__ import annotations

import platform
import sys

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import qVersion
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from ..version import APP_NAME, __version__
from .components import EmptyState, InfoCard, PageHeader, ReflowGrid

NOT_SCANNED = "Not scanned yet"


class PlaceholderPage(QWidget):
    def __init__(self, title: str, subtitle: str, empty_title: str, empty_message: str, badge: str):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(20)
        lay.addWidget(PageHeader(title, subtitle))
        lay.addWidget(EmptyState(empty_title, empty_message, badge), 1)


class DashboardPage(QWidget):
    CARDS = [
        ("System", "Computer name, Windows version, manufacturer, uptime."),
        ("CPU & Motherboard", "Processor, cores, motherboard and BIOS details."),
        ("Memory", "Installed RAM and memory modules."),
        ("Graphics", "GPU model, driver and video memory."),
        ("Storage", "Drives, capacity and free space."),
        ("Network", "Adapters, addresses, gateway and DNS."),
        ("Listening Ports", "Local TCP listeners and UDP endpoints."),
    ]

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(20)
        outer.addWidget(PageHeader(
            "Dashboard",
            "An overview of this computer. No scan has been run, so no data is shown."))
        self.grid = ReflowGrid(min_col_width=280)
        self.cards: list[InfoCard] = []
        for title, desc in self.CARDS:
            card = InfoCard(title, desc, NOT_SCANNED)
            self.cards.append(card)
            self.grid.add(card)
        inner = QWidget()
        inner.setObjectName("ScrollInner")
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 4, 0)
        il.addWidget(self.grid)
        il.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)


class AboutPage(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(20)
        lay.addWidget(PageHeader("About", "Version and runtime information."))
        info = (f"{APP_NAME} {__version__}\n"
                f"Python {sys.version.split()[0]}  |  PySide6 {pyside_version}  |  Qt {qVersion()}\n"
                f"Platform: {platform.platform()}")
        lay.addWidget(EmptyState(f"{APP_NAME} {__version__}", info, "Development build"), 1)


def build_pages() -> list[tuple[str, QWidget]]:
    return [
        ("Dashboard", DashboardPage()),
        ("Hardware", PlaceholderPage(
            "Hardware", "CPU, motherboard, BIOS, memory, GPU and storage.",
            "No hardware data yet",
            "Hardware detection arrives in Modules 2-4. Nothing is shown until real data is collected.",
            "Coming in Modules 2-4")),
        ("Network", PlaceholderPage(
            "Network", "Adapters, addresses, gateway, DNS and connectivity checks.",
            "No network data yet",
            "Network inspection arrives in Module 5.", "Coming in Module 5")),
        ("Port Analyzer", PlaceholderPage(
            "Port Analyzer", "Local listening TCP ports and UDP endpoints on this computer only.",
            "No port data yet",
            "The local port analyzer arrives in Module 6.", "Coming in Module 6")),
        ("Reports", PlaceholderPage(
            "Reports", "Export scan results as a PDF report.",
            "No report available",
            "PDF reports arrive in Module 7 and need a completed scan.", "Coming in Module 7")),
        ("Settings", PlaceholderPage(
            "Settings", "Theme, report preferences, important ports and data retention.",
            "Settings not available yet",
            "Settings arrive in Module 8. Use the theme button in the sidebar for now.",
            "Coming in Module 8")),
        ("About", AboutPage()),
    ]
