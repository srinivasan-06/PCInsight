"""Module 3: CPU, motherboard and BIOS collector (no UI code here).

Sources: Windows registry (firmware/SMBIOS data copied there by Windows) first, then
Windows CIM via PowerShell as a fallback; psutil for core counts and frequency.
The chipset is NOT collected: Windows has no supported, reliable interface for it,
so the field is reported as unsupported rather than guessed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable

from .common import (CollectionError, Reading, make_field, placeholder_note, query_cim,
                     read_registry_value, reg_str)
from .models import InfoField, InfoSection, Status

CPU_KEY = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
BIOS_KEY = r"HARDWARE\DESCRIPTION\System\BIOS"
SRC_REG_CPU = "Windows registry (CentralProcessor)"
SRC_REG_BIOS = "Windows registry (firmware/SMBIOS data)"
SRC_CIM_CPU = "Windows CIM (Win32_Processor)"
SRC_CIM_BOARD = "Windows CIM (Win32_BaseBoard)"
SRC_CIM_BIOS = "Windows CIM (Win32_BIOS)"
SRC_PSUTIL = "psutil"
VENDORS = {"GenuineIntel": "Intel", "AuthenticAMD": "AMD", "HygonGenuine": "Hygon"}

CPU_NOTE = ("Cores and threads belong to the processor (CPU), not the motherboard. "
            "The motherboard only provides the socket and chipset the CPU works with.")
BOARD_NOTE = ("Board details are reported by your computer's firmware (SMBIOS). Some makers leave "
              "generic placeholder text, which is shown as reported.")
CHIPSET_NOTE = ("Windows does not expose the motherboard chipset through a supported, reliable "
                "interface, so PCInsight does not guess it. Look up your board model on the "
                "manufacturer's specification page.")


@dataclass(frozen=True)
class CpuBoardSources:
    registry: Callable[[str, str], object]
    cim_query: Callable[[str, list[str]], dict[str, str]]
    cpu_count: Callable[[bool], "int | None"]   # argument: logical?
    cpu_freq_mhz: Callable[[], "float | None"]
    now: Callable[[], datetime]


def _psutil_cpu_count(logical: bool) -> "int | None":
    import psutil
    return psutil.cpu_count(logical=logical)


def _psutil_cpu_freq() -> "float | None":
    import psutil
    f = psutil.cpu_freq()
    return None if f is None else f.current


def default_sources() -> CpuBoardSources:
    return CpuBoardSources(registry=read_registry_value, cim_query=query_cim,
                           cpu_count=_psutil_cpu_count, cpu_freq_mhz=_psutil_cpu_freq,
                           now=datetime.now)


# --- value post-processing ---------------------------------------------------------

def _plain(value: str) -> tuple[str, str]:
    return value, placeholder_note(value)


def _cpu_name(value: str) -> tuple[str, str]:
    return " ".join(value.split()), ""


def _vendor(value: str) -> tuple[str, str]:
    if value in VENDORS:
        return VENDORS[value], ""
    return value, ("Vendor ID shown as reported by the processor." if value else "")


def normalize_bios_date(raw: str) -> tuple[str, str]:
    """Return (YYYY-MM-DD, note). Unrecognised formats are returned untouched with a note."""
    raw = raw.strip()
    if not raw:
        return "", ""
    m = re.match(r"^/Date\((-?\d+)", raw)
    if m:
        d = datetime.fromtimestamp(int(m.group(1)) / 1000, tz=timezone.utc).date()
        return d.isoformat(), ""
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


# --- collectors ---------------------------------------------------------------------

def _reg_then_cim(s: CpuBoardSources, reg_key: str, reg_name: str, cim_class: str, cim_prop: str,
                  reg_source: str, cim_source: str,
                  post: Callable[[str], tuple[str, str]] = _plain) -> Reading:
    def finish(v: str, source: str) -> Reading:
        value, note = post(v)
        return Reading(value, source, note)

    try:
        return finish(reg_str(s.registry, reg_key, reg_name), reg_source)
    except CollectionError as reg_err:
        try:
            v = s.cim_query(cim_class, [cim_prop]).get(cim_prop, "")
        except CollectionError as cim_err:
            raise CollectionError(f"Registry: {reg_err}. CIM: {cim_err}.") from cim_err
        return finish(v, cim_source)


def _count(s: CpuBoardSources, logical: bool) -> Reading:
    n = s.cpu_count(logical)
    if n is None or n < 1:
        raise CollectionError("Windows did not report this count")
    return Reading(str(n), SRC_PSUTIL)


def _frequency(s: CpuBoardSources) -> Reading:
    mhz = s.cpu_freq_mhz()
    if not mhz or mhz <= 0:
        raise CollectionError("Windows did not report a current frequency")
    return Reading(f"{mhz:,.0f} MHz ({mhz / 1000:.2f} GHz)", SRC_PSUTIL,
                   "Snapshot at scan time; Windows may report the base clock rather than the live boost speed.")


def collect_cpu_board_bios(sources: CpuBoardSources | None = None) -> list[InfoSection]:
    s = sources or default_sources()
    now = s.now()
    cpu = [
        make_field("cpu_name", "CPU name", SRC_REG_CPU, lambda: _reg_then_cim(
            s, CPU_KEY, "ProcessorNameString", "Win32_Processor", "Name", SRC_REG_CPU, SRC_CIM_CPU, _cpu_name)),
        make_field("cpu_manufacturer", "CPU manufacturer", SRC_REG_CPU, lambda: _reg_then_cim(
            s, CPU_KEY, "VendorIdentifier", "Win32_Processor", "Manufacturer", SRC_REG_CPU, SRC_CIM_CPU, _vendor)),
        make_field("physical_cores", "Physical cores", SRC_PSUTIL, lambda: _count(s, False)),
        make_field("logical_processors", "Logical processors (threads)", SRC_PSUTIL, lambda: _count(s, True)),
        make_field("cpu_frequency", "Current frequency", SRC_PSUTIL, lambda: _frequency(s)),
    ]
    board = [
        make_field("board_manufacturer", "Motherboard manufacturer", SRC_REG_BIOS, lambda: _reg_then_cim(
            s, BIOS_KEY, "BaseBoardManufacturer", "Win32_BaseBoard", "Manufacturer", SRC_REG_BIOS, SRC_CIM_BOARD)),
        make_field("board_model", "Motherboard model", SRC_REG_BIOS, lambda: _reg_then_cim(
            s, BIOS_KEY, "BaseBoardProduct", "Win32_BaseBoard", "Product", SRC_REG_BIOS, SRC_CIM_BOARD)),
        InfoField("chipset", "Chipset", None, Status.UNSUPPORTED,
                  "Windows (no supported interface)", CHIPSET_NOTE),
    ]
    bios = [
        make_field("bios_vendor", "BIOS manufacturer", SRC_REG_BIOS, lambda: _reg_then_cim(
            s, BIOS_KEY, "BIOSVendor", "Win32_BIOS", "Manufacturer", SRC_REG_BIOS, SRC_CIM_BIOS)),
        make_field("bios_version", "BIOS version", SRC_REG_BIOS, lambda: _reg_then_cim(
            s, BIOS_KEY, "BIOSVersion", "Win32_BIOS", "SMBIOSBIOSVersion", SRC_REG_BIOS, SRC_CIM_BIOS)),
        make_field("bios_date", "BIOS release date", SRC_REG_BIOS, lambda: _reg_then_cim(
            s, BIOS_KEY, "BIOSReleaseDate", "Win32_BIOS", "ReleaseDate", SRC_REG_BIOS, SRC_CIM_BIOS,
            normalize_bios_date)),
    ]
    return [
        InfoSection("cpu", "Processor (CPU)", cpu, now, CPU_NOTE),
        InfoSection("motherboard", "Motherboard", board, now, BOARD_NOTE),
        InfoSection("bios", "BIOS / UEFI firmware", bios, now),
    ]


if __name__ == "__main__":  # python -m pcinsight.core.cpu_board_info
    for sec in collect_cpu_board_bios():
        print(f"\n== {sec.title} ==")
        for f in sec.fields:
            shown = f.value if f.status is Status.OK else f"<{f.status.value}> {f.note}"
            print(f"{f.label:30} {shown}   [{f.source}]")
