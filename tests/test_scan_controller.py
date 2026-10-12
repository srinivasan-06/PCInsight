import threading
import time

from PySide6.QtCore import QObject

from helpers import wait_until
from pcinsight.ui.scan_controller import ScanController


def _collect(ctrl):
    out = {"done": [], "fail": [], "start": 0}
    ctrl.scan_finished.connect(out["done"].append)
    ctrl.scan_failed.connect(out["fail"].append)
    ctrl.scan_started.connect(lambda: out.__setitem__("start", out["start"] + 1))
    return out


def test_scan_runs_in_background_and_finishes(qapp):
    main_thread = threading.get_ident()
    seen = []
    ctrl = ScanController(lambda: seen.append(threading.get_ident()) or "RESULT")
    out = _collect(ctrl)
    assert ctrl.start() and out["start"] == 1
    assert wait_until(qapp, lambda: out["done"])
    assert out["done"] == ["RESULT"] and seen[0] != main_thread
    assert not ctrl.is_running


def test_failure_emits_failed_and_allows_next_scan(qapp):
    calls = []

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("secret detail")
        return "ok"

    ctrl = ScanController(fn)
    out = _collect(ctrl)
    ctrl.start()
    assert wait_until(qapp, lambda: out["fail"])
    assert "ValueError" in out["fail"][0] and "secret" not in out["fail"][0]
    ctrl.start()
    assert wait_until(qapp, lambda: out["done"])


def test_second_start_while_running_is_refused(qapp):
    gate = threading.Event()
    ctrl = ScanController(lambda: gate.wait(5) or "r")
    out = _collect(ctrl)
    assert ctrl.start()
    assert not ctrl.start() and out["start"] == 1
    gate.set()
    assert wait_until(qapp, lambda: out["done"])


def test_repeated_scans(qapp):
    ctrl = ScanController(lambda: "r")
    out = _collect(ctrl)
    for i in range(5):
        assert ctrl.start()
        assert wait_until(qapp, lambda i=i: len(out["done"]) == i + 1)


def test_shutdown_during_scan_waits_and_ignores_result(qapp):
    ctrl = ScanController(lambda: time.sleep(0.3) or "late")
    out = _collect(ctrl)
    ctrl.start()
    ctrl.shutdown()
    qapp.processEvents()
    assert not ctrl.is_running and out["done"] == [] and not ctrl.start()
