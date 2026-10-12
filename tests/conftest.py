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
