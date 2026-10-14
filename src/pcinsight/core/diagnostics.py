"""Optional diagnostic log file (off by default). It records which parts of a scan failed and why (exception
types), not scan contents; the collectors are written not to log addresses or device names."""
from __future__ import annotations

import logging
import logging.handlers
import platform
from pathlib import Path

from ..version import __version__

LOG_NAME = "pcinsight.log"
_handler: logging.Handler | None = None


def configure_logging(enabled: bool, log_dir: Path | None) -> None:
    """Switch the diagnostic log on or off. Safe to call repeatedly."""
    global _handler
    root = logging.getLogger("pcinsight")
    if _handler is not None:
        root.removeHandler(_handler)
        _handler.close()                    # release the file so it can be deleted on Windows
        _handler = None
    if not enabled or log_dir is None:
        return
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(log_dir / LOG_NAME, maxBytes=512 * 1024, backupCount=2,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.setLevel(logging.DEBUG)
    root.addHandler(handler)
    if root.level == logging.NOTSET or root.level > logging.DEBUG:
        root.setLevel(logging.DEBUG)
    _handler = handler
    root.info("Diagnostic logging enabled (PCInsight %s, Python %s, %s)", __version__, platform.python_version(),
              platform.system())


def log_files(log_dir: Path) -> list[Path]:
    return sorted(log_dir.glob(LOG_NAME + "*")) if log_dir.exists() else []


def delete_log_files(log_dir: Path) -> int:
    """Delete log files (closing the active one first). Returns how many were removed."""
    was_on = _handler is not None
    configure_logging(False, None)
    removed = 0
    for f in log_files(log_dir):
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    if was_on:
        configure_logging(True, log_dir)
    return removed
