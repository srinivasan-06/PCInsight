import io
import re

import pypdf
from PySide6.QtWidgets import QLabel

from helpers import sample_with_ports, wait_until
from pcinsight.core.connectivity import ConnectivityResult
from pcinsight.core.models import InfoField, InfoSection, Status
from pcinsight.ui import pages
from pcinsight.ui.main_window import MainWindow


def make_window(qapp, scanned=True, conn_fn=None):
    w = MainWindow(scan_fn=sample_with_ports, connectivity_fn=conn_fn or _conn)
    w.show()
    qapp.processEvents()
    if scanned:
        w.scan_bar.rescan_button.click()
        assert wait_until(qapp, lambda: w.pages["Reports"].save_button.isEnabled())
    return w


def _conn():
    from datetime import datetime
    f = [InfoField("internet", "Internet connection (TCP)", "Connected to 1.1.1.1:443 (12 ms)", Status.OK, "test")]
    t = datetime(2026, 10, 12, 12, 5, 0)
    return ConnectivityResult([InfoSection("net_connectivity", "Connectivity tests", f, t)], t)


def text_of(path):
    return re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in pypdf.PdfReader(path).pages))


def save(qapp, w, path):
    page = w.pages["Reports"]
    page.save_dialog = lambda default: path
    page.save_button.click()
    assert wait_until(qapp, lambda: not page.controller.is_running and page.save_button.isEnabled())
    return page


def test_disabled_before_any_scan_with_clear_reason(qapp):
    w = make_window(qapp, scanned=False)
    page = w.pages["Reports"]
    assert not page.save_button.isEnabled()
    assert "No scan yet" in page.scan_label.text() and page.save_button.toolTip() == "Run a scan first."


def test_save_creates_a_real_report_and_shows_where(qapp, tmp_path):
    w = make_window(qapp)
    target = str(tmp_path / "out.pdf")
    page = save(qapp, w, target)
    assert page.message.text() == f"Saved: {target}" and page.message.objectName() == "Success"
    assert page.open_pdf_button.isVisibleTo(page) and page.open_folder_button.isVisibleTo(page)
    assert "TEST-PC" in text_of(target) and not page.progress.isVisibleTo(page)
    assert "2026-10-12 12:00:00" in page.scan_label.text()


def test_default_name_offered_to_the_dialog(qapp, tmp_path):
    w = make_window(qapp)
    seen = []
    page = w.pages["Reports"]
    page.save_dialog = lambda default: seen.append(default) or ""
    page.save_button.click()
    assert re.search(r"PCInsight-Report-\d{8}-\d{4}\.pdf$", seen[0])


def test_cancelled_dialog_is_calm_and_creates_nothing(qapp, tmp_path):
    w = make_window(qapp)
    page = w.pages["Reports"]
    page.save_dialog = lambda default: ""
    page.save_button.click()
    qapp.processEvents()
    assert page.message.text() == "Save cancelled. No file was created."
    assert page.message.objectName() == "Muted" and page.save_button.isEnabled()
    assert not page.open_pdf_button.isVisibleTo(page) and not list(tmp_path.iterdir())


def test_save_errors_are_explained_and_the_app_keeps_working(qapp, tmp_path):
    w = make_window(qapp)
    page = save(qapp, w, str(tmp_path / "missing-folder" / "r.pdf"))
    assert page.message.objectName() == "Error"
    assert "Could not save the report." in page.message.text() and "does not exist" in page.message.text()
    assert not page.open_pdf_button.isVisibleTo(page) and page.save_button.isEnabled()
    good = str(tmp_path / "retry.pdf")                                   # and a retry works
    page = save(qapp, w, good)
    assert page.message.objectName() == "Success"


def test_unexpected_crash_while_saving_is_contained(qapp, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret-internal")
    monkeypatch.setattr(pages, "write_report", boom)
    w = make_window(qapp)
    page = save(qapp, w, str(tmp_path / "r.pdf"))
    assert page.message.objectName() == "Error" and "Nothing was saved" in page.message.text()
    assert "secret" not in page.message.text() and page.save_button.isEnabled()


def test_options_reach_the_pdf(qapp, tmp_path):
    w = make_window(qapp)
    page = w.pages["Reports"]
    page.include_ports.setChecked(False)
    page.paper.setCurrentText("Letter")
    save(qapp, w, str(tmp_path / "o.pdf"))
    assert "Listening-port results were left out" in text_of(str(tmp_path / "o.pdf"))
    box = pypdf.PdfReader(str(tmp_path / "o.pdf")).pages[0].mediabox
    assert round(float(box.width)) == 612


def test_connectivity_results_are_included_only_after_they_were_run(qapp, tmp_path):
    w = make_window(qapp)
    page = w.pages["Reports"]
    assert "Connectivity tests were not run" in page.scan_label.text()
    save(qapp, w, str(tmp_path / "a.pdf"))
    assert "Connectivity tests were not run" in text_of(str(tmp_path / "a.pdf"))
    w.pages["Network"].run_button.click()
    assert wait_until(qapp, lambda: "included" in page.scan_label.text())
    save(qapp, w, str(tmp_path / "b.pdf"))
    assert "Connected to 1.1.1.1:443 (12 ms)" in text_of(str(tmp_path / "b.pdf"))


def test_repeated_saves_and_overwrite(qapp, tmp_path):
    w = make_window(qapp)
    for i in range(3):
        save(qapp, w, str(tmp_path / f"r{i}.pdf"))
    save(qapp, w, str(tmp_path / "r0.pdf"))
    assert len(list(tmp_path.glob("*.pdf"))) == 3 and not list(tmp_path.glob("*.tmp"))
    assert open(tmp_path / "r0.pdf", "rb").read(4) == b"%PDF"


def test_open_buttons_use_the_saved_path(qapp, tmp_path):
    w = make_window(qapp)
    opened = []
    page = w.pages["Reports"]
    page.open_path = opened.append
    target = str(tmp_path / "x.pdf")
    save(qapp, w, target)
    page.open_pdf_button.click()
    page.open_folder_button.click()
    assert opened == [target, str(tmp_path)]


def test_report_uses_the_newest_scan(qapp, tmp_path):
    w = make_window(qapp)
    w.scan_bar.rescan_button.click()
    assert wait_until(qapp, lambda: w.scan_bar.rescan_button.isEnabled())
    save(qapp, w, str(tmp_path / "n.pdf"))
    assert "TEST-PC" in text_of(str(tmp_path / "n.pdf"))


def test_closing_the_window_while_the_report_is_being_built(qapp, tmp_path, monkeypatch):
    import time
    real = pages.write_report
    monkeypatch.setattr(pages, "write_report", lambda *a, **k: time.sleep(0.3) or real(*a, **k))
    w = make_window(qapp)
    page = w.pages["Reports"]
    page.save_dialog = lambda default: str(tmp_path / "late.pdf")
    page.save_button.click()
    w.close()
    qapp.processEvents()
    assert not page.controller.is_running


def test_button_cannot_start_two_reports_at_once(qapp, tmp_path, monkeypatch):
    import time
    real = pages.write_report
    monkeypatch.setattr(pages, "write_report", lambda *a, **k: time.sleep(0.3) or real(*a, **k))
    w = make_window(qapp)
    page = w.pages["Reports"]
    page.save_dialog = lambda default: str(tmp_path / "once.pdf")
    page.save_button.click()
    assert not page.save_button.isEnabled() and page.progress.isVisibleTo(page)
    page._on_save_clicked()                                              # a second click is ignored
    assert wait_until(qapp, lambda: page.save_button.isEnabled())
    assert len(list(tmp_path.glob("*.pdf"))) == 1


def test_page_explains_privacy(qapp):
    w = make_window(qapp, scanned=False)
    text = " ".join(l.text() for l in w.pages["Reports"].findChildren(QLabel))
    assert "never uploaded" in text and "IP addresses and MAC addresses" in text
