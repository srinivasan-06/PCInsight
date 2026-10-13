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
        w.close()
        if isValid(w):
            delete(w)  # destroy now; leftovers make every later stylesheet change slower
    qapp.processEvents()
