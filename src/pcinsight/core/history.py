"""Local scan history in SQLite (standard library). Everything stays on this PC. Deleted scans are overwritten
(secure_delete) and 'delete all' also compacts the file. A damaged database is set aside and replaced."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from .models import Status
from .paths import data_dir
from .scan import ScanResult
from .serialization import result_from_dict, result_to_dict

logger = logging.getLogger(__name__)
DB_VERSION = 1


class HistoryError(Exception):
    """A history operation failed. The message is safe to show to the user."""


@dataclass(frozen=True)
class HistoryEntry:
    id: int
    scanned_at: datetime
    computer: str
    problems: int
    size_bytes: int


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class HistoryStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else data_dir() / "history.sqlite3"
        self.recovery_message = ""

    # -- connection handling ---------------------------------------------------------------------------
    def _open(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=5.0)
        try:
            conn.execute("PRAGMA secure_delete=ON")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > DB_VERSION:
                raise HistoryError("The history was created by a newer version of PCInsight and cannot be opened.")
            if version == 0:
                conn.execute("""CREATE TABLE IF NOT EXISTS scans(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, scanned_at TEXT NOT NULL, saved_at TEXT NOT NULL,
                    app_version TEXT NOT NULL, computer TEXT NOT NULL, problems INTEGER NOT NULL,
                    payload BLOB NOT NULL)""")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_scans_time ON scans(scanned_at)")
                conn.execute(f"PRAGMA user_version={DB_VERSION}")
                conn.commit()
            return conn
        except BaseException:
            conn.close()
            raise

    def _quarantine(self) -> None:
        target = self.path.with_name(f"{self.path.name}.damaged-{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            os.replace(self.path, target)
            self.recovery_message = ("The scan history file was damaged, so it was set aside as "
                                     f"{target.name} and an empty history was started.")
        except OSError as exc:
            raise HistoryError("The scan history file is damaged and could not be set aside.") from exc

    @contextmanager
    def _session(self) -> Iterator[sqlite3.Connection]:
        conn = None
        try:
            try:
                conn = self._open()
            except sqlite3.DatabaseError as exc:
                if type(exc) is sqlite3.DatabaseError:        # "file is not a database" / malformed (not locked/IO)
                    self._quarantine()
                    conn = self._open()
                else:
                    raise
            yield conn
            conn.commit()
        except HistoryError:
            raise
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            if "locked" in msg or "busy" in msg:
                raise HistoryError("The history file is busy (is another PCInsight window using it?). Try again.") from exc
            if "full" in msg:
                raise HistoryError("There is not enough free disk space for the scan history.") from exc
            raise HistoryError("The scan history file could not be opened or written.") from exc
        except sqlite3.Error as exc:
            raise HistoryError(f"The scan history could not be used ({type(exc).__name__}).") from exc
        except OSError as exc:
            raise HistoryError(f"The scan history could not be used ({type(exc).__name__}).") from exc
        finally:
            if conn is not None:
                conn.close()

    # -- operations ---------------------------------------------------------------------------------------------
    def save(self, result: ScanResult, app_version: str = "") -> int:
        try:
            payload = zlib.compress(json.dumps(result_to_dict(result), ensure_ascii=False).encode("utf-8"), 6)
        except (TypeError, ValueError) as exc:
            raise HistoryError("This scan could not be prepared for saving.") from exc
        name = result.system.get("computer_name")
        computer = name.value if name is not None and name.status is Status.OK and name.value else ""
        problems = (result.system.unavailable_count + sum(s.unavailable_count for s in result.hardware)
                    + len(result.errors))
        with self._session() as conn:
            cur = conn.execute(
                "INSERT INTO scans(scanned_at, saved_at, app_version, computer, problems, payload) VALUES(?,?,?,?,?,?)",
                (_iso(result.scanned_at), _iso(datetime.now()), app_version, computer, problems, payload))
            return int(cur.lastrowid)

    def list(self) -> list[HistoryEntry]:
        with self._session() as conn:
            rows = conn.execute("SELECT id, scanned_at, computer, problems, length(payload) FROM scans "
                                "ORDER BY scanned_at DESC, id DESC").fetchall()
        out = []
        for rid, at, computer, problems, size in rows:
            try:
                when = datetime.fromisoformat(at)
            except ValueError:
                when = datetime.min
            out.append(HistoryEntry(int(rid), when, computer, int(problems), int(size)))
        return out

    def load(self, scan_id: int) -> ScanResult:
        with self._session() as conn:
            row = conn.execute("SELECT payload FROM scans WHERE id=?", (scan_id,)).fetchone()
        if row is None:
            raise HistoryError("That saved scan no longer exists.")
        try:
            return result_from_dict(json.loads(zlib.decompress(row[0]).decode("utf-8")))
        except (zlib.error, ValueError, TypeError, UnicodeDecodeError, KeyError) as exc:
            msg = "newer version" if "newer version" in str(exc) else ""
            raise HistoryError("This saved scan was " + ("saved by a newer version of PCInsight and cannot be opened."
                                                         if msg else "damaged and cannot be opened. You can delete it.")) from exc

    def delete(self, scan_ids: list[int]) -> int:
        if not scan_ids:
            return 0
        with self._session() as conn:
            before = conn.total_changes
            conn.executemany("DELETE FROM scans WHERE id=?", [(i,) for i in scan_ids])
            return conn.total_changes - before

    def delete_all(self) -> int:
        with self._session() as conn:
            before = conn.total_changes
            conn.execute("DELETE FROM scans")
            removed = conn.total_changes - before
            conn.commit()
            conn.execute("VACUUM")          # compact the file so removed data is not left behind
            return removed

    def apply_retention(self, days: int, max_scans: int, now: datetime | None = None) -> int:
        removed = 0
        with self._session() as conn:
            before = conn.total_changes
            if days > 0:
                cutoff = _iso((now or datetime.now()) - timedelta(days=days))
                conn.execute("DELETE FROM scans WHERE scanned_at < ?", (cutoff,))
            if max_scans > 0:
                conn.execute("DELETE FROM scans WHERE id NOT IN "
                             "(SELECT id FROM scans ORDER BY scanned_at DESC, id DESC LIMIT ?)", (max_scans,))
            removed = conn.total_changes - before
        return removed

    def stats(self) -> tuple[int, int]:
        """(number of saved scans, size of the history file in bytes)."""
        with self._session() as conn:
            count = conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
        try:
            size = self.path.stat().st_size
        except OSError:
            size = 0
        return int(count), size
