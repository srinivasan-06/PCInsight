"""Helpers shared by every collector (registry, PowerShell CIM, field construction)."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable

from .models import InfoField, Status

logger = logging.getLogger(__name__)

PLACEHOLDERS = {
    "to be filled by o.e.m.", "system manufacturer", "system product name", "default string",
    "o.e.m.", "oem", "not applicable", "none", "unknown", "system version",
    "base board manufacturer", "base board product name", "base board version",
}


class CollectionError(Exception):
    """A value could not be retrieved. The message is safe to show to the user."""


def read_registry_value(path: str, name: str) -> object:
    try:
        import winreg
    except ImportError as exc:
        raise CollectionError("The Windows registry is not available on this platform") from exc
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            return winreg.QueryValueEx(key, name)[0]
    except FileNotFoundError as exc:
        raise CollectionError("Registry value not present on this system") from exc
    except PermissionError as exc:
        raise CollectionError("Permission denied reading the registry value") from exc
    except OSError as exc:
        raise CollectionError("The registry value could not be read") from exc


_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def clean_value(v: object) -> str:
    return "" if v is None else str(v).strip()


def to_int(v: object) -> "int | None":
    """Best-effort integer parse; None when missing or not numeric."""
    s = clean_value(v)
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return None


def run_powershell_json(script: str, timeout: float = 20.0) -> list[dict]:
    """Run a fixed PowerShell script that ends in ConvertTo-Json; return a list of objects.

    Only constant scripts built by this app are passed in (never user input).
    """
    full = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; " + script
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", full]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError as exc:
        raise CollectionError("PowerShell was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise CollectionError("The PowerShell query timed out") from exc
    except OSError as exc:
        raise CollectionError("PowerShell could not be started") from exc
    if proc.returncode != 0:
        raise CollectionError("The PowerShell query failed")
    out = (proc.stdout or "").lstrip("\ufeff").strip()
    if not out:
        return []
    try:
        data = json.loads(out)
    except ValueError as exc:
        raise CollectionError("The PowerShell query returned unreadable data") from exc
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        raise CollectionError("The PowerShell query returned unreadable data")
    return data


def query_cim_all(class_name: str, properties: list[str], timeout: float = 20.0) -> list[dict[str, str]]:
    """Every instance of a CIM class, restricted to the named scalar properties."""
    if not _IDENT.match(class_name) or not all(_IDENT.match(p) for p in properties):
        raise CollectionError("Invalid CIM query")
    script = (f"Get-CimInstance -ClassName {class_name} | "
              f"Select-Object {','.join(properties)} | ConvertTo-Json -Compress")
    rows = run_powershell_json(script, timeout)
    return [{p: clean_value(r.get(p)) for p in properties} for r in rows]


def query_cim(class_name: str, properties: list[str], timeout: float = 15.0) -> dict[str, str]:
    """First instance of a CIM class."""
    rows = query_cim_all(class_name, properties, timeout)
    if not rows:
        raise CollectionError("The query returned no data")
    return rows[0]


_UNITS = ["bytes", "KB", "MB", "GB", "TB", "PB"]


def format_bytes(n: int) -> str:
    """Binary units (1 GB = 1,073,741,824 bytes), matching what Windows Explorer shows."""
    if n < 1024:
        return f"{n} bytes"
    v, i = float(n), 0
    while v >= 1024 and i < len(_UNITS) - 1:
        v /= 1024
        i += 1
    return f"{f'{v:.1f}'.rstrip('0').rstrip('.')} {_UNITS[i]}"


def normalize_date(raw: str) -> tuple[str, str]:
    """Return (YYYY-MM-DD, note). Unrecognised formats come back untouched with a note."""
    raw = raw.strip()
    if not raw:
        return "", ""
    m = re.match(r"^/Date\((-?\d+)", raw)
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).date().isoformat(), ""
    for fmt, note in (("%m/%d/%Y", ""), ("%Y-%m-%d", ""),
                      ("%m/%d/%y", "Firmware reported a two-digit year; century assumed.")):
        try:
            return datetime.strptime(raw, fmt).date().isoformat(), note
        except ValueError:
            pass
    m = re.match(r"^(\d{4})-?(\d{2})-?(\d{2})", raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat(), ""
        except ValueError:
            pass
    return raw, "Date format not recognised; shown as reported."


@dataclass
class Reading:
    value: str
    source: str
    note: str = ""


def make_field(key: str, label: str, default_source: str, fn: Callable[[], Reading]) -> InfoField:
    """Run one collector. Never raises: failures become UNAVAILABLE fields."""
    try:
        r = fn()
    except CollectionError as exc:
        return InfoField(key, label, None, Status.UNAVAILABLE, default_source, str(exc))
    except Exception as exc:  # collector boundary
        logger.warning("Collector %s failed: %s", key, type(exc).__name__)
        return InfoField(key, label, None, Status.UNAVAILABLE, default_source,
                         "Unexpected error while reading this value")
    if not r.value or not r.value.strip():
        return InfoField(key, label, None, Status.EMPTY, r.source, r.note)
    return InfoField(key, label, r.value.strip(), Status.OK, r.source, r.note)


def as_collection_error(exc: Exception) -> CollectionError:
    """Turn any exception into a CollectionError that is safe to show. The text of an unexpected exception can
    contain paths, names or addresses, so only its type is logged and nothing of it is shown."""
    if isinstance(exc, CollectionError):
        return exc
    logger.warning("Unexpected %s while reading system data", type(exc).__name__)
    return CollectionError("Unexpected error while reading this value")


def reg_str(read: Callable[[str, str], object], path: str, name: str) -> str:
    value = read(path, name)
    if value is None:
        raise CollectionError("Registry value not present on this system")
    return str(value).strip()


def placeholder_note(value: str) -> str:
    if value.strip().lower() in PLACEHOLDERS:
        return "The firmware reports a generic placeholder; the maker did not set a real value."
    return ""
