"""Module 4b: graphics adapter collector."""
from __future__ import annotations

from .common import CollectionError, Reading, format_bytes, make_field, normalize_date, to_int
from .device_sources import DeviceSources, default_device_sources
from .models import InfoSection

SRC_VC = "Windows CIM (Win32_VideoController)"
SRC_DRV = "Windows registry (display driver)"
GPU_CLASS_KEY = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
GPU_FIELDS = ["Name", "DriverVersion", "DriverDate", "AdapterRAM"]
LEGACY_CAP = 0xFFF00000  # 4,293,918,720: what the legacy 32-bit AdapterRAM field reports for cards with 4 GB or more
GPU_NOTE = ("Integrated graphics share system memory, so their dedicated video memory can be small. "
            "Video memory is read from the display driver's registry entry when available, because "
            "Windows' older interface cannot report more than 4 GB.")


def _fail(msg: str) -> Reading:
    raise CollectionError(msg)


def _bytes_from_registry(raw: object) -> "int | None":
    if isinstance(raw, (bytes, bytearray)):
        n = int.from_bytes(bytes(raw[:8]), "little")
    elif isinstance(raw, int):
        n = raw
    else:
        n = to_int(raw)
    return n if n and n > 0 else None


def _registry_vram(s: DeviceSources, name: str, used: set[int]) -> "int | None":
    for idx in range(16):
        if idx in used:
            continue
        sub = f"{GPU_CLASS_KEY}\\{idx:04d}"
        try:
            desc = str(s.registry(sub, "DriverDesc")).strip()
        except CollectionError:
            continue
        if desc.lower() != name.lower():
            continue
        used.add(idx)
        try:
            return _bytes_from_registry(s.registry(sub, "HardwareInformation.qwMemorySize"))
        except CollectionError:
            return None
    return None


def _vram(s: DeviceSources, row: dict[str, str], used: set[int]) -> Reading:
    reg = _registry_vram(s, row.get("Name", ""), used) if row.get("Name") else None
    if reg:
        return Reading(format_bytes(reg), SRC_DRV)
    legacy = to_int(row.get("AdapterRAM"))
    if not legacy or legacy <= 0:
        raise CollectionError("Video memory was not reported")
    if legacy >= LEGACY_CAP:
        return Reading("4 GB or more", SRC_VC,
                       "Windows reports at most 4 GB through this interface; the exact size was not available.")
    return Reading(format_bytes(legacy), SRC_VC)


def _driver_date(raw: str) -> Reading:
    value, note = normalize_date(raw)
    return Reading(value, SRC_VC, note)


def collect_gpus(sources: DeviceSources | None = None) -> list[InfoSection]:
    s = sources or default_device_sources()
    now = s.now()
    try:
        rows = s.cim_all("Win32_VideoController", GPU_FIELDS)
        err = None if rows else CollectionError("Windows reported no graphics adapters")
    except CollectionError as exc:
        rows, err = [], exc
    if err is not None:
        return [InfoSection("gpu", "Graphics", [
            make_field("gpus", "Graphics adapters", SRC_VC, lambda: _fail(str(err)))], now, GPU_NOTE)]

    used: set[int] = set()
    sections = []
    for i, row in enumerate(rows, 1):
        name = row.get("Name", "").strip()
        fields = [
            make_field("gpu_name", "Adapter", SRC_VC, lambda r=row: Reading(r.get("Name", "").strip() or "Unknown adapter", SRC_VC)),
            make_field("driver_version", "Driver version", SRC_VC, lambda r=row: Reading(
                r.get("DriverVersion", ""), SRC_VC, "Windows driver version format; the vendor may show a different number.")),
            make_field("driver_date", "Driver date", SRC_VC, lambda r=row: _driver_date(r.get("DriverDate", ""))),
            make_field("vram", "Video memory (VRAM)", SRC_DRV, lambda r=row: _vram(s, r, used)),
        ]
        sections.append(InfoSection(f"gpu_{i}", f"Graphics adapter {i}" + (f" \u2014 {name}" if name else ""),
                                    fields, now, GPU_NOTE if i == 1 else ""))
    return sections


if __name__ == "__main__":  # python -m pcinsight.core.gpu_info
    from .models import Status
    for sec in collect_gpus():
        print(f"\n== {sec.title} ==")
        for f in sec.fields:
            print(f"{f.label:24} {f.value if f.status is Status.OK else '<' + f.status.value + '> ' + f.note}")
