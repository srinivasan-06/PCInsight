import sqlite3
import zlib
from datetime import datetime, timedelta
from pathlib import Path

import pypdf
import re

from helpers import NOW, sample_result, sample_with_ports, wait_until
from pcinsight.core.history import HistoryError, HistoryStore
from pcinsight.core.scan import ScanResult
from pcinsight.ui.main_window import MainWindow


def make_window(qapp, **kw):
    w = MainWindow(scan_fn=sample_with_ports, connectivity_fn=lambda: None, **kw)
    w.show()
    qapp.processEvents()
    r = w.pages["Reports"]
    r.confirm = lambda title, text: True
    r.open_path = lambda p: None
    return w, r


def scan(qapp, w):
    w.scan_bar.rescan_button.click()
    assert wait_until(qapp, lambda: w.scan_bar.rescan_button.isEnabled() and "Last scan" in w.scan_bar.status_label.text())


def old(hours):
    return ScanResult(sample_with_ports().system, datetime(2026, 10, 1) + timedelta(hours=hours),
                      hardware=sample_with_ports().hardware, gateways=["192.168.1.1"])


def test_each_scan_is_saved_and_listed_newest_first(qapp):
    w, r = make_window(qapp)
    assert r.history_table.rowCount() == 0 and "No saved scans yet" in r.history_note.text()
    assert not r.load_button.isEnabled() and not r.delete_scan_button.isEnabled()
    for _ in range(3):
        scan(qapp, w)
    assert r.history_table.rowCount() == 3 and r.history_note.text().startswith("3 saved scans.")
    row = [r.history_table.item(0, c).text() for c in range(4)]
    assert row[0] == "2026-10-12 12:00:00" and row[1] == "TEST-PC" and row[2].isdigit() and row[3].endswith("KB") or row[3].endswith("bytes")
    assert w.history.stats()[0] == 3


def test_history_is_there_after_a_restart(qapp):
    w, r = make_window(qapp)
    scan(qapp, w)
    w2, r2 = make_window(qapp)
    assert r2.history_table.rowCount() == 1


def test_retention_is_applied_after_each_scan(qapp):
    w, r = make_window(qapp)
    for i in range(12):
        w.history.save(old(i))
    w.settings_store.update(retention_max_scans=10)
    scan(qapp, w)
    assert w.history.stats()[0] == 10 and r.history_table.rowCount() == 10


def test_retention_is_applied_at_startup(qapp):
    w, r = make_window(qapp)
    for i in range(12):
        w.history.save(old(i))
    w.settings_store.update(retention_max_scans=10)
    w2, r2 = make_window(qapp)
    assert r2.history_table.rowCount() == 10


def test_opening_a_saved_scan_shows_it_everywhere_and_marks_it_as_not_live(qapp):
    w, r = make_window(qapp)
    sid = w.history.save(old(5))
    r.refresh_history()
    w.nav_buttons[4].click()
    r.history_table.selectRow(0)
    assert r.load_button.isEnabled()
    r.load_button.click()
    assert w.stack.currentWidget() is w.pages["Dashboard"]
    status = w.scan_bar.status_label.text()
    assert status.startswith("Viewing a saved scan from 2026-10-01 05:00:00 (not live)") and "Scan now" in status
    assert w.pages["Hardware"].has_data and w.pages["Network"].has_data and w.pages["Port Analyzer"].has_data
    assert w.pages["Hardware"].table.value_labels["computer_name"].text() == "TEST-PC"
    assert w._gateways == ["192.168.1.1"]
    assert w.history.stats()[0] == 1                       # viewing does not save a duplicate
    assert sid


def test_a_report_can_be_made_from_a_saved_scan(qapp, tmp_path):
    w, r = make_window(qapp)
    w.history.save(old(5))
    r.refresh_history()
    r.history_table.selectRow(0)
    r.load_button.click()
    target = str(tmp_path / "from-history.pdf")
    r.save_dialog = lambda default: target
    r.save_button.click()
    assert wait_until(qapp, lambda: r.save_button.isEnabled() and r.message.text().startswith("Saved:"))
    text = re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in pypdf.PdfReader(target).pages))
    assert "2026-10-12 12:00:00" in text or "2026-10-01" in text
    assert "Scan: 2026-10-01 05:00:00" in text


def test_a_new_scan_replaces_the_saved_view(qapp):
    w, r = make_window(qapp)
    w.history.save(old(5))
    r.refresh_history()
    r.history_table.selectRow(0)
    r.load_button.click()
    scan(qapp, w)
    assert w.scan_bar.status_label.text().startswith("Last scan: 2026-10-12 12:00:00")
    assert w.history.stats()[0] == 2


def test_deleting_one_saved_scan_needs_confirmation(qapp):
    w, r = make_window(qapp)
    for i in range(3):
        w.history.save(old(i))
    r.refresh_history()
    r.history_table.selectRow(0)
    r.confirm = lambda t, x: False
    r.delete_scan_button.click()
    assert w.history.stats()[0] == 3 and r.history_message.text() == "Nothing was deleted."
    r.confirm = lambda t, x: True
    r.delete_scan_button.click()
    assert w.history.stats()[0] == 2 and r.history_table.rowCount() == 2
    assert r.history_message.text() == "The saved scan was deleted." and r.history_message.objectName() == "Success"


def test_a_damaged_saved_scan_is_explained_and_does_not_break_anything(qapp):
    w, r = make_window(qapp)
    good, bad = w.history.save(old(1)), w.history.save(old(2))
    conn = sqlite3.connect(w.history.path)
    conn.execute("UPDATE scans SET payload=? WHERE id=?", (b"garbage", bad))
    conn.commit()
    conn.close()
    r.refresh_history()
    r.history_table.selectRow(0)                            # newest = the damaged one
    r.load_button.click()
    assert r.history_message.objectName() == "Error" and "damaged" in r.history_message.text()
    assert not w.pages["Hardware"].has_data
    r.history_table.selectRow(1)
    r.load_button.click()
    assert w.pages["Hardware"].has_data
    r.history_table.selectRow(0)                            # and the damaged one can still be deleted
    r.delete_scan_button.click()
    assert w.history.stats()[0] == 1


def test_a_history_failure_never_spoils_the_scan(qapp):
    class Failing(HistoryStore):
        def save(self, result, app_version=""):
            raise HistoryError("The history file is busy (is another PCInsight window using it?). Try again.")
    w, r = make_window(qapp, history_store=Failing(Path(__file__).parent / "unused.sqlite3"))
    scan(qapp, w)
    assert w.pages["Hardware"].has_data
    assert "History not saved: The history file is busy" in w.scan_bar.status_label.text()
    assert w.scan_bar.rescan_button.isEnabled()


def test_an_unexpected_history_error_is_contained(qapp):
    class Broken(HistoryStore):
        def save(self, result, app_version=""):
            raise RuntimeError("secret-internal")
    w, r = make_window(qapp, history_store=Broken(Path(__file__).parent / "unused2.sqlite3"))
    scan(qapp, w)
    assert w.pages["Hardware"].has_data
    assert "History not saved (RuntimeError)" in w.scan_bar.status_label.text()
    assert "secret" not in w.scan_bar.status_label.text()


def test_a_damaged_history_file_is_set_aside_at_startup_and_scanning_still_works(qapp):
    folder = Path(__import__("os").environ["PCINSIGHT_DATA_DIR"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "history.sqlite3").write_bytes(b"not a database at all" * 100)
    w, r = make_window(qapp)
    assert "damaged" in r.history_note.text() and "set aside" in r.history_note.text()
    assert any(f.name.startswith("history.sqlite3.damaged-") for f in folder.iterdir())
    scan(qapp, w)
    assert r.history_table.rowCount() == 1


def test_history_that_is_unavailable_is_explained_not_fatal(qapp):
    folder = Path(__import__("os").environ["PCINSIGHT_DATA_DIR"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "history.sqlite3").mkdir()                     # a folder where the file should be
    w, r = make_window(qapp)
    assert "not available" in r.history_note.text()
    assert "not available" in w.pages["Settings"].history_info.text()
    scan(qapp, w)
    assert w.pages["Hardware"].has_data and "History not saved" in w.scan_bar.status_label.text()
