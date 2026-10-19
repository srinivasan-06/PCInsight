import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    from pcinsight.ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    qapp.processEvents()
    yield w
    w.close()


@pytest.fixture(autouse=True)
def _cleanup_windows(qapp):
    """Destroy any windows a test created so the app-wide stylesheet isn't re-applied to leftovers."""
    yield
    from shiboken6 import delete, isValid
    for w in QApplication.topLevelWidgets():
        if not isValid(w):          # Qt may already have deleted it with its owner (e.g. a combo box popup)
            continue
        w.close()
        if isValid(w):
            delete(w)  # destroy now; leftovers make every later stylesheet change slower
    qapp.processEvents()


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    """Every test gets its own empty data folder, so no test can read or damage real settings/history/logs."""
    monkeypatch.setenv("PCINSIGHT_DATA_DIR", str(tmp_path / "pcinsight-data"))
    yield
    from pcinsight.core.diagnostics import configure_logging
    configure_logging(False, None)     # release any log file handle before the folder is removed


# ---- Module 9: keep "mocked tests passed" and "real hardware was checked" strictly apart -------------------------
_integration = {"passed": 0, "failed": 0, "skipped": 0}


def pytest_collection_modifyitems(items):
    """Every test in a *integration* file is marked, so `-m integration` / `-m "not integration"` always work."""
    for item in items:
        if "integration" in item.path.name:
            item.add_marker(pytest.mark.integration)


def pytest_runtest_logreport(report):
    if "integration" not in report.keywords:
        return
    if report.when == "call":
        _integration["passed" if report.passed else "failed"] += 1
    elif report.when == "setup" and report.skipped:
        _integration["skipped"] += 1
    elif report.when == "setup" and report.failed:
        _integration["failed"] += 1


def pytest_terminal_summary(terminalreporter):
    tr, i = terminalreporter, _integration
    tr.write_sep("=", "what this result does and does not prove")
    if i["passed"] == 0:
        tr.write_line("REAL-HARDWARE INTEGRATION TESTS DID NOT RUN (or none passed).", yellow=True, bold=True)
        tr.write_line("Every passing test above used MOCKED system data. That shows PCInsight handles the answers it was "
                      "given; it is NOT evidence that hardware detection works on this or any other PC.")
        tr.write_line('To check real hardware, run on Windows:  python -m pytest -m integration -s -rs   (or test.bat)')
    else:
        tr.write_line(f"Real-hardware integration tests: {i['passed']} passed, {i['failed']} failed, "
                      f"{i['skipped']} skipped - on THIS PC, THIS Windows install and THIS user's permissions only.",
                      bold=True)
        tr.write_line("This is not proof for other PCs. Repeat on each hardware / Windows / permission combination "
                      "you need to support (see TESTING.md).")
