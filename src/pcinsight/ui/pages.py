"""Pages for each navigation item."""
from __future__ import annotations

import platform
import sys

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import qVersion
from PySide6.QtWidgets import QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget

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


def _val(sec, key: str) -> "str | None":
    f = sec.get(key) if sec else None
    return f.value if f is not None and f.status is Status.OK else None


class DashboardPage(QWidget):
    # (title, description, implementing module, section-key prefixes shown on the card)
    CARDS = [
        ("System", "Computer name, Windows version, manufacturer, uptime.", 2, ()),
        ("CPU & Motherboard", "Processor, cores, motherboard and BIOS details.", 3, ("cpu", "motherboard", "bios")),
        ("Memory", "Installed RAM and memory modules.", 4, ("memory",)),
        ("Graphics", "GPU model, driver and video memory.", 4, ("gpu",)),
        ("Storage", "Drives, capacity and free space.", 4, ("storage", "volumes")),
        ("Network", "Adapters, addresses, gateway and DNS.", 5, ()),
        ("Listening Ports", "Local TCP listeners and UDP endpoints.", 6, ()),
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
        for title, desc, _module, _prefixes in self.CARDS:
            card = InfoCard(title, desc, NOT_SCANNED)
            self.cards.append(card)
            self.grid.add(card)
        self.system_card = self.cards[0]
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 4, 0)
        il.addWidget(self.grid)
        il.addStretch()
        outer.addWidget(_scroll(inner), 1)

    def set_scanning(self) -> None:
        for card, (_t, _d, _m, prefixes) in zip(self.cards, self.CARDS):
            if card is self.system_card or prefixes:
                card.set_status("Scanning\u2026")

    def show_result(self, result: ScanResult) -> None:
        self._show_system(result)
        summaries = {1: self._cpu_lines, 2: self._memory_lines, 3: self._gpu_lines, 4: self._storage_lines}
        for idx, (_t, _d, module, prefixes) in enumerate(self.CARDS):
            card = self.cards[idx]
            if idx == 0:
                continue
            if not prefixes:
                card.set_summary(None)
                card.set_status(f"Not available yet (Module {module})")
                continue
            secs = result.sections_for(*prefixes)
            if not secs:
                card.set_summary(None)
                card.set_status("Not collected")
                continue
            lines = summaries[idx](result)
            card.set_summary("\n".join(lines) if lines else None)
            n = sum(x.unavailable_count for x in secs)
            card.set_status("Scanned" if n == 0 else f"Partial data ({n} unavailable)")

    def _show_system(self, result: ScanResult) -> None:
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

    @staticmethod
    def _cpu_lines(result: ScanResult) -> list[str]:
        cpu, board = result.section("cpu"), result.section("motherboard")
        lines = [v for v in (_val(cpu, "cpu_name"),) if v]
        cores, threads = _val(cpu, "physical_cores"), _val(cpu, "logical_processors")
        if cores and threads:
            lines.append(f"{cores} cores / {threads} threads")
        if _val(board, "board_model"):
            lines.append(f"Board: {_val(board, 'board_model')}")
        return lines

    @staticmethod
    def _memory_lines(result: ScanResult) -> list[str]:
        mem = result.section("memory")
        total, installed = _val(mem, "total_physical"), _val(mem, "installed")
        lines = []
        if total:
            lines.append(f"{total} usable" + (f" ({installed} installed)" if installed else ""))
        used, slots = _val(mem, "slots_used"), _val(mem, "slots_total")
        if used and slots:
            lines.append(f"{used} of {slots} slots populated")
        types = sorted({t for sec in result.sections_for("memory") if (t := _val(sec, "type"))})
        if types:
            lines.append(", ".join(types))
        return lines

    @staticmethod
    def _gpu_lines(result: ScanResult) -> list[str]:
        names = [n for sec in result.sections_for("gpu") if (n := _val(sec, "gpu_name"))]
        lines = names[:3]
        if len(names) > 3:
            lines.append(f"+{len(names) - 3} more")
        return lines

    @staticmethod
    def _storage_lines(result: ScanResult) -> list[str]:
        disks = []
        for sec in result.sections_for("storage"):
            model, cap = _val(sec, "model"), _val(sec, "capacity")
            if model:
                disks.append(f"{model} ({cap})" if cap else model)
        lines = disks[:3]
        if len(disks) > 3:
            lines.append(f"+{len(disks) - 3} more")
        vols = result.section("volumes")
        if vols:
            ok = sum(1 for f in vols.fields if f.status is Status.OK)
            if ok:
                lines.append(f"{ok} drive{'s' if ok != 1 else ''} with free-space data")
        return lines


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
            "You will see system, CPU, motherboard, BIOS, memory, graphics and storage details.", NOT_SCANNED)
        outer.addWidget(self.empty, 1)

        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("Search")
        self.filter_edit.setPlaceholderText("Filter results (e.g. GPU, SSD, driver, DDR4)\u2026")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setAccessibleName("Filter hardware results")
        self.filter_edit.setVisible(False)
        self.filter_edit.textChanged.connect(self._apply_filter)
        outer.addWidget(self.filter_edit)
        self.no_match = QLabel("No rows match this filter.")
        self.no_match.setObjectName("Muted")
        self.no_match.setVisible(False)
        outer.addWidget(self.no_match)

        self.content = QWidget()
        self._cl = QVBoxLayout(self.content)
        self._cl.setContentsMargins(0, 0, 4, 0)
        self._cl.setSpacing(10)
        self.tables: dict[str, FieldTable] = {}
        self._section_widgets: dict[str, list[QWidget]] = {}
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
        self._section_widgets.clear()

    def _apply_filter(self, text: str) -> None:
        total = 0
        for key, table in self.tables.items():
            shown = table.apply_filter(text)
            total += shown
            for w in self._section_widgets[key]:
                w.setVisible(shown > 0 or not text.strip())
            table.setVisible(shown > 0 or not text.strip())
        self.no_match.setVisible(bool(text.strip()) and total == 0 and bool(self.tables))

    def _add_section(self, key: str, title: str, fields, note: str = "") -> None:
        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        heading.setContentsMargins(0, 8, 0, 0)
        self._cl.addWidget(heading)
        extras: list[QWidget] = [heading]
        if note:
            n = QLabel(note)
            n.setObjectName("Muted")
            n.setWordWrap(True)
            self._cl.addWidget(n)
            extras.append(n)
        table = FieldTable()
        table.set_fields(fields)
        self.tables[key] = table
        self._section_widgets[key] = extras
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
        self.filter_edit.setVisible(True)
        self._apply_filter(self.filter_edit.text())


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
