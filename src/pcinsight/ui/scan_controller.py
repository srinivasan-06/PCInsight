"""Runs scans on a background thread so the UI never freezes."""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal

logger = logging.getLogger(__name__)


class _Worker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], object]):
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # thread boundary
            logger.exception("Scan failed")
            self.failed.emit(f"Unexpected error ({type(exc).__name__})")
            return
        self.finished.emit(result)


class ScanController(QObject):
    scan_started = Signal()
    scan_finished = Signal(object)
    scan_failed = Signal(str)

    def __init__(self, scan_fn: Callable[[], object], parent: QObject | None = None):
        super().__init__(parent)
        self._scan_fn = scan_fn
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._closing = False

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def start(self) -> bool:
        if self._thread is not None or self._closing:
            return False
        self._thread = QThread(self)
        self._worker = _Worker(self._scan_fn)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()
        self.scan_started.emit()
        return True

    def _cleanup(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        if self._worker is not None:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None

    def _on_finished(self, result: object) -> None:
        if self._closing or self._thread is None:
            return
        self._cleanup()
        self.scan_finished.emit(result)

    def _on_failed(self, message: str) -> None:
        if self._closing or self._thread is None:
            return
        self._cleanup()
        self.scan_failed.emit(message)

    def shutdown(self, timeout_ms: int = 25000) -> None:
        """Called when the window closes. Waits for a running scan; ignores its result."""
        self._closing = True
        if self._thread is not None:
            self._thread.quit()
            if not self._thread.wait(timeout_ms):
                logger.error("Scan thread did not stop within %d ms", timeout_ms)
                return
            if self._worker is not None:
                self._worker.deleteLater()
            self._thread = None
            self._worker = None
