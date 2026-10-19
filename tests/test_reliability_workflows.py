"""Module 9 - reliability of whole workflows (MOCKED system data): scan -> screens -> PDF -> shutdown.

Mocked tests show how PCInsight behaves when the system answers in a given way. They do not show that the real
PC answers that way; see tests/test_integration_windows.py for the real-hardware checks.
"""
from __future__ import annotations

import errno
import io
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime

import pypdf
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject
from PySide6.QtWidgets import QApplication, QLabel

from helpers import (NOW, ETH_ROWS, make_net_sources, sample_everything, sample_result, sample_with_ports,
                     wait_until, eth_ps, ps_root)
from pcinsight.core.models import InfoField, InfoSection, Status, SystemOverview
from pcinsight.core.network_info import collect_network
from pcinsight.core.scan import ScanResult, run_scan
from pcinsight.report import ReportError, write_report
from pcinsight.report import writer as writer_module
from pcinsight.ui import pages
from pcinsight.ui.main_window import MainWindow
from pcinsight.ui.scan_controller import ScanController

# ---------------------------------------------------------------------------------------------------------------
# helpers


@pytest.fixture
def no_uncaught(monkeypatch):
    """Fail the test if any exception escapes into Qt slots or background threads (these are otherwise only
    printed to the console and the test would pass while the app misbehaves)."""
    seen: list = []
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: seen.append(v))
    monkeypatch.setattr(threading, "excepthook", lambda args: seen.append(args.exc_value))
    yield seen
    assert seen == [], f"uncaught exceptions: {seen!r}"


@pytest.fixture
def outdir(tmp_path):
    """The folder the tests save reports into (kept apart from the app's own temporary data folder)."""
    d = tmp_path / "out"
    d.mkdir()
    return d


def make_window(qapp, scan_fn, **kw):
    w = MainWindow(scan_fn=scan_fn, **kw)
    w.show()
    qapp.processEvents()
    return w


def scan_and_wait(qapp, w):
    before = w.scan_bar.status_label.text()
    w.scan_bar.rescan_button.click()
    assert wait_until(qapp, lambda: w.scan_bar.rescan_button.isEnabled() and not w.controller.is_running), \
        "the scan never finished"
    flush(qapp)
    return before


def flush(qapp):
    """Widgets removed with deleteLater() still exist until Qt processes the deferred deletions."""
    for _ in range(3):
        qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def page_text(page) -> str:
    return " ".join(l.text() for l in page.findChildren(QLabel))


def pdf_text(path) -> str:
    return re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in pypdf.PdfReader(path).pages))


def nothing():
    return []


def empty_system():
    return SystemOverview([], NOW)


def adapter_scan(adapters: dict, ps_adapters=(), stats=None, routes=()) -> ScanResult:
    """A real collect_network() run on mocked adapters, wrapped into a scan result."""
    net = collect_network(make_net_sources(ifaces=adapters, stats=stats if stats is not None else {
        n: (True, 1000) for n in adapters}, ps=ps_root(adapters=list(ps_adapters), routes=list(routes))))
    return run_scan(lambda: sample_result().system, nothing, nothing, nothing, nothing, lambda: net, nothing)


# ---------------------------------------------------------------------------------------------------------------
# empty results


def test_a_scan_that_finds_nothing_is_shown_honestly_everywhere(qapp, tmp_path, no_uncaught):
    result = run_scan(empty_system, nothing, nothing, nothing, nothing,
                      lambda: collect_network(make_net_sources(ifaces={}, stats={}, ps=[])), nothing)
    w = make_window(qapp, lambda: result)
    scan_and_wait(qapp, w)
    for name in ("Dashboard", "Hardware", "Network", "Port Analyzer", "Reports", "Settings", "About"):
        w.nav_buttons[list(w.pages).index(name)].click()
        qapp.processEvents()
        text = page_text(w.pages[name])
        assert not re.search(r"\b(None|NaN|nan|null)\b", text), f"{name}: {text[:200]}"
    # a report can still be created and does not invent anything
    out = write_report(str(tmp_path / "empty.pdf"), result)
    text = pdf_text(out)
    assert text and "Traceback" not in text and not re.search(r"\bNone\b", text)
    w.close()


def test_every_collector_failing_still_gives_a_usable_app_and_report(qapp, tmp_path, no_uncaught):
    def boom():
        raise RuntimeError("SECRET-DETAIL 10.1.2.3")

    result = run_scan(empty_system, boom, boom, boom, boom, boom, boom)
    assert len(result.errors) == 6 and all("SECRET" not in e for e in result.errors)
    w = make_window(qapp, lambda: result)
    scan_and_wait(qapp, w)
    assert "6 problem(s)" in w.scan_bar.status_label.text() and w.scan_bar.rescan_button.isEnabled()
    out = write_report(str(tmp_path / "failed.pdf"), result)
    text = pdf_text(out)
    assert "could not be read" in text and "SECRET" not in text and "10.1.2.3" not in text
    w.close()


def test_a_failing_collector_leaves_no_stale_data_from_the_previous_scan(qapp, no_uncaught):
    """Scan 1 finds ports; in scan 2 the port collector fails. The Ports page must not keep showing scan 1."""
    first = sample_with_ports()
    second = sample_with_ports()
    second.hardware = [s for s in second.hardware if not s.key.startswith("ports")]
    second.errors = ["Listening ports could not be read (PermissionError)"]
    second.scanned_at = datetime(2026, 10, 12, 13, 0, 0)
    results = iter([first, second])
    w = make_window(qapp, lambda: next(results))
    scan_and_wait(qapp, w)
    assert "445/TCP" in page_text(w.pages["Port Analyzer"])
    scan_and_wait(qapp, w)
    ports_text = page_text(w.pages["Port Analyzer"])
    assert "445/TCP" not in ports_text and "3306/TCP" not in ports_text, "stale ports from the previous scan are shown"
    assert "could not be read" in ports_text
    w.close()


def test_data_that_disappears_between_scans_disappears_from_the_screens(qapp, no_uncaught):
    three = adapter_scan({"Ethernet": ETH_ROWS, "Wi-Fi": [("mac", "11-22-33-44-55-66", "")],
                          "vEthernet (WSL)": [("ipv4", "172.20.0.1", "255.255.240.0")]},
                         [eth_ps(7, "Ethernet"), eth_ps(8, "Wi-Fi", "Disconnected"), eth_ps(9, "vEthernet (WSL)")])
    one = adapter_scan({"Ethernet": ETH_ROWS}, [eth_ps(7, "Ethernet")])
    results = iter([three, one])
    w = make_window(qapp, lambda: next(results))
    scan_and_wait(qapp, w)
    assert "vEthernet (WSL) \u2014" in page_text(w.pages["Network"]) and "Wi-Fi \u2014" in page_text(w.pages["Network"])
    scan_and_wait(qapp, w)
    text = page_text(w.pages["Network"])
    assert "vEthernet (WSL) \u2014" not in text and "Wi-Fi \u2014" not in text and "Ethernet \u2014" in text
    w.close()


# ---------------------------------------------------------------------------------------------------------------
# multiple and disconnected adapters (the real network collector on mocked adapters)


def test_many_adapters_connected_disconnected_and_virtual(qapp, tmp_path, no_uncaught):
    adapters = {
        "Ethernet": ETH_ROWS,
        "Wi-Fi": [("mac", "11-22-33-44-55-66", "")],                                   # disconnected: no IP at all
        "Bluetooth Network Connection": [("mac", "AA-AA-AA-AA-AA-AA", "")],
        "vEthernet (Default Switch)": [("mac", "00-15-5D-00-00-01", ""), ("ipv4", "172.28.0.1", "255.255.240.0")],
        "vEthernet (WSL)": [("ipv4", "172.20.0.1", "255.255.240.0")],
        "Loopback Pseudo-Interface 1": [("ipv4", "127.0.0.1", "255.0.0.0")],
        "Ethernet 2": [("mac", "AA-BB-CC-DD-EE-02", ""), ("ipv4", "169.254.10.20", "255.255.0.0")],   # APIPA
    }
    stats = {"Ethernet": (True, 1000), "Wi-Fi": (False, 0), "Bluetooth Network Connection": (False, 3),
             "vEthernet (Default Switch)": (True, 10000), "vEthernet (WSL)": (True, 10000),
             "Loopback Pseudo-Interface 1": (True, 1000), "Ethernet 2": (True, 100)}
    ps = [eth_ps(7, "Ethernet"), eth_ps(8, "Wi-Fi", "Disconnected", MediaType="Native 802.11", PhysicalMediaType="Native 802.11"),
          eth_ps(9, "Bluetooth Network Connection", "Disconnected"),
          eth_ps(10, "vEthernet (Default Switch)", Virtual=True, HardwareInterface=False),
          eth_ps(11, "vEthernet (WSL)", Virtual=True, HardwareInterface=False), eth_ps(12, "Ethernet 2")]
    routes = [{"InterfaceIndex": 7, "Family": "IPv4", "NextHop": "192.168.1.1"}]
    result = adapter_scan(adapters, ps, stats, routes)
    assert result.errors == []
    adapter_sections = [s for s in result.hardware if s.key.startswith("net_adapter_")]
    assert len(adapter_sections) >= 6, [s.title for s in adapter_sections]

    w = make_window(qapp, lambda: result)
    scan_and_wait(qapp, w)
    text = page_text(w.pages["Network"])
    for name in ("Ethernet", "Wi-Fi", "Bluetooth Network Connection", "vEthernet (Default Switch)", "vEthernet (WSL)"):
        assert name in text, name
    # a disconnected adapter must not be given an address or a gateway it does not have
    wifi = next(s for s in adapter_sections if "Wi-Fi" in s.title)
    assert wifi.get("ipv4").status is Status.EMPTY and wifi.get("gateway").status is Status.EMPTY
    assert result.gateways == ["192.168.1.1"]                  # only from the adapter that is up
    out = write_report(str(tmp_path / "net.pdf"), result)
    text = pdf_text(out)
    for name in ("Wi-Fi", "Bluetooth Network Connection", "vEthernet (WSL)"):
        assert name in text, f"{name} missing from the PDF"
    w.close()


def test_adapter_listing_fails_but_the_rest_of_the_scan_continues(qapp, no_uncaught):
    def listing_fails():
        raise PermissionError("SECRET")
    net = collect_network(make_net_sources(interfaces=listing_fails))
    result = run_scan(lambda: sample_result().system, nothing, nothing, nothing, nothing, lambda: net, nothing)
    w = make_window(qapp, lambda: result)
    scan_and_wait(qapp, w)
    text = page_text(w.pages["Network"])
    assert "Could not list network adapters" in text and "SECRET" not in text
    w.close()


# ---------------------------------------------------------------------------------------------------------------
# long device names


@pytest.mark.parametrize("name", [
    "G" * 300,                                                     # no break opportunity at all
    "NVIDIA GeForce RTX " + "ULTRA " * 60,                         # many words
    "Prozessor \u00dcber \u4e2d\u6587\u8bbe\u5907 " * 12,          # non-Latin text
])
def test_long_device_names_survive_screen_and_pdf(qapp, tmp_path, no_uncaught, name):
    result = sample_everything()
    result.hardware = [InfoSection("gpu_1", f"Graphics adapter 1 \u2014 {name}", [
        InfoField("gpu_name", "Adapter", name, Status.OK, "test")], NOW)] + result.hardware[:2]
    w = make_window(qapp, lambda: result)
    scan_and_wait(qapp, w)
    assert w.pages["Hardware"].tables["gpu_1"].value_labels["gpu_name"].text() == name   # never cut off on screen
    assert w.width() <= 1180 + 40                                                       # and the window did not grow
    out = write_report(str(tmp_path / "long.pdf"), result)
    assert open(out, "rb").read(5) == b"%PDF-"
    if name.isascii():
        assert name.replace(" ", "") in pdf_text(out).replace(" ", "")                  # never cut off in the PDF
    w.close()


# ---------------------------------------------------------------------------------------------------------------
# PDF save failures, through the real Reports page


def _save_via_ui(qapp, w, path):
    page = w.pages["Reports"]
    page.save_dialog = lambda default: path
    page.save_button.click()
    assert wait_until(qapp, lambda: page.save_button.isEnabled() and not page.controller.is_running)
    return page


def _failures():
    def eacces(*a, **k):
        raise PermissionError(errno.EACCES, "SECRET denied")

    def enospc(*a, **k):
        raise OSError(errno.ENOSPC, "SECRET disk full")

    def eio(*a, **k):
        raise OSError(errno.EIO, "SECRET I/O error (network share went away)")

    def ebusy(*a, **k):
        raise OSError(errno.EBUSY, "SECRET busy")
    return [("replace-denied", "replace", eacces, "not allowed to save"),
            ("replace-disk-full", "replace", enospc, "not enough free disk space"),
            ("replace-io-error", "replace", eio, "could not be saved"),
            ("replace-locked", "replace", ebusy, "could not be saved"),
            ("fsync-io-error", "fsync", eio, "could not be saved"),
            ("fsync-disk-full", "fsync", enospc, "not enough free disk space")]


@pytest.mark.parametrize("label, target, error, expected", _failures(), ids=[f[0] for f in _failures()])
def test_pdf_save_failures_are_explained_leave_no_debris_and_never_touch_the_old_report(
        qapp, outdir, monkeypatch, no_uncaught, label, target, error, expected):
    w = make_window(qapp, sample_with_ports)
    scan_and_wait(qapp, w)
    dest = outdir / "report.pdf"
    dest.write_bytes(b"%PDF-OLD-REPORT")
    monkeypatch.setattr(writer_module.os, target, error)
    page = _save_via_ui(qapp, w, str(dest))
    assert page.message.objectName() == "Error" and expected in page.message.text()
    assert "SECRET" not in page.message.text()
    assert dest.read_bytes() == b"%PDF-OLD-REPORT", "the previous report was damaged by a failed save"
    assert [p.name for p in outdir.iterdir()] == ["report.pdf"], "a temporary file was left behind"
    assert not page.open_pdf_button.isVisibleTo(page)            # no "Open" button for a file that was not saved
    monkeypatch.undo()
    page = _save_via_ui(qapp, w, str(dest))                      # and the next attempt works without a restart
    assert page.message.objectName() == "Success" and dest.read_bytes().startswith(b"%PDF-1")
    w.close()


def test_a_write_that_dies_halfway_leaves_neither_a_partial_pdf_nor_a_temp_file(tmp_path, monkeypatch):
    real_open = open

    class Dying:
        def __init__(self, fh):
            self.fh = fh

        def write(self, data):
            self.fh.write(data[: len(data) // 2])
            raise OSError(errno.EIO, "device went away")

        def __getattr__(self, item):
            return getattr(self.fh, item)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.fh.close()
            return False

    def fake_open(path, mode="r", *a, **k):
        fh = real_open(path, mode, *a, **k)
        return Dying(fh) if "w" in mode and str(path).endswith(".tmp") else fh

    monkeypatch.setattr("builtins.open", fake_open)
    with pytest.raises(ReportError):
        write_report(str(tmp_path / "half.pdf"), sample_with_ports())
    monkeypatch.undo()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("path", ["bad\x00name.pdf", "x" * 400 + ".pdf", "con\x00.pdf"])
def test_impossible_file_names_give_a_clear_error_not_a_crash(tmp_path, path):
    with pytest.raises(ReportError):
        write_report(str(tmp_path / path), sample_with_ports())
    assert list(tmp_path.iterdir()) == []


def test_saving_below_a_file_instead_of_a_folder(tmp_path):
    (tmp_path / "afile").write_text("x")
    with pytest.raises(ReportError):
        write_report(str(tmp_path / "afile" / "r.pdf"), sample_with_ports())


def test_report_generation_failure_is_contained_and_nothing_is_written(qapp, outdir, monkeypatch, no_uncaught):
    def broken(*a, **k):
        raise MemoryError("SECRET")
    monkeypatch.setattr(writer_module, "build_report_pdf", broken)
    w = make_window(qapp, sample_with_ports)
    scan_and_wait(qapp, w)
    page = _save_via_ui(qapp, w, str(outdir / "r.pdf"))
    assert page.message.objectName() == "Error" and "SECRET" not in page.message.text()
    assert list(outdir.iterdir()) == []
    w.close()


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0, reason="needs a non-root POSIX user")
def test_a_really_read_only_folder(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    try:
        with pytest.raises(ReportError, match="not allowed"):
            write_report(str(ro / "r.pdf"), sample_with_ports())
    finally:
        ro.chmod(0o755)


# ---------------------------------------------------------------------------------------------------------------
# repeated scans


def test_twenty_scans_in_a_row_do_not_leak_threads_or_widgets(qapp, no_uncaught):
    w = make_window(qapp, sample_with_ports)
    for _ in range(3):                                           # warm up (lazy Qt objects are created once)
        scan_and_wait(qapp, w)
    qapp.processEvents()
    threads, objects = threading.active_count(), len(w.findChildren(QObject))
    rows = len(w.pages["Hardware"].tables)
    for _ in range(20):
        scan_and_wait(qapp, w)
    for _ in range(5):
        qapp.sendPostedEvents(None, 0)                           # deferred deletions
        qapp.processEvents()
    assert threading.active_count() <= threads, "scan threads are piling up"
    assert len(w.findChildren(QObject)) <= objects + 50, "widgets are piling up between scans"
    assert len(w.pages["Hardware"].tables) == rows
    w.close()


def test_alternating_failed_and_successful_scans(qapp, no_uncaught):
    n = []

    def flaky():
        n.append(1)
        if len(n) % 2:
            raise OSError("SECRET")
        return sample_with_ports()

    w = make_window(qapp, flaky)
    for i in range(8):
        w.scan_bar.rescan_button.click()
        assert wait_until(qapp, lambda: w.scan_bar.rescan_button.isEnabled() and not w.controller.is_running)
        text = w.scan_bar.status_label.text()
        assert ("failed" in text) == (i % 2 == 0), text
        assert "SECRET" not in text
    w.close()


def test_rapid_clicking_runs_one_scan_at_a_time(qapp, no_uncaught):
    running, peak, total = [0], [0], [0]
    lock = threading.Lock()

    def scan():
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
            total[0] += 1
        time.sleep(0.15)
        with lock:
            running[0] -= 1
        return sample_result()

    w = make_window(qapp, scan)
    for _ in range(30):
        w.controller.start()                                      # the button is disabled, but be rude anyway
        qapp.processEvents()
    assert wait_until(qapp, lambda: not w.controller.is_running)
    assert peak[0] == 1 and total[0] == 1
    w.close()


def test_scan_history_keeps_growing_correctly_over_repeated_scans(qapp, no_uncaught):
    w = make_window(qapp, sample_with_ports)
    for _ in range(6):
        scan_and_wait(qapp, w)
    assert len(w.history.list()) == 6
    w.close()


# ---------------------------------------------------------------------------------------------------------------
# application shutdown during and after a scan


def test_closing_after_a_finished_scan_and_closing_twice(qapp, no_uncaught):
    w = make_window(qapp, sample_with_ports)
    scan_and_wait(qapp, w)
    w.close()
    w.close()
    qapp.processEvents()
    assert not w.controller.is_running and not w.connectivity_controller.is_running


def test_closing_before_any_scan(qapp, no_uncaught):
    w = make_window(qapp, sample_with_ports)
    w.close()
    qapp.processEvents()


def test_a_scan_that_finishes_after_the_window_closed_is_dropped_everything_is_not_saved(qapp, no_uncaught):
    gate = threading.Event()
    w = make_window(qapp, lambda: gate.wait(5) and sample_with_ports())
    history = w.history
    w.scan_bar.rescan_button.click()
    assert w.controller.is_running
    threading.Timer(0.2, gate.set).start()
    w.close()                                                     # blocks until the scan thread has ended
    qapp.processEvents()
    assert not w.controller.is_running
    assert history.list() == [], "a scan that finished after closing must not be written to the history"
    assert not w.pages["Hardware"].has_data


@pytest.mark.parametrize("delay", [0.0, 0.001, 0.005, 0.02, 0.05, 0.1])
def test_closing_at_every_moment_of_a_scan(qapp, no_uncaught, delay):
    """Race: close at different moments between 'scan started' and 'result delivered'."""
    w = make_window(qapp, lambda: time.sleep(0.05) or sample_with_ports())
    w.scan_bar.rescan_button.click()
    end = time.time() + delay
    while time.time() < end:
        qapp.processEvents()
    w.close()
    qapp.processEvents()
    assert not w.controller.is_running


def test_closing_while_a_scan_connectivity_test_and_report_are_all_running(qapp, outdir, monkeypatch, no_uncaught):
    real = pages.write_report
    monkeypatch.setattr(pages, "write_report", lambda *a, **k: time.sleep(0.2) or real(*a, **k))
    release = threading.Event()
    w = MainWindow(scan_fn=lambda: release.wait(2) and sample_with_ports(),
                   connectivity_fn=lambda: release.wait(2) and None)
    w.show()
    w.pages["Reports"].set_scan(sample_with_ports())              # a report is possible while a new scan runs
    w.pages["Reports"].save_dialog = lambda d: str(outdir / "r.pdf")
    w.pages["Reports"].save_button.click()
    w.controller.start()
    w.connectivity_controller.start()
    threading.Timer(0.1, release.set).start()
    w.close()
    qapp.processEvents()
    assert not (w.controller.is_running or w.connectivity_controller.is_running or w.pages["Reports"].controller.is_running)
    assert not any(p.suffix == ".tmp" or p.name.startswith(".") for p in outdir.iterdir()), "temp file left behind"


def test_a_scan_that_will_not_stop_does_not_freeze_shutdown_forever(qapp, caplog):
    gate = threading.Event()
    ctrl = ScanController(lambda: gate.wait(10) or "late")
    done = []
    ctrl.scan_finished.connect(done.append)
    ctrl.start()
    started = time.time()
    with caplog.at_level(logging.ERROR):
        ctrl.shutdown(timeout_ms=100)
    assert time.time() - started < 2, "shutdown waited far longer than its timeout"
    assert "did not stop" in caplog.text
    gate.set()                                                    # let the stuck thread end so the test can clean up
    ctrl._thread.wait(5000)
    qapp.processEvents()
    assert done == [], "a result was delivered after shutdown"


def test_controller_refuses_work_after_shutdown_and_survives_repeated_shutdown(qapp):
    ctrl = ScanController(lambda: "r")
    ctrl.shutdown()
    ctrl.shutdown()
    assert ctrl.start() is False and not ctrl.is_running


def test_worker_crash_text_never_reaches_the_user_and_the_thread_is_released(qapp):
    class Weird(Exception):
        def __str__(self):
            return "SECRET C:\\Users\\alice"

    ctrl = ScanController(lambda: (_ for _ in ()).throw(Weird()))
    msgs = []
    ctrl.scan_failed.connect(msgs.append)
    ctrl.start()
    assert wait_until(qapp, lambda: msgs)
    assert msgs == ["Unexpected error (Weird)"] and not ctrl.is_running


# ---------------------------------------------------------------------------------------------------------------
# start-up


def test_application_entry_point_starts_and_returns_the_event_loop_result(qapp, monkeypatch):
    from pcinsight import app

    shown = []

    class FakeApp:
        def __init__(self, argv):
            self.argv = argv

        def setApplicationName(self, name):  # noqa: N802
            shown.append(("name", name))

        def setApplicationVersion(self, v):  # noqa: N802
            shown.append(("version", v))

        def exec(self):
            return 7

    class FakeWindow:
        def show(self):
            shown.append(("show", None))

    monkeypatch.setattr(app, "QApplication", FakeApp)
    monkeypatch.setattr(app, "MainWindow", FakeWindow)
    assert app.main(["pcinsight"]) == 7
    assert ("show", None) in shown and any(k == "name" for k, _ in shown)


def test_the_pcinsight_module_entry_point_exits_with_the_app_result(monkeypatch):
    import runpy
    from pcinsight import app
    monkeypatch.setattr(app, "main", lambda argv=None: 3)
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("pcinsight", run_name="__main__")
    assert exit_info.value.code == 3


def test_a_deliberately_raising_slot_is_detected_by_the_guard(qapp, monkeypatch):
    """Negative control: proves the 'no_uncaught' guard really can fail a test."""
    seen = []
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: seen.append(v))
    from PySide6.QtCore import QTimer

    def bad():
        raise ValueError("slot failure")
    QTimer.singleShot(0, bad)
    wait_until(qapp, lambda: seen, timeout=1)
    assert seen and isinstance(seen[0], ValueError)


def test_an_absurdly_long_value_is_shortened_with_a_visible_notice_instead_of_failing_the_whole_report(tmp_path):
    name = "A" * 5000
    result = sample_everything()
    result.hardware = [InfoSection("gpu_1", "Graphics adapter 1", [
        InfoField("gpu_name", "Adapter", name, Status.OK, "test")], NOW)] + result.hardware[:2]
    text = pdf_text(write_report(str(tmp_path / "huge.pdf"), result))
    assert "3,000 more characters are not shown in this report" in text
