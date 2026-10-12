"""Pages for each navigation item."""
from __future__ import annotations

import platform
import sys

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import qVersion
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from ..core.models import Status, format_timestamp
from ..core.scan import ScanResult
from ..version import APP_NAME, __version__
from .components import EmptyState, FieldTable, InfoCard, PageHeader, ReflowGrid

NOT_SCANNED = "Not scanned yet"


def _scroll(inner: QWidget) -> QScrollArea:
    inner.setObjectName("ScrollInner")
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(inner)
    return scroll


class PlaceholderPage(QWidget):
    def __init__(self, title: str, subtitle: str, empty_title: str, empty_message: str, badge: str):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(20)
        lay.addWidget(PageHeader(title, subtitle))
        lay.addWidget(EmptyState(empty_title, empty_message, badge), 1)


class DashboardPage(QWidget):
    # (title, description, implementing module)
    CARDS = [
        ("System", "Computer name, Windows version, manufacturer, uptime.", 2),
        ("CPU & Motherboard", "Processor, cores, motherboard and BIOS details.", 3),
        ("Memory", "Installed RAM and memory modules.", 4),
        ("Graphics", "GPU model, driver and video memory.", 4),
        ("Storage", "Drives, capacity and free space.", 4),
        ("Network", "Adapters, addresses, gateway and DNS.", 5),
        ("Listening Ports", "Local TCP listeners and UDP endpoints.", 6),
    ]

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(20)
        self.subtitle = "An overview of this computer. Press \"Scan now\" to collect real data."
        outer.addWidget(PageHeader("Dashboard", self.subtitle))
        self.grid = ReflowGrid(min_col_width=280)
        self.cards: list[InfoCard] = []
        self._modules: list[int] = []
        for title, desc, module in self.CARDS:
            card = InfoCard(title, desc, NOT_SCANNED)
            self.cards.append(card)
            self._modules.append(module)
            self.grid.add(card)
        self.system_card = self.cards[0]
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 4, 0)
        il.addWidget(self.grid)
        il.addStretch()
        outer.addWidget(_scroll(inner), 1)

    def set_scanning(self) -> None:
        self.system_card.set_status("Scanning\u2026")
        self.cards[1].set_status("Scanning\u2026")

    def show_result(self, result: ScanResult) -> None:
        ov = result.system
        lines = []
        for key in ("computer_name", "os_edition", "uptime"):
            f = ov.get(key)
            if f and f.status is Status.OK:
                lines.append(f"Up {f.value}" if key == "uptime" else f.value)
        build = ov.get("os_build")
        if build and build.status is Status.OK and len(lines) > 1:
            lines[1] += f" (build {build.value})"
        self.system_card.set_summary("\n".join(lines) if lines else None)
        n = ov.unavailable_count
        self.system_card.set_status("Scanned" if n == 0 else f"Partial data ({n} unavailable)")
        self._show_cpu_card(result)
        for card, module in zip(self.cards[2:], self._modules[2:]):
            card.set_status(f"Not available yet (Module {module})")

    def _show_cpu_card(self, result: ScanResult) -> None:
        card = self.cards[1]
        secs = [result.section(k) for k in ("cpu", "motherboard", "bios")]
        secs = [x for x in secs if x is not None]
        if not secs:
            card.set_summary(None)
            card.set_status("Not collected")
            return
        cpu = result.section("cpu")
        lines = []
        name = cpu.get("cpu_name") if cpu else None
        if name and name.status is Status.OK:
            lines.append(name.value)
        cores, threads = (cpu.get("physical_cores"), cpu.get("logical_processors")) if cpu else (None, None)
        if cores and threads and cores.status is Status.OK and threads.status is Status.OK:
            lines.append(f"{cores.value} cores / {threads.value} threads")
        board = result.section("motherboard")
        model = board.get("board_model") if board else None
        if model and model.status is Status.OK:
            lines.append(f"Board: {model.value}")
        card.set_summary("\n".join(lines) if lines else None)
        n = sum(x.unavailable_count for x in secs)
        card.set_status("Scanned" if n == 0 else f"Partial data ({n} unavailable)")


class HardwarePage(QWidget):
    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(20)
        outer.addWidget(PageHeader("Hardware", "System, CPU, motherboard, BIOS, memory, GPU and storage."))
        self.empty = EmptyState(
            "No hardware data yet",
            "Press \"Scan now\" to read information from this computer. "
            "Memory, GPU and storage sections arrive in Module 4.", NOT_SCANNED)
        outer.addWidget(self.empty, 1)

        self.content = QWidget()
        self._cl = QVBoxLayout(self.content)
        self._cl.setContentsMargins(0, 0, 4, 0)
        self._cl.setSpacing(10)
        self.tables: dict[str, FieldTable] = {}
        self.scroll = _scroll(self.content)
        self.scroll.setVisible(False)
        outer.addWidget(self.scroll, 1)

    @property
    def table(self) -> FieldTable:
        """The System table (kept for Module 2 compatibility)."""
        return self.tables["system"]

    @property
    def has_data(self) -> bool:
        return self.scroll.isVisibleTo(self)

    def _clear(self) -> None:
        while self._cl.count():
            item = self._cl.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.tables.clear()

    def _add_section(self, key: str, title: str, fields, note: str = "") -> None:
        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        heading.setContentsMargins(0, 8, 0, 0)
        self._cl.addWidget(heading)
        if note:
            n = QLabel(note)
            n.setObjectName("Muted")
            n.setWordWrap(True)
            self._cl.addWidget(n)
        table = FieldTable()
        table.set_fields(fields)
        self.tables[key] = table
        self._cl.addWidget(table)

    def show_result(self, result: ScanResult) -> None:
        self._clear()
        collected = QLabel(f"Collected {format_timestamp(result.scanned_at)}")
        collected.setObjectName("Muted")
        self._cl.addWidget(collected)
        self._add_section("system", "System", result.system.fields)
        for sec in result.hardware:
            self._add_section(sec.key, sec.title, sec.fields, sec.note)
        for err in result.errors:
            e = QLabel(f"\u26a0 {err}")
            e.setObjectName("Muted")
            e.setWordWrap(True)
            self._cl.addWidget(e)
        legend = QLabel(
            "Values come from the Windows registry and, where needed, Windows CIM (PowerShell). "
            "\"Unavailable\" means this app could not retrieve the value; it does not mean the "
            "component is absent. \"Reported as empty\" means Windows answered with a blank value. "
            "\"Not exposed by Windows\" means no supported interface exists, so nothing is guessed.")
        legend.setObjectName("Muted")
        legend.setWordWrap(True)
        self._cl.addWidget(legend)
        self._cl.addStretch()
        self.empty.setVisible(False)
        self.scroll.setVisible(True)


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
        ("Hardware", HardwarePage()),
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
