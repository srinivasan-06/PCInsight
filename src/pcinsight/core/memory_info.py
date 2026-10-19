"""Module 4a: memory (RAM) collector. Serial numbers are deliberately NOT collected."""
from __future__ import annotations

from .common import CollectionError, Reading, as_collection_error, format_bytes, make_field, placeholder_note, to_int
from .device_sources import DeviceSources, default_device_sources
from .models import InfoSection

SRC_PM = "Windows CIM (Win32_PhysicalMemory)"
SRC_ARRAY = "Windows CIM (Win32_PhysicalMemoryArray)"
SRC_PSUTIL = "psutil"
MODULE_FIELDS = ["Capacity", "SMBIOSMemoryType", "Speed", "ConfiguredClockSpeed",
                 "Manufacturer", "PartNumber", "DeviceLocator"]
# SMBIOS "Memory Device Type" codes (decimal)
MEMORY_TYPES = {18: "DDR", 19: "DDR2", 20: "DDR2 FB-DIMM", 24: "DDR3", 25: "FB-DIMM (DDR2)", 26: "DDR4",
                27: "LPDDR", 28: "LPDDR2", 29: "LPDDR3", 30: "LPDDR4", 32: "HBM", 33: "HBM2",
                34: "DDR5", 35: "LPDDR5", 36: "HBM3"}
SUMMARY_NOTE = ("\"Total physical memory\" is what Windows can use; it can be slightly lower than the "
                "installed memory because hardware reserves some. \"Available\" and \"In use\" are "
                "snapshots that change constantly.")
MODULES_NOTE = ("Speeds are reported by Windows in MHz; for DDR memory this usually equals the data rate "
                "(MT/s). Serial numbers are intentionally not collected.")


def _fail(msg: str) -> Reading:
    raise CollectionError(msg)


def _memory_type(code: "int | None") -> Reading:
    if code is None or code in (0, 2):
        raise CollectionError("Memory type not reported by the firmware")
    if code in MEMORY_TYPES:
        return Reading(MEMORY_TYPES[code], SRC_PM)
    return Reading(f"Unknown type (SMBIOS code {code})", SRC_PM, "Type code not recognised by PCInsight.")


def _mhz(value: str) -> Reading:
    n = to_int(value)
    if not n or n <= 0:
        raise CollectionError("Windows did not report this speed")
    return Reading(f"{n:,} MHz", SRC_PM)


def _text(value: str) -> Reading:
    return Reading(value.strip(), SRC_PM, placeholder_note(value))


def collect_memory(sources: DeviceSources | None = None) -> list[InfoSection]:
    s = sources or default_device_sources()
    now = s.now()

    modules, modules_err = None, None
    try:
        modules = s.cim_all("Win32_PhysicalMemory", MODULE_FIELDS)
    except Exception as exc:  # noqa: BLE001 - boundary: one bad query must not remove the whole section
        modules_err = as_collection_error(exc)

    def modules_or_raise() -> list[dict[str, str]]:
        if modules is None:
            raise modules_err  # type: ignore[misc]
        if not modules:
            raise CollectionError("Windows reported no memory modules (common on virtual machines)")
        return modules

    def stats() -> tuple[int, int]:
        total, avail = s.memory_stats()
        if total <= 0 or avail < 0 or avail > total:
            raise CollectionError("Windows returned inconsistent memory figures")
        return total, avail

    def installed() -> Reading:
        caps = [to_int(m.get("Capacity")) for m in modules_or_raise()]
        if any(c is None or c <= 0 for c in caps):
            raise CollectionError("Capacity was missing for one or more modules")
        return Reading(format_bytes(sum(caps)), SRC_PM, "Sum of the capacities reported for each module.")

    def slots_total() -> Reading:
        arrays = s.cim_all("Win32_PhysicalMemoryArray", ["MemoryDevices"])
        counts = [to_int(a.get("MemoryDevices")) for a in arrays]
        counts = [c for c in counts if c]
        if not counts:
            raise CollectionError("Windows did not report the number of memory slots")
        return Reading(str(sum(counts)), SRC_ARRAY)

    def in_use() -> Reading:
        total, avail = stats()
        return Reading(f"{format_bytes(total - avail)} ({(total - avail) / total:.0%})", SRC_PSUTIL,
                       "Snapshot at scan time.")

    summary = [
        make_field("total_physical", "Total physical memory", SRC_PSUTIL,
                   lambda: Reading(format_bytes(stats()[0]), SRC_PSUTIL, "Memory usable by Windows.")),
        make_field("available", "Available memory (right now)", SRC_PSUTIL,
                   lambda: Reading(format_bytes(stats()[1]), SRC_PSUTIL, "Snapshot at scan time.")),
        make_field("in_use", "In use (right now)", SRC_PSUTIL, in_use),
        make_field("installed", "Installed memory (sum of modules)", SRC_PM, installed),
        make_field("slots_total", "Memory slots", SRC_ARRAY, slots_total),
        make_field("slots_used", "Slots populated", SRC_PM,
                   lambda: Reading(str(len(modules_or_raise())), SRC_PM)),
    ]
    sections = [InfoSection("memory", "Memory (RAM)", summary, now, SUMMARY_NOTE)]

    if not modules:  # failed query or none reported
        sections.append(InfoSection("memory_modules", "Memory modules", [
            make_field("modules", "Memory modules", SRC_PM, lambda: (modules_or_raise() and _fail("")))],
            now, MODULES_NOTE))
        return sections

    for i, m in enumerate(modules, 1):
        locator = m.get("DeviceLocator", "").strip()
        fields = [
            make_field("slot", "Slot", SRC_PM, lambda m=m: _text(m.get("DeviceLocator", ""))),
            make_field("capacity", "Capacity", SRC_PM, lambda m=m: (
                Reading(format_bytes(to_int(m.get("Capacity"))), SRC_PM)
                if (to_int(m.get("Capacity")) or 0) > 0 else _fail("Capacity was not reported"))),
            make_field("type", "Memory type", SRC_PM, lambda m=m: _memory_type(to_int(m.get("SMBIOSMemoryType")))),
            make_field("speed", "Rated speed", SRC_PM, lambda m=m: _mhz(m.get("Speed", ""))),
            make_field("configured_speed", "Configured speed", SRC_PM,
                       lambda m=m: _mhz(m.get("ConfiguredClockSpeed", ""))),
            make_field("manufacturer", "Manufacturer", SRC_PM, lambda m=m: _text(m.get("Manufacturer", ""))),
            make_field("part_number", "Part number", SRC_PM, lambda m=m: _text(m.get("PartNumber", ""))),
        ]
        title = f"Memory module {i}" + (f" \u2014 {locator}" if locator else "")
        sections.append(InfoSection(f"memory_module_{i}", title, fields, now, MODULES_NOTE if i == 1 else ""))
    return sections


if __name__ == "__main__":  # python -m pcinsight.core.memory_info
    from .models import Status
    for sec in collect_memory():
        print(f"\n== {sec.title} ==")
        for f in sec.fields:
            print(f"{f.label:36} {f.value if f.status is Status.OK else '<' + f.status.value + '> ' + f.note}")
