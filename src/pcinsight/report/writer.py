"""Safe saving of the report. The user chooses the path; the file is written to a temporary name first and
only moved into place when complete, so a failure never leaves a half-written or damaged report behind and
never destroys an existing file."""
from __future__ import annotations

import errno
import logging
import os
from datetime import datetime
from pathlib import Path

from ..core.connectivity import ConnectivityResult
from ..core.scan import ScanResult
from .pdf_report import ReportOptions, build_report_pdf

logger = logging.getLogger(__name__)


class ReportError(Exception):
    """A report could not be created or saved. The message is safe and understandable to show to the user."""


def default_report_filename(now: datetime | None = None) -> str:
    return f"PCInsight-Report-{(now or datetime.now()).strftime('%Y%m%d-%H%M')}.pdf"


def write_report(path: str, result: ScanResult, connectivity: ConnectivityResult | None = None,
                 options: ReportOptions | None = None, generated_at: datetime | None = None) -> str:
    """Build and save the report. Returns the final path. Raises ReportError with a plain-language reason."""
    if not path or not path.strip():
        raise ReportError("No save location was chosen.")
    chosen = Path(path.strip())
    try:
        if chosen.is_dir():     # check the path as chosen, before any '.pdf' is added
            raise ReportError("That location is a folder. Please choose a file name for the report.")
        target = chosen if chosen.suffix.lower() == ".pdf" else chosen.with_name(chosen.name + ".pdf")
        if target.is_dir():
            raise ReportError("That location is a folder. Please choose a file name for the report.")
        if not target.parent.exists():
            raise ReportError("The folder you chose does not exist. Please choose another location.")
    except ReportError:
        raise
    except (OSError, ValueError) as exc:   # e.g. a name that is too long or contains invalid characters
        raise ReportError("That file name or path is not valid. Please choose a shorter or simpler name.") from exc

    try:
        data = build_report_pdf(result, connectivity, options, generated_at)
    except Exception as exc:  # noqa: BLE001 - boundary: nothing may escape as a crash
        logger.exception("Report generation failed")
        raise ReportError(f"The report could not be built ({type(exc).__name__}). Nothing was saved.") from exc

    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except PermissionError as exc:
        _cleanup(tmp)
        raise ReportError("PCInsight is not allowed to save there, or the file is open in another program "
                          "(for example a PDF viewer). Close it or choose a different location.") from exc
    except OSError as exc:
        _cleanup(tmp)
        if exc.errno == errno.ENOSPC:
            raise ReportError("There is not enough free disk space to save the report.") from exc
        if exc.errno in (errno.ENAMETOOLONG, errno.EINVAL):
            raise ReportError("That file name or path is not valid. Please choose a shorter or simpler name.") from exc
        raise ReportError(f"The report could not be saved ({type(exc).__name__}). Please try another location.") from exc
    return str(target)


def _cleanup(tmp: Path) -> None:
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
