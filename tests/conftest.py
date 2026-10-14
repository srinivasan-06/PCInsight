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
