"""Helpers shared by every collector (registry, PowerShell CIM, field construction)."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
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


def query_cim(class_name: str, properties: list[str], timeout: float = 15.0) -> dict[str, str]:
    if not _IDENT.match(class_name) or not all(_IDENT.match(p) for p in properties):
        raise CollectionError("Invalid CIM query")
    script = (f"Get-CimInstance -ClassName {class_name} | "
              f"Select-Object {','.join(properties)} | ConvertTo-Json -Compress")
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError as exc:
        raise CollectionError("PowerShell was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise CollectionError("The PowerShell query timed out") from exc
    except OSError as exc:
        raise CollectionError("PowerShell could not be started") from exc
    if proc.returncode != 0:
        raise CollectionError("The PowerShell query failed")
    try:
        data = json.loads(proc.stdout)
        if isinstance(data, list):
            data = data[0]
        if not isinstance(data, dict):
            raise ValueError
    except (ValueError, IndexError) as exc:
        raise CollectionError("The PowerShell query returned unreadable data") from exc
    return {p: ("" if data.get(p) is None else str(data[p]).strip()) for p in properties}


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


def reg_str(read: Callable[[str, str], object], path: str, name: str) -> str:
    value = read(path, name)
    if value is None:
        raise CollectionError("Registry value not present on this system")
    return str(value).strip()


def placeholder_note(value: str) -> str:
    if value.strip().lower() in PLACEHOLDERS:
        return "The firmware reports a generic placeholder; the maker did not set a real value."
    return ""
