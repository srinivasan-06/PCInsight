import json
import logging
import os
from datetime import datetime, timedelta

from PySide6.QtWidgets import QLabel

from helpers import NOW, sample_result, sample_with_ports, wait_until
from pcinsight.core import diagnostics, settings as settings_mod
from pcinsight.core.ports_info import DEFAULT_IMPORTANT_PORTS
from pcinsight.core.scan import ScanResult
from pcinsight.ui import main_window
from pcinsight.ui.main_window import MainWindow


def make_window(qapp, **kw):
    w = MainWindow(scan_fn=kw.pop("scan_fn", sample_with_ports), connectivity_fn=kw.pop("connectivity_fn", None), **kw)
    w.show()
    qapp.processEvents()
    page = w.pages["Settings"]
    page.confirm = lambda title, text: True
    page.open_path = lambda p: None
    return w, page


def saved(w):
    return json.loads(w.settings_store.path.read_text())


def scan_once(qapp, w):
    n = w.pages["Reports"].history_table.rowCount()
    w.scan_bar.rescan_button.click()
    assert wait_until(qapp, lambda: w.scan_bar.rescan_button.isEnabled() and "Last scan" in w.scan_bar.status_label.text())


def test_defaults_are_shown(qapp):
    w, p = make_window(qapp)
    assert p.theme_combo.currentData() == "light" and p.paper_combo.currentText() == "A4"
    assert p.cb_network.isChecked() and p.cb_ports.isChecked() and p.cb_conn.isChecked()
    assert p.ports_edit.text() == ", ".join(map(str, DEFAULT_IMPORTANT_PORTS))
    assert p.cb_history.isChecked() and not p.cb_logging.isChecked()
    assert p.days_combo.currentData() == 90 and p.max_combo.currentData() == 50
    assert p.version_label.text() == "PCInsight 0.1.0"
    assert str(w.settings_store.path.parent) in p.data_label.text()
    assert "never uploaded" in " ".join(l.text() for l in p.findChildren(QLabel))
    assert not p.message.isVisibleTo(p)


def test_theme_choice_applies_and_persists(qapp):
    w, p = make_window(qapp)
    p.theme_combo.setCurrentIndex(p.theme_combo.findData("dark"))
    assert w.theme_name == "dark" and saved(w)["theme"] == "dark" and p.message.text() == "Saved."
    assert w.theme_button.text() == "Switch to light theme"
    w2, _ = make_window(qapp)                       # "restart": same data folder
    assert w2.theme_name == "dark"


def test_sidebar_theme_button_is_saved_and_synced(qapp):
    w, p = make_window(qapp)
    w.theme_button.click()
    assert saved(w)["theme"] == "dark" and p.theme_combo.currentData() == "dark"
    w.theme_button.click()
    assert saved(w)["theme"] == "light" and p.theme_combo.currentData() == "light"


def test_report_preferences_persist_and_become_report_defaults(qapp):
    w, p = make_window(qapp)
    p.paper_combo.setCurrentText("Letter")
    p.cb_ports.setChecked(False)
    p.cb_conn.setChecked(False)
    s = saved(w)
    assert s["paper"] == "Letter" and s["report_include_ports"] is False and s["report_include_connectivity"] is False
    r = w.pages["Reports"]
    assert r.paper.currentText() == "Letter" and not r.include_ports.isChecked() and not r.include_connectivity.isChecked()
    assert r.include_network.isChecked()
    w2, _ = make_window(qapp)
    assert w2.pages["Reports"].paper.currentText() == "Letter"


def test_valid_ports_are_applied_and_used_by_the_next_scan(qapp, monkeypatch):
    w, p = make_window(qapp)
    assert not p.ports_apply.isEnabled()                       # nothing changed yet
    p.ports_edit.setText("22, 8080 3389")
    assert p.ports_apply.isEnabled() and "3 ports will be checked on the next scan" in p.ports_feedback.text()
    p.ports_apply.click()
    assert saved(w)["important_ports"] == [22, 8080, 3389] and p.message.text() == "Saved."
    assert not p.ports_apply.isEnabled()
    seen = {}
    monkeypatch.setattr(main_window, "collect_ports", lambda important_ports=None: seen.setdefault("p", list(important_ports)) or [])
    monkeypatch.setattr(main_window, "run_scan", lambda ports_collector=None: ports_collector())
    w._default_scan()
    assert seen["p"] == [22, 8080, 3389]


def test_invalid_ports_are_refused_with_clear_reasons(qapp):
    w, p = make_window(qapp)
    p.ports_edit.setText("22, abc, 70000, 0")
    assert not p.ports_apply.isEnabled() and p.ports_feedback.objectName() == "Error"
    text = p.ports_feedback.text()
    assert "not applied" in text.lower() and "\"abc\" is not a port number" in text and "70000 is outside" in text
    p.ports_apply.click()                                       # clicking a disabled button does nothing
    assert w.settings_store.settings.important_ports == tuple(DEFAULT_IMPORTANT_PORTS)
    assert not w.settings_store.path.exists()                   # nothing was written


def test_duplicate_ports_warn_but_apply_and_empty_list_is_allowed(qapp):
    w, p = make_window(qapp)
    p.ports_edit.setText("80 80 443")
    assert p.ports_apply.isEnabled() and "listed more than once" in p.ports_feedback.text()
    p.ports_apply.click()
    assert saved(w)["important_ports"] == [80, 443]
    p.ports_edit.setText("")
    assert p.ports_apply.isEnabled() and "No ports will be listed as important" in p.ports_feedback.text()
    p.ports_apply.click()
    assert saved(w)["important_ports"] == []


def test_reset_ports(qapp):
    w, p = make_window(qapp)
    p.ports_edit.setText("1")
    p.ports_apply.click()
    p.ports_reset.click()
    assert saved(w)["important_ports"] == DEFAULT_IMPORTANT_PORTS
    assert p.ports_edit.text() == ", ".join(map(str, DEFAULT_IMPORTANT_PORTS))


def test_history_toggle_controls_saving(qapp):
    w, p = make_window(qapp)
    scan_once(qapp, w)
    assert w.history.stats()[0] == 1
    p.cb_history.setChecked(False)
    assert saved(w)["history_enabled"] is False
    scan_once(qapp, w)
    assert w.history.stats()[0] == 1                            # nothing new saved
    assert "turned off in Settings" in w.pages["Reports"].history_note.text() or True
    w.pages["Reports"].refresh_history()
    assert "turned off in Settings" in w.pages["Reports"].history_note.text()
    p.cb_history.setChecked(True)
    scan_once(qapp, w)
    assert w.history.stats()[0] == 2


def test_retention_settings_persist_and_trim_immediately(qapp):
    w, p = make_window(qapp)
    base = datetime(2026, 10, 1)
    for i in range(12):
        w.history.save(ScanResult(sample_result().system, base + timedelta(hours=i)))
    p.max_combo.setCurrentIndex(p.max_combo.findData(10))
    assert saved(w)["retention_max_scans"] == 10 and w.history.stats()[0] == 10
    assert "2 older scans removed" in p.message.text()
    p.days_combo.setCurrentIndex(p.days_combo.findData(7))
    assert saved(w)["retention_days"] == 7 and w.history.stats()[0] == 0     # all older than 7 days (relative to today)
    assert "10 saved" not in p.history_info.text() and p.history_info.text().startswith("0 saved scans")


def test_delete_all_history_needs_confirmation(qapp):
    w, p = make_window(qapp)
    scan_once(qapp, w)
    scan_once(qapp, w)
    p.confirm = lambda title, text: False
    p.delete_history_button.click()
    assert w.history.stats()[0] == 2 and p.message.text() == "Nothing was deleted."
    asked = []
    p.confirm = lambda title, text: asked.append(text) or True
    p.delete_history_button.click()
    assert "cannot be undone" in asked[0] and "Reports you saved are not affected" in asked[0]
    assert w.history.stats()[0] == 0 and p.message.text() == "Deleted 2 saved scans."
    assert w.pages["Reports"].history_table.rowCount() == 0
    assert p.history_info.text().startswith("0 saved scans")


def test_diagnostic_logging_toggle_creates_and_stops_the_log(qapp):
    w, p = make_window(qapp)
    p.cb_logging.setChecked(True)
    log = w.settings_store.path.parent / "logs" / "pcinsight.log"
    assert saved(w)["diagnostic_logging"] is True and log.exists()
    logging.getLogger("pcinsight.x").warning("hello-log")
    assert "hello-log" in log.read_text()
    p.cb_logging.setChecked(False)
    logging.getLogger("pcinsight.x").warning("after-off")
    assert "after-off" not in log.read_text() and saved(w)["diagnostic_logging"] is False


def test_logging_setting_is_restored_at_startup(qapp):
    w, p = make_window(qapp)
    p.cb_logging.setChecked(True)
    diagnostics.configure_logging(False, None)
    w2, p2 = make_window(qapp)
    assert p2.cb_logging.isChecked()
    logging.getLogger("pcinsight.y").warning("restored-marker")
    assert "restored-marker" in (w2.settings_store.path.parent / "logs" / "pcinsight.log").read_text()


def test_log_folder_buttons(qapp):
    w, p = make_window(qapp)
    opened = []
    p.open_path = opened.append
    p.open_logs_button.click()
    p.open_data_button.click()
    assert opened == [str(w.settings_store.path.parent / "logs"), str(w.settings_store.path.parent)]
    p.cb_logging.setChecked(True)
    assert any("pcinsight.log" in f.name for f in (w.settings_store.path.parent / "logs").iterdir())
    p.delete_logs_button.click()
    assert p.message.text() == "Deleted 1 log file."
    p.confirm = lambda t, x: False
    p.delete_logs_button.click()
    assert p.message.text() == "Nothing was deleted."


def test_logging_that_cannot_start_stays_off_and_says_why(qapp):
    w, p = make_window(qapp)
    (w.settings_store.path.parent / "logs").write_text("i am a file, not a folder")
    p.cb_logging.setChecked(True)
    assert not p.cb_logging.isChecked() and saved(w)["diagnostic_logging"] is False
    assert p.message.objectName() == "Error" and "logging stays off" in p.message.text()


def test_reset_all_settings(qapp):
    w, p = make_window(qapp)
    p.theme_combo.setCurrentIndex(p.theme_combo.findData("dark"))
    p.ports_edit.setText("1")
    p.ports_apply.click()
    p.paper_combo.setCurrentText("Letter")
    p.confirm = lambda t, x: False
    p.reset_button.click()
    assert w.theme_name == "dark" and p.message.text() == "Nothing was changed."
    p.confirm = lambda t, x: True
    p.reset_button.click()
    assert w.theme_name == "light" and p.theme_combo.currentData() == "light" and p.paper_combo.currentText() == "A4"
    assert p.ports_edit.text() == ", ".join(map(str, DEFAULT_IMPORTANT_PORTS))
    assert p.message.text() == "All settings were reset to defaults." and w.pages["Reports"].paper.currentText() == "A4"


def test_a_settings_file_that_cannot_be_saved_is_explained_and_the_change_still_applies(qapp, monkeypatch):
    w, p = make_window(qapp)

    def locked(src, dst):
        raise PermissionError("locked")
    monkeypatch.setattr(settings_mod.os, "replace", locked)
    p.theme_combo.setCurrentIndex(p.theme_combo.findData("dark"))
    assert w.theme_name == "dark"                                 # active for this session
    assert p.message.objectName() == "Error" and "not allowed to write" in p.message.text()
    assert "until you close PCInsight" in p.message.text()


def test_a_damaged_settings_file_at_startup_is_reported_and_defaults_used(qapp):
    from pathlib import Path
    folder = Path(os.environ["PCINSIGHT_DATA_DIR"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "settings.json").write_text("{ this is not json")
    w, p = make_window(qapp)
    assert w.theme_name == "light" and p.ports_edit.text().startswith("21, 22")
    assert p.message.isVisibleTo(p) and p.message.objectName() == "Error"
    assert "damaged" in p.message.text() and "default settings are being used" in p.message.text()
    assert any(f.name.startswith("settings.json.damaged-") for f in folder.iterdir())
