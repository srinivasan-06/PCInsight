"""Module 2: system overview collector (no UI code here).

Sources, in order of preference:
  * Windows registry (fast, no subprocess): OS edition/version/build, firmware-reported
    manufacturer and model.
  * Windows CIM via PowerShell: fallback for manufacturer/model only.
  * psutil: boot time.   * Python platform/environment: computer name, architecture.
Every field is collected independently, so one failure never affects the others.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping

from .models import InfoField, Status, SystemOverview

logger = logging.getLogger(__name__)

CV_KEY = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
BIOS_KEY = r"HARDWARE\DESCRIPTION\System\BIOS"
SRC_REGISTRY_OS = "Windows registry (CurrentVersion)"
SRC_REGISTRY_BIOS = "Windows registry (firmware/BIOS data)"
SRC_CIM = "Windows CIM (Win32_ComputerSystem)"
SRC_PLATFORM = "Python platform module"
PLACEHOLDERS = {
    "to be filled by o.e.m.", "system manufacturer", "system product name", "default string",
    "o.e.m.", "oem", "not applicable", "none", "unknown", "system version",
}


class CollectionError(Exception):
    """A value could not be retrieved. The message is safe to show to the user."""


# --- real data sources -------------------------------------------------------------

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


def _psutil_boot_time() -> float:
    import psutil
    return psutil.boot_time()


@dataclass(frozen=True)
class SystemSources:
    registry: Callable[[str, str], object]
    cim_query: Callable[[str, list[str]], dict[str, str]]
    boot_time: Callable[[], float]
    node: Callable[[], str]
    machine: Callable[[], str]
    platform_version: Callable[[], str]
    env: Mapping[str, str]
    now: Callable[[], datetime]


def default_sources() -> SystemSources:
    return SystemSources(registry=read_registry_value, cim_query=query_cim,
                         boot_time=_psutil_boot_time, node=platform.node,
                         machine=platform.machine, platform_version=platform.version,
                         env=os.environ, now=datetime.now)


# --- field helpers -----------------------------------------------------------------

@dataclass
class _Reading:
    value: str
    source: str
    note: str = ""


def _field(key: str, label: str, default_source: str, fn: Callable[[], _Reading]) -> InfoField:
    try:
        r = fn()
    except CollectionError as exc:
        return InfoField(key, label, None, Status.UNAVAILABLE, default_source, str(exc))
    except Exception as exc:  # collector boundary: never let one field crash a scan
        logger.warning("Collector %s failed: %s", key, type(exc).__name__)
        return InfoField(key, label, None, Status.UNAVAILABLE, default_source,
                         "Unexpected error while reading this value")
    if not r.value or not r.value.strip():
        return InfoField(key, label, None, Status.EMPTY, r.source, r.note)
    return InfoField(key, label, r.value.strip(), Status.OK, r.source, r.note)


def _reg_str(s: SystemSources, path: str, name: str) -> str:
    value = s.registry(path, name)
    if value is None:
        raise CollectionError("Registry value not present on this system")
    return str(value).strip()


def _placeholder_note(value: str) -> str:
    if value.strip().lower() in PLACEHOLDERS:
        return "The firmware reports a generic placeholder; the maker did not set a real value."
    return ""


def format_uptime(seconds: float) -> str:
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes or not parts:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}" if (minutes or total >= 60)
                     else "less than a minute")
    return ", ".join(parts)


# --- individual collectors ---------------------------------------------------------

def _computer_name(s: SystemSources) -> _Reading:
    name = s.env.get("COMPUTERNAME") or s.node()
    return _Reading(name or "", "Environment / Python platform module")


def _os_edition(s: SystemSources) -> _Reading:
    name = _reg_str(s, CV_KEY, "ProductName")
    note = ""
    try:
        build = int(_reg_str(s, CV_KEY, "CurrentBuildNumber"))
    except (CollectionError, ValueError):
        build = 0
    if build >= 22000 and name.startswith("Windows 10"):
        name = "Windows 11" + name[len("Windows 10"):]
        note = "Windows still labels Windows 11 as 'Windows 10' in the registry; corrected using the build number."
    return _Reading(name, SRC_REGISTRY_OS, note)


def _os_version(s: SystemSources) -> _Reading:
    for name in ("DisplayVersion", "ReleaseId"):
        try:
            v = _reg_str(s, CV_KEY, name)
        except CollectionError:
            continue
        if v:
            return _Reading(v, SRC_REGISTRY_OS)
    raise CollectionError("This Windows version does not report a feature-update version")


def _os_build(s: SystemSources) -> _Reading:
    try:
        build = _reg_str(s, CV_KEY, "CurrentBuildNumber")
        try:
            return _Reading(f"{build}.{_reg_str(s, CV_KEY, 'UBR')}", SRC_REGISTRY_OS)
        except CollectionError:
            return _Reading(build, SRC_REGISTRY_OS, "Revision number not reported.")
    except CollectionError as exc:
        pv = s.platform_version()
        if re.match(r"^\d+\.\d+\.\d+", pv or ""):
            return _Reading(pv, SRC_PLATFORM,
                            "Registry unavailable; fell back to the Python platform module.")
        raise exc


_ARCH = {"AMD64": "x64 (AMD64)", "X86_64": "x64 (AMD64)", "ARM64": "ARM64", "AARCH64": "ARM64",
         "X86": "x86 (32-bit)", "I386": "x86 (32-bit)", "I686": "x86 (32-bit)"}


def _architecture(s: SystemSources) -> _Reading:
    raw = (s.env.get("PROCESSOR_ARCHITEW6432") or s.env.get("PROCESSOR_ARCHITECTURE")
           or s.machine() or "").strip().upper()
    if not raw:
        raise CollectionError("The processor architecture was not reported")
    return _Reading(_ARCH.get(raw, raw), "Environment / Python platform module",
                    "Operating-system architecture.")


def _firmware_value(s: SystemSources, reg_name: str, cim_prop: str) -> _Reading:
    try:
        v = _reg_str(s, BIOS_KEY, reg_name)
        return _Reading(v, SRC_REGISTRY_BIOS, _placeholder_note(v))
    except CollectionError as reg_err:
        try:
            v = s.cim_query("Win32_ComputerSystem", [cim_prop]).get(cim_prop, "")
            return _Reading(v, SRC_CIM, _placeholder_note(v))
        except CollectionError as cim_err:
            raise CollectionError(f"Registry: {reg_err}. CIM: {cim_err}.") from cim_err


def _boot_dt(s: SystemSources) -> datetime:
    boot = datetime.fromtimestamp(s.boot_time())
    if boot > s.now():
        raise CollectionError("Boot time is in the future (system clock may have changed)")
    return boot


def _last_boot(s: SystemSources) -> _Reading:
    return _Reading(_boot_dt(s).strftime("%Y-%m-%d %H:%M"), "psutil")


def _uptime(s: SystemSources) -> _Reading:
    secs = (s.now() - _boot_dt(s)).total_seconds()
    return _Reading(format_uptime(secs), "psutil",
                    "Windows Fast Startup may make this longer than time since the last restart.")


# --- public API --------------------------------------------------------------------

def collect_system_overview(sources: SystemSources | None = None) -> SystemOverview:
    s = sources or default_sources()
    fields = [
        _field("computer_name", "Computer name", "Environment / Python platform module", lambda: _computer_name(s)),
        _field("os_edition", "Windows edition", SRC_REGISTRY_OS, lambda: _os_edition(s)),
        _field("os_version", "Windows version", SRC_REGISTRY_OS, lambda: _os_version(s)),
        _field("os_build", "Windows build", SRC_REGISTRY_OS, lambda: _os_build(s)),
        _field("architecture", "System architecture", "Environment / Python platform module", lambda: _architecture(s)),
        _field("manufacturer", "System manufacturer", SRC_REGISTRY_BIOS, lambda: _firmware_value(s, "SystemManufacturer", "Manufacturer")),
        _field("model", "System model", SRC_REGISTRY_BIOS, lambda: _firmware_value(s, "SystemProductName", "Model")),
        _field("last_boot", "Last boot time", "psutil", lambda: _last_boot(s)),
        _field("uptime", "Uptime", "psutil", lambda: _uptime(s)),
    ]
    return SystemOverview(fields=fields, collected_at=s.now())


if __name__ == "__main__":  # quick manual check: python -m pcinsight.core.system_info
    ov = collect_system_overview()
    for f in ov.fields:
        shown = f.value if f.status is Status.OK else f"<{f.status.value}> {f.note}"
        print(f"{f.label:22} {shown}   [{f.source}]")
