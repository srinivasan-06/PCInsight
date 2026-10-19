"""Pages for each navigation item."""
from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QStandardPaths, Qt, QUrl, Signal, qVersion
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QScrollArea,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.common import format_bytes
from ..core.history import HistoryError, HistoryStore
from ..core.models import Status, format_timestamp
from ..core.settings import SettingsStore
from ..core.scan import ScanResult
from ..report import ReportError, ReportOptions, default_report_filename, write_report
from ..version import APP_NAME, __version__
from .dialogs import ask_confirmation
from .scan_controller import ScanController
from .settings_page import SettingsPage
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
        ("Network", "Adapters, addresses, gateway and DNS.", 5, ("network", "net")),
        ("Listening Ports", "Local TCP listeners and UDP endpoints.", 6, ("ports",)),
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
        summaries = {1: self._cpu_lines, 2: self._memory_lines, 3: self._gpu_lines, 4: self._storage_lines,
                     5: self._network_lines, 6: self._ports_lines}
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
            if idx in (5, 6):  # "empty" is normal here (no gateway on an unplugged adapter, no listeners): count real failures only
                n = sum(1 for x in secs for f in x.fields if f.status is Status.UNAVAILABLE)
            else:
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
    def _network_lines(result: ScanResult) -> list[str]:
        overview = result.section("network")
        lines = [v for v in (_val(overview, "adapters"),) if v]
        shown = 0
        for sec in result.sections_for("net"):
            status, ip = _val(sec, "status"), _val(sec, "ipv4")
            if not (status and status.startswith("Up") and ip) or "self-assigned" in ip.splitlines()[0]:
                continue
            name = sec.title.split(" \u2014 ")[0]
            first_ip = ip.splitlines()[0].split(" \u00b7 ")[0]
            lines.append(f"{name}: {first_ip}")
            shown += 1
            if shown == 3:
                break
        return lines

    @staticmethod
    def _ports_lines(result: ScanResult) -> list[str]:
        ov = result.section("ports")
        tcp, udp, imp = _val(ov, "tcp_count"), _val(ov, "udp_count"), _val(ov, "important")
        lines = []
        if tcp and udp:
            lines.append(f"{tcp} TCP listeners \u00b7 {udp} UDP endpoints")
        if imp:
            lines.append(f"Important ports: {imp}")
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


class SectionsPage(QWidget):
    """Reusable page: header, filter box and a scrolling list of titled FieldTable sections."""

    def __init__(self, title: str, subtitle: str, empty_title: str, empty_message: str, badge: str,
                 filter_placeholder: str):
        super().__init__()
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(0, 0, 0, 0)
        self.outer.setSpacing(20)
        self.outer.addWidget(PageHeader(title, subtitle))
        self.empty = EmptyState(empty_title, empty_message, badge)
        self.outer.addWidget(self.empty, 1)

        self.filter_edit = QLineEdit()
        self.filter_edit.setObjectName("Search")
        self.filter_edit.setPlaceholderText(filter_placeholder)
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setAccessibleName(f"Filter {title.lower()} results")
        self.filter_edit.setVisible(False)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.outer.addWidget(self.filter_edit)
        self.no_match = QLabel("No rows match this filter.")
        self.no_match.setObjectName("Muted")
        self.no_match.setVisible(False)
        self.outer.addWidget(self.no_match)

        self.content = QWidget()
        self._cl = QVBoxLayout(self.content)
        self._cl.setContentsMargins(0, 0, 4, 0)
        self._cl.setSpacing(10)
        self.tables: dict[str, FieldTable] = {}
        self._section_widgets: dict[str, list[QWidget]] = {}
        self.scroll = _scroll(self.content)
        self.scroll.setVisible(False)
        self.outer.addWidget(self.scroll, 1)

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
        heading.setWordWrap(True)
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

    def render(self, header_lines: list[str], sections, errors: list[str], legend: str) -> None:
        """sections: iterable of (key, title, fields, note)."""
        self._clear()
        for line in header_lines:
            lab = QLabel(line)
            lab.setObjectName("Muted")
            self._cl.addWidget(lab)
        for key, title, fields, note in sections:
            self._add_section(key, title, fields, note)
        for err in errors:
            e = QLabel(f"\u26a0 {err}")
            e.setObjectName("Muted")
            e.setWordWrap(True)
            self._cl.addWidget(e)
        if legend:
            lg = QLabel(legend)
            lg.setObjectName("Muted")
            lg.setWordWrap(True)
            self._cl.addWidget(lg)
        self._cl.addStretch()
        self.empty.setVisible(False)
        self.scroll.setVisible(True)
        self.filter_edit.setVisible(True)
        self._apply_filter(self.filter_edit.text())


LEGEND = ("Values come from the Windows registry, Windows networking/CIM (PowerShell) and psutil. "
          "\"Unavailable\" means this app could not retrieve the value; it does not mean the component is "
          "absent. \"Reported as empty\" means Windows answered with a blank value or none. "
          "\"Not exposed by Windows\" means no supported interface exists, so nothing is guessed.")


class HardwarePage(SectionsPage):
    def __init__(self):
        super().__init__(
            "Hardware", "System, CPU, motherboard, BIOS, memory, GPU and storage.",
            "No hardware data yet",
            "Press \"Scan now\" to read information from this computer. "
            "You will see system, CPU, motherboard, BIOS, memory, graphics and storage details.", NOT_SCANNED,
            "Filter results (e.g. GPU, SSD, driver, DDR4)\u2026")

    @property
    def table(self) -> FieldTable:
        """The System table (kept for Module 2 compatibility)."""
        return self.tables["system"]

    def show_result(self, result: ScanResult) -> None:
        skip = {id(x) for x in result.network_sections() + result.ports_sections()}
        sections = [("system", "System", result.system.fields, "")]
        sections += [(x.key, x.title, x.fields, x.note) for x in result.hardware if id(x) not in skip]
        self.render([f"Collected {format_timestamp(result.scanned_at)}"], sections, result.errors, LEGEND)


PORTS_LEGEND = ("Statuses: \"Listening locally\" = a program on this PC is waiting for connections on that port "
                "(not proof that other computers can reach it). \"No local listener detected\" = nothing on this PC is "
                "listening on that TCP port (not proof it is closed from outside). \"Process details unavailable\" = "
                "Windows would not tell us which program owns the port. \"UDP endpoint detected; remote reachability "
                "not verified\" = a UDP socket exists; UDP has no open/closed state.")


class PortsPage(SectionsPage):
    def __init__(self):
        super().__init__(
            "Port Analyzer", "Programs listening for network connections on this computer. Other computers are never scanned.",
            "No port data yet",
            "Press \"Scan now\" to list the TCP listeners and UDP endpoints on this computer. "
            "Nothing is sent to other computers and nothing on your PC is changed.", NOT_SCANNED,
            "Filter ports (e.g. 445, svchost, loopback, UDP)\u2026")

    def show_result(self, result: ScanResult) -> None:
        sections = [(x.key, x.title, x.fields, x.note) for x in result.ports_sections()]
        errors = [e for e in result.errors if e.startswith("Listening ports")]
        header = f"Collected {format_timestamp(result.scanned_at)}  \u00b7  this computer only"
        if not sections:
            # Never leave the previous scan's ports on screen under a newer scan (they could be out of date, or the
            # collector may have failed this time). Say plainly that this scan has no port data.
            header = f"No port data was collected in the scan from {format_timestamp(result.scanned_at)}."
        self.render([header], sections, errors, PORTS_LEGEND)


class NetworkPage(SectionsPage):
    """Local configuration (from the scan) plus optional, user-started connectivity tests."""

    def __init__(self):
        super().__init__(
            "Network", "Adapters, addresses, gateway, DNS and optional connectivity tests.",
            "No network data yet",
            "Press \"Scan now\" to read this computer's network configuration. Connectivity tests are started "
            "separately with the button above.", NOT_SCANNED,
            "Filter results (e.g. Wi-Fi, gateway, DHCP, IPv6)\u2026")
        self._scan: ScanResult | None = None
        self._connectivity = None
        bar = QFrame()
        bar.setObjectName("ScanBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 10, 16, 10)
        self.connectivity_label = QLabel("Connectivity tests: not run yet. They send small network probes only when you press the button.")
        self.connectivity_label.setObjectName("Muted")
        self.connectivity_label.setWordWrap(True)
        self.connectivity_progress = QProgressBar()
        self.connectivity_progress.setRange(0, 0)
        self.connectivity_progress.setTextVisible(False)
        self.connectivity_progress.setFixedWidth(120)
        self.connectivity_progress.setVisible(False)
        self.run_button = QPushButton("Run connectivity tests")
        self.run_button.setObjectName("Primary")
        self.run_button.setToolTip("Pings your default gateway, tries a TCP connection to 1.1.1.1 (then 8.8.8.8) "
                                   "and looks up example.com. Nothing else is sent.")
        bl.addWidget(self.connectivity_label, 1)
        bl.addWidget(self.connectivity_progress)
        bl.addWidget(self.run_button)
        self.outer.insertWidget(1, bar)

    def show_result(self, result: ScanResult) -> None:
        self._scan = result
        self._render()

    def set_connectivity_running(self) -> None:
        self.run_button.setEnabled(False)
        self.connectivity_progress.setVisible(True)
        self.connectivity_label.setText("Running connectivity tests\u2026")

    def show_connectivity(self, res) -> None:
        self._connectivity = res
        self.run_button.setEnabled(True)
        self.connectivity_progress.setVisible(False)
        self.connectivity_label.setText(f"Connectivity tests last run: {format_timestamp(res.ran_at)}")
        self._render()

    def set_connectivity_failed(self, message: str) -> None:
        self.run_button.setEnabled(True)
        self.connectivity_progress.setVisible(False)
        self.connectivity_label.setText(f"Connectivity tests failed: {message}")

    def _render(self) -> None:
        lines, sections, errors = [], [], []
        if self._scan is not None:
            lines.append(f"Local configuration collected {format_timestamp(self._scan.scanned_at)}")
            sections += [(x.key, x.title, x.fields, x.note) for x in self._scan.network_sections()]
            errors = [e for e in self._scan.errors if e.startswith("Network")]
        else:
            lines.append("Local configuration: not collected yet (press \"Scan now\").")
        if self._connectivity is not None:
            lines.append(f"Connectivity tests run {format_timestamp(self._connectivity.ran_at)} "
                         "(separate from the configuration above)")
            sections += [(x.key, x.title, x.fields, x.note) for x in self._connectivity.sections]
        self.render(lines, sections, errors, LEGEND)


@dataclass
class ReportOutcome:
    ok: bool
    path: str = ""
    message: str = ""


def _qt_save_dialog(default_path: str) -> str:
    path, _ = QFileDialog.getSaveFileName(None, "Save PCInsight report", default_path, "PDF files (*.pdf)")
    return path


def _qt_open_path(path: str) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


class ReportsPage(QWidget):
    """Choose what to include, pick a save location, create the PDF. All saving problems are explained.
    Also lists saved scans (the local history) so an old scan can be reopened."""

    load_requested = Signal(int)

    def __init__(self, settings_store: SettingsStore | None = None, history: HistoryStore | None = None):
        super().__init__()
        self.settings_store, self.history = settings_store, history
        self.confirm = ask_confirmation             # replaceable (tests)
        self.save_dialog = _qt_save_dialog          # replaceable (tests)
        self.open_path = _qt_open_path              # replaceable (tests)
        self._result: ScanResult | None = None
        self._connectivity = None
        self._job: tuple | None = None
        self.last_path = ""
        self.controller = ScanController(self._run_job, self)
        self.controller.scan_finished.connect(self._on_done)
        self.controller.scan_failed.connect(self._on_crashed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(20)
        lay.addWidget(PageHeader("Reports", "Save the scan results as a professional PDF report."))

        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 18, 20, 18)
        cl.setSpacing(10)
        self.scan_label = QLabel("")
        self.scan_label.setObjectName("Muted")
        self.scan_label.setWordWrap(True)
        cl.addWidget(self.scan_label)
        title = QLabel("Include in the report")
        title.setObjectName("SectionTitle")
        cl.addWidget(title)
        self.include_network = QCheckBox("Network configuration")
        self.include_ports = QCheckBox("Local listening ports")
        self.include_connectivity = QCheckBox("Connectivity test results (only if you ran them)")
        for box in (self.include_network, self.include_ports, self.include_connectivity):
            box.setChecked(True)
            cl.addWidget(box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Paper size"))
        self.paper = QComboBox()
        self.paper.addItems(["A4", "Letter"])
        self.paper.setAccessibleName("Paper size")
        row.addWidget(self.paper)
        row.addStretch()
        cl.addLayout(row)
        privacy = QLabel("Reports can contain your computer name, IP addresses and MAC addresses. "
                         "They are saved only where you choose and are never uploaded.")
        privacy.setObjectName("Muted")
        privacy.setWordWrap(True)
        cl.addWidget(privacy)
        actions = QHBoxLayout()
        self.save_button = QPushButton("Save PDF report\u2026")
        self.save_button.setObjectName("Primary")
        self.save_button.clicked.connect(self._on_save_clicked)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(140)
        self.progress.setVisible(False)
        actions.addWidget(self.save_button)
        actions.addWidget(self.progress)
        actions.addStretch()
        cl.addLayout(actions)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message.setVisible(False)
        cl.addWidget(self.message)
        open_row = QHBoxLayout()
        self.open_pdf_button = QPushButton("Open PDF")
        self.open_folder_button = QPushButton("Open folder")
        for b in (self.open_pdf_button, self.open_folder_button):
            b.setObjectName("Ghost")
            b.setVisible(False)
            open_row.addWidget(b)
        open_row.addStretch()
        cl.addLayout(open_row)
        self.open_pdf_button.clicked.connect(lambda: self.open_path(self.last_path))
        self.open_folder_button.clicked.connect(lambda: self.open_path(os.path.dirname(self.last_path)))
        lay.addWidget(card)

        # -- saved scans (local history) --------------------------------------------------------------------
        hcard = QFrame()
        hcard.setObjectName("Card")
        hl = QVBoxLayout(hcard)
        hl.setContentsMargins(20, 18, 20, 18)
        hl.setSpacing(10)
        htitle = QLabel("Saved scans")
        htitle.setObjectName("SectionTitle")
        hl.addWidget(htitle)
        self.history_note = QLabel("")
        self.history_note.setObjectName("Muted")
        self.history_note.setWordWrap(True)
        hl.addWidget(self.history_note)
        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(["Scan time", "Computer", "Problems", "Size"])
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.verticalHeader().setVisible(False)
        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)   # never cut off the scan time
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.setMinimumHeight(150)
        self.history_table.setAccessibleName("Saved scans")
        self.history_table.itemSelectionChanged.connect(self._history_selection_changed)
        hl.addWidget(self.history_table)
        hrow = QHBoxLayout()
        self.load_button = QPushButton("Open selected scan")
        self.load_button.setObjectName("Primary")
        self.delete_scan_button = QPushButton("Delete selected scan")
        self.delete_scan_button.setObjectName("Ghost")
        hrow.addWidget(self.load_button)
        hrow.addWidget(self.delete_scan_button)
        hrow.addStretch()
        hl.addLayout(hrow)
        self.history_message = QLabel("")
        self.history_message.setWordWrap(True)
        self.history_message.setVisible(False)
        hl.addWidget(self.history_message)
        self.load_button.clicked.connect(self._on_open_scan)
        self.delete_scan_button.clicked.connect(self._on_delete_scan)
        lay.addWidget(hcard)
        hcard.setVisible(history is not None)
        lay.addStretch()
        self.apply_defaults()
        self.refresh_history()
        self._refresh_state()

    # -- defaults from Settings -----------------------------------------------------------------------------
    def apply_defaults(self) -> None:
        if self.settings_store is None:
            return
        s = self.settings_store.settings
        self.include_network.setChecked(s.report_include_network)
        self.include_ports.setChecked(s.report_include_ports)
        self.include_connectivity.setChecked(s.report_include_connectivity)
        self.paper.setCurrentText(s.paper)

    # -- saved scans ---------------------------------------------------------------------------------------------
    def _history_msg(self, text: str, kind: str = "Muted") -> None:
        self.history_message.setObjectName(kind)
        self.history_message.style().unpolish(self.history_message)
        self.history_message.style().polish(self.history_message)
        self.history_message.setText(text)
        self.history_message.setVisible(bool(text))

    def show_history_error(self, text: str) -> None:
        self._history_msg(text, "Error")

    def refresh_history(self) -> None:
        if self.history is None:
            return
        self.history_table.setRowCount(0)
        enabled = self.settings_store is None or self.settings_store.settings.history_enabled
        try:
            entries = self.history.list()
        except HistoryError as exc:
            self.history_note.setText(f"Scan history is not available: {exc}")
            self._history_selection_changed()
            return
        for e in entries:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            cells = [format_timestamp(e.scanned_at), e.computer or "\u2014", str(e.problems), format_bytes(e.size_bytes)]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, e.id)
                self.history_table.setItem(row, col, item)
        parts = [f"{len(entries)} saved scan{'s' if len(entries) != 1 else ''}."
                 if entries else "No saved scans yet. Each scan is saved here automatically."]
        if not enabled:
            parts.append("Saving new scans is turned off in Settings.")
        if self.history.recovery_message:
            parts.append(self.history.recovery_message)
        self.history_note.setText(" ".join(parts))
        self._history_selection_changed()

    def _selected_scan_id(self) -> "int | None":
        rows = self.history_table.selectionModel().selectedRows() if self.history_table.selectionModel() else []
        if not rows:
            return None
        return self.history_table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole)

    def _history_selection_changed(self) -> None:
        has = self._selected_scan_id() is not None
        self.load_button.setEnabled(has)
        self.delete_scan_button.setEnabled(has)

    def _on_open_scan(self) -> None:
        scan_id = self._selected_scan_id()
        if scan_id is not None:
            self._history_msg("")
            self.load_requested.emit(scan_id)

    def _on_delete_scan(self) -> None:
        scan_id = self._selected_scan_id()
        if scan_id is None or self.history is None:
            return
        if not self.confirm("Delete saved scan", "Delete this saved scan permanently? Reports you saved are not affected."):
            self._history_msg("Nothing was deleted.")
            return
        try:
            self.history.delete([scan_id])
            self._history_msg("The saved scan was deleted.", "Success")
        except HistoryError as exc:
            self._history_msg(f"Could not delete the saved scan: {exc}", "Error")
        self.refresh_history()

    # -- data from the main window ------------------------------------------------------------------------
    def set_scan(self, result: ScanResult) -> None:
        self._result = result
        self._refresh_state()

    def set_connectivity(self, res) -> None:
        self._connectivity = res
        self._refresh_state()

    def _refresh_state(self) -> None:
        running = self.controller.is_running
        if self._result is None:
            self.scan_label.setText("No scan yet. Press \"Scan now\" first; the report contains only real scan results.")
        else:
            conn = (f" Connectivity tests from {format_timestamp(self._connectivity.ran_at)} will be included."
                    if self._connectivity is not None else " Connectivity tests were not run.")
            self.scan_label.setText(f"The report will use the scan from {format_timestamp(self._result.scanned_at)}." + conn)
        self.save_button.setEnabled(self._result is not None and not running)
        self.save_button.setToolTip("" if self._result is not None else "Run a scan first.")

    def options(self) -> ReportOptions:
        return ReportOptions(paper=self.paper.currentText(), include_network=self.include_network.isChecked(),
                             include_ports=self.include_ports.isChecked(),
                             include_connectivity=self.include_connectivity.isChecked())

    # -- saving ----------------------------------------------------------------------------------------------
    def _show(self, text: str, kind: str = "") -> None:
        self.message.setObjectName(kind)
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self.message.setText(text)
        self.message.setVisible(True)

    def _on_save_clicked(self) -> None:
        if self._result is None or self.controller.is_running:
            return
        docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or os.path.expanduser("~")
        path = self.save_dialog(os.path.join(docs, default_report_filename()))
        self.open_pdf_button.setVisible(False)
        self.open_folder_button.setVisible(False)
        if not path:
            self._show("Save cancelled. No file was created.", "Muted")
            return
        self._job = (path, self._result, self._connectivity, self.options())
        self._show("Creating the report\u2026", "Muted")
        self.progress.setVisible(True)
        if self.controller.start():
            self.save_button.setEnabled(False)

    def _run_job(self) -> ReportOutcome:
        path, result, connectivity, options = self._job  # type: ignore[misc]
        try:
            return ReportOutcome(True, write_report(path, result, connectivity, options))
        except ReportError as exc:
            return ReportOutcome(False, message=str(exc))

    def _on_done(self, outcome: ReportOutcome) -> None:
        self.progress.setVisible(False)
        if outcome.ok:
            self.last_path = outcome.path
            self._show(f"Saved: {outcome.path}", "Success")
            self.open_pdf_button.setVisible(True)
            self.open_folder_button.setVisible(True)
        else:
            self._show(f"Could not save the report. {outcome.message}", "Error")
        self._refresh_state()

    def _on_crashed(self, message: str) -> None:
        self.progress.setVisible(False)
        self._show(f"Could not save the report. {message}. Nothing was saved; please try again.", "Error")
        self._refresh_state()

    def shutdown(self) -> None:
        self.controller.shutdown()


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


def build_pages(settings_store: SettingsStore | None = None,
                history: HistoryStore | None = None) -> list[tuple[str, QWidget]]:
    return [
        ("Dashboard", DashboardPage()),
        ("Hardware", HardwarePage()),
        ("Network", NetworkPage()),
        ("Port Analyzer", PortsPage()),
        ("Reports", ReportsPage(settings_store, history)),
        ("Settings", SettingsPage(settings_store or SettingsStore(), history or HistoryStore())),
        ("About", AboutPage()),
    ]
