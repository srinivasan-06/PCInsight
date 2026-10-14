"""Settings page. Every control applies immediately and is saved; nothing needs an 'OK' button except the
port list (which is validated first)."""
from __future__ import annotations

import platform
import sys

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import Qt, Signal, qVersion
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..core.common import format_bytes
from ..core.diagnostics import configure_logging, delete_log_files, log_files
from ..core.history import HistoryError, HistoryStore
from ..core.ports_info import DEFAULT_IMPORTANT_PORTS
from ..core.settings import PAPERS, RETENTION_DAYS_CHOICES, RETENTION_MAX_CHOICES, SettingsStore, parse_port_list
from ..version import APP_NAME, __version__
from .components import PageHeader
from .dialogs import ask_confirmation, open_path

DAYS_LABELS = {7: "7 days", 30: "30 days", 90: "90 days", 365: "1 year", 0: "Forever"}


def _label(text: str, name: str = "", wrap: bool = True) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


class SettingsPage(QWidget):
    theme_changed = Signal(str)
    settings_changed = Signal()
    history_changed = Signal()

    def __init__(self, store: SettingsStore, history: HistoryStore):
        super().__init__()
        self.store, self.history = store, history
        self.log_dir = store.path.parent / "logs"
        self.confirm = ask_confirmation          # replaceable (tests)
        self.open_path = open_path               # replaceable (tests)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(16)
        outer.addWidget(PageHeader("Settings", "Changes are saved automatically and stay on this PC."))
        self.message = _label("")
        self.message.setVisible(False)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        outer.addWidget(self.message)

        inner = QWidget()
        inner.setObjectName("ScrollInner")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(16)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        # -- Appearance ---------------------------------------------------------------------------------
        card, cl = self._card("Appearance")
        row = QHBoxLayout()
        row.addWidget(QLabel("Theme"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Light", "light")
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.setAccessibleName("Theme")
        row.addWidget(self.theme_combo)
        row.addStretch()
        cl.addLayout(row)
        lay.addWidget(card)

        # -- Report preferences --------------------------------------------------------------------------
        card, cl = self._card("Report preferences", "Defaults for new PDF reports. You can still change them for "
                                                     "a single report on the Reports page.")
        row = QHBoxLayout()
        row.addWidget(QLabel("Paper size"))
        self.paper_combo = QComboBox()
        self.paper_combo.addItems(PAPERS)
        self.paper_combo.setAccessibleName("Default paper size")
        row.addWidget(self.paper_combo)
        row.addStretch()
        cl.addLayout(row)
        self.cb_network = QCheckBox("Include network configuration")
        self.cb_ports = QCheckBox("Include local listening ports")
        self.cb_conn = QCheckBox("Include connectivity test results (when they were run)")
        for cb in (self.cb_network, self.cb_ports, self.cb_conn):
            cl.addWidget(cb)
        lay.addWidget(card)

        # -- Important ports --------------------------------------------------------------------------------
        card, cl = self._card("Important ports", "The Port Analyzer reports on these TCP ports first. Not every port "
                                                  "is expected to be open. Use port numbers 1-65535 separated by "
                                                  "commas or spaces. Changes apply to the next scan.")
        self.ports_edit = QLineEdit()
        self.ports_edit.setObjectName("Search")
        self.ports_edit.setAccessibleName("Important ports")
        cl.addWidget(self.ports_edit)
        self.ports_feedback = _label("")
        cl.addWidget(self.ports_feedback)
        row = QHBoxLayout()
        self.ports_apply = QPushButton("Apply ports")
        self.ports_apply.setObjectName("Primary")
        self.ports_reset = QPushButton("Reset to defaults")
        self.ports_reset.setObjectName("Ghost")
        row.addWidget(self.ports_apply)
        row.addWidget(self.ports_reset)
        row.addStretch()
        cl.addLayout(row)
        lay.addWidget(card)

        # -- Scan history ---------------------------------------------------------------------------------------
        card, cl = self._card("Scan history and data retention",
                              "PCInsight can keep a local history of your scans so you can reopen an old scan or "
                              "make a report from it. It is stored only on this PC, never uploaded.")
        self.cb_history = QCheckBox("Save a local history of scans")
        cl.addWidget(self.cb_history)
        cl.addWidget(_label("Turning this off stops saving new scans; scans already saved stay until you delete them.",
                            "Muted"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Keep scans for"))
        self.days_combo = QComboBox()
        for d in RETENTION_DAYS_CHOICES:
            self.days_combo.addItem(DAYS_LABELS[d], d)
        self.days_combo.setAccessibleName("Keep scans for")
        row.addWidget(self.days_combo)
        row.addWidget(QLabel("and at most"))
        self.max_combo = QComboBox()
        for m in RETENTION_MAX_CHOICES:
            self.max_combo.addItem(f"{m} scans", m)
        self.max_combo.setAccessibleName("Maximum number of saved scans")
        row.addWidget(self.max_combo)
        row.addStretch()
        cl.addLayout(row)
        self.history_info = _label("")
        self.history_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cl.addWidget(self.history_info)
        self.delete_history_button = QPushButton("Delete all saved scans\u2026")
        self.delete_history_button.setObjectName("Ghost")
        cl.addWidget(self.delete_history_button, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(card)

        # -- Diagnostics ------------------------------------------------------------------------------------------
        card, cl = self._card("Diagnostics", "An optional log file helps find problems. It records which parts of a "
                                              "scan failed and why, and is designed not to record IP addresses, MAC "
                                              "addresses or device names. Review it before sharing it.")
        self.cb_logging = QCheckBox("Write a diagnostic log file")
        cl.addWidget(self.cb_logging)
        row = QHBoxLayout()
        self.open_logs_button = QPushButton("Open log folder")
        self.open_logs_button.setObjectName("Ghost")
        self.delete_logs_button = QPushButton("Delete log files")
        self.delete_logs_button.setObjectName("Ghost")
        row.addWidget(self.open_logs_button)
        row.addWidget(self.delete_logs_button)
        row.addStretch()
        cl.addLayout(row)
        lay.addWidget(card)

        # -- Application ---------------------------------------------------------------------------------------------
        card, cl = self._card("About this installation")
        self.version_label = _label(f"{APP_NAME} {__version__}", "Value")
        cl.addWidget(self.version_label)
        cl.addWidget(_label(f"Python {sys.version.split()[0]}  |  PySide6 {pyside_version}  |  Qt {qVersion()}  |  "
                            f"{platform.system()}", "Muted"))
        self.data_label = _label(f"Your settings, scan history and logs are kept in: {store.path.parent}", "Muted")
        self.data_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cl.addWidget(self.data_label)
        cl.addWidget(_label("Privacy: scan results are never uploaded. PCInsight sends network traffic only when you "
                            "press \"Run connectivity tests\".", "Muted"))
        row = QHBoxLayout()
        self.open_data_button = QPushButton("Open data folder")
        self.open_data_button.setObjectName("Ghost")
        self.reset_button = QPushButton("Reset all settings\u2026")
        self.reset_button.setObjectName("Ghost")
        row.addWidget(self.open_data_button)
        row.addWidget(self.reset_button)
        row.addStretch()
        cl.addLayout(row)
        lay.addWidget(card)
        lay.addStretch()

        self.refresh()
        self._connect()
        if store.load_warning:
            self._show(store.load_warning, "Error")

    # -- building helpers -------------------------------------------------------------------------------------------
    @staticmethod
    def _card(title: str, description: str = "") -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("Card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        lay.addWidget(_label(title, "SectionTitle"))
        if description:
            lay.addWidget(_label(description, "Muted"))
        return frame, lay

    def _show(self, text: str, kind: str = "Muted") -> None:
        self.message.setObjectName(kind)
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self.message.setText(text)
        self.message.setVisible(bool(text))

    def _connect(self) -> None:
        self.theme_combo.currentIndexChanged.connect(self._on_theme)
        self.paper_combo.currentIndexChanged.connect(self._on_report_prefs)
        for cb in (self.cb_network, self.cb_ports, self.cb_conn):
            cb.toggled.connect(self._on_report_prefs)
        self.ports_edit.textChanged.connect(self._validate_ports)
        self.ports_apply.clicked.connect(self._apply_ports)
        self.ports_reset.clicked.connect(self._reset_ports)
        self.cb_history.toggled.connect(self._on_history_enabled)
        self.days_combo.currentIndexChanged.connect(self._on_retention)
        self.max_combo.currentIndexChanged.connect(self._on_retention)
        self.delete_history_button.clicked.connect(self._delete_history)
        self.cb_logging.toggled.connect(self._on_logging)
        self.open_logs_button.clicked.connect(self._open_logs)
        self.delete_logs_button.clicked.connect(self._delete_logs)
        self.open_data_button.clicked.connect(lambda: self._open_folder(self.store.path.parent))
        self.reset_button.clicked.connect(self._reset_all)

    # -- sync controls with the stored settings --------------------------------------------------------------------
    def refresh(self) -> None:
        s = self.store.settings
        widgets = (self.theme_combo, self.paper_combo, self.cb_network, self.cb_ports, self.cb_conn, self.cb_history,
                   self.days_combo, self.max_combo, self.cb_logging, self.ports_edit)
        for w in widgets:
            w.blockSignals(True)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(s.theme))
        self.paper_combo.setCurrentText(s.paper)
        self.cb_network.setChecked(s.report_include_network)
        self.cb_ports.setChecked(s.report_include_ports)
        self.cb_conn.setChecked(s.report_include_connectivity)
        self.cb_history.setChecked(s.history_enabled)
        self.days_combo.setCurrentIndex(self.days_combo.findData(s.retention_days))
        self.max_combo.setCurrentIndex(self.max_combo.findData(s.retention_max_scans))
        self.cb_logging.setChecked(s.diagnostic_logging)
        self.ports_edit.setText(", ".join(map(str, s.important_ports)))
        for w in widgets:
            w.blockSignals(False)
        self._validate_ports()
        self.refresh_history_info()

    def refresh_history_info(self) -> None:
        try:
            count, size = self.history.stats()
            text = (f"{count} saved scan{'s' if count != 1 else ''} \u00b7 {format_bytes(size)} \u00b7 "
                    f"{self.history.path}")
            if self.history.recovery_message:
                self._show(self.history.recovery_message, "Error")
        except HistoryError as exc:
            text = f"Scan history is not available: {exc}"
        self.history_info.setText(text)

    def _saved(self, ok: bool) -> None:
        if ok:
            self._show("Saved.", "Success")
        else:
            self._show(self.store.last_error, "Error")

    # -- handlers ----------------------------------------------------------------------------------------------------------
    def _on_theme(self) -> None:
        name = self.theme_combo.currentData()
        self._saved(self.store.update(theme=name))
        self.theme_changed.emit(name)

    def _on_report_prefs(self) -> None:
        ok = self.store.update(paper=self.paper_combo.currentText(), report_include_network=self.cb_network.isChecked(),
                               report_include_ports=self.cb_ports.isChecked(),
                               report_include_connectivity=self.cb_conn.isChecked())
        self._saved(ok)
        self.settings_changed.emit()

    def _validate_ports(self) -> None:
        ports, errors, warnings = parse_port_list(self.ports_edit.text())
        current = list(self.store.settings.important_ports)
        if errors:
            self.ports_feedback.setObjectName("Error")
            self.ports_feedback.setText("Not applied: " + "; ".join(errors) + ".")
        else:
            self.ports_feedback.setObjectName("Muted")
            note = f"{len(ports)} port{'s' if len(ports) != 1 else ''} will be checked on the next scan."
            if not ports:
                note = "No ports will be listed as important (all listening ports are still shown)."
            self.ports_feedback.setText(note + (" " + "; ".join(warnings) + "." if warnings else ""))
        self.ports_feedback.style().unpolish(self.ports_feedback)
        self.ports_feedback.style().polish(self.ports_feedback)
        self.ports_apply.setEnabled(not errors and ports != current)

    def _apply_ports(self) -> None:
        ports, errors, _ = parse_port_list(self.ports_edit.text())
        if errors:
            return
        self._saved(self.store.update(important_ports=ports))
        self.settings_changed.emit()
        self._validate_ports()

    def _reset_ports(self) -> None:
        self._saved(self.store.update(important_ports=list(DEFAULT_IMPORTANT_PORTS)))
        self.refresh()
        self.settings_changed.emit()

    def _on_history_enabled(self, checked: bool) -> None:
        self._saved(self.store.update(history_enabled=checked))

    def _on_retention(self) -> None:
        days, most = self.days_combo.currentData(), self.max_combo.currentData()
        ok = self.store.update(retention_days=days, retention_max_scans=most)
        try:
            removed = self.history.apply_retention(days, most)
        except HistoryError as exc:
            self._show(f"Saved, but the history could not be trimmed: {exc}" if ok else self.store.last_error, "Error")
        else:
            if not ok:
                self._show(self.store.last_error, "Error")
            elif removed:
                self._show(f"Saved. {removed} older scan{'s' if removed != 1 else ''} removed to match the new limits.",
                           "Success")
            else:
                self._show("Saved.", "Success")
        self.refresh_history_info()
        self.history_changed.emit()

    def _delete_history(self) -> None:
        if not self.confirm("Delete scan history", "Delete ALL saved scans? They are removed permanently from this "
                                                    "PC and this cannot be undone. Reports you saved are not affected."):
            self._show("Nothing was deleted.", "Muted")
            return
        try:
            n = self.history.delete_all()
            self._show(f"Deleted {n} saved scan{'s' if n != 1 else ''}.", "Success")
        except HistoryError as exc:
            self._show(f"Could not delete the history: {exc}", "Error")
        self.refresh_history_info()
        self.history_changed.emit()

    def _on_logging(self, checked: bool) -> None:
        try:
            configure_logging(checked, self.log_dir)
        except OSError as exc:
            configure_logging(False, None)
            self.store.update(diagnostic_logging=False)
            self.cb_logging.blockSignals(True)
            self.cb_logging.setChecked(False)
            self.cb_logging.blockSignals(False)
            self._show(f"The log file could not be created ({type(exc).__name__}), so logging stays off.", "Error")
            return
        self._saved(self.store.update(diagnostic_logging=checked))

    def _open_folder(self, folder) -> None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._show(f"The folder could not be opened ({type(exc).__name__}).", "Error")
            return
        self.open_path(str(folder))

    def _open_logs(self) -> None:
        self._open_folder(self.log_dir)

    def _delete_logs(self) -> None:
        if not self.confirm("Delete log files", "Delete all PCInsight diagnostic log files?"):
            self._show("Nothing was deleted.", "Muted")
            return
        n = delete_log_files(self.log_dir)
        self._show(f"Deleted {n} log file{'s' if n != 1 else ''}." if n else "There were no log files to delete.",
                   "Success" if n else "Muted")

    def _reset_all(self) -> None:
        if not self.confirm("Reset settings", "Reset ALL settings to their defaults? Your saved scans and reports "
                                              "are not affected."):
            self._show("Nothing was changed.", "Muted")
            return
        ok = self.store.reset()
        configure_logging(self.store.settings.diagnostic_logging, self.log_dir)
        self.refresh()
        self._show("All settings were reset to defaults." if ok else self.store.last_error, "Success" if ok else "Error")
        self.theme_changed.emit(self.store.settings.theme)
        self.settings_changed.emit()
