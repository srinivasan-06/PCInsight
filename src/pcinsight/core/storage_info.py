"""Module 4c: storage devices (physical disks) and drive free space (volumes).

Physical disks and volumes are different things: a disk can hold several drive letters.
Free space says nothing about disk health, and PCInsight keeps the two separate.
"""
from __future__ import annotations

from .common import CollectionError, Reading, as_collection_error, clean_value, format_bytes, make_field, to_int
from .device_sources import DeviceSources, default_device_sources
from .models import InfoSection

SRC_PD = "Windows Storage (Get-PhysicalDisk)"
SRC_DD = "Windows CIM (Win32_DiskDrive)"
SRC_VOL = "psutil"
PHYSICAL_DISK_SCRIPT = (
    "Get-PhysicalDisk | Select-Object FriendlyName,Model,Size,"
    "@{n='MediaType';e={[string]$_.MediaType}},@{n='BusType';e={[string]$_.BusType}},"
    "@{n='HealthStatus';e={[string]$_.HealthStatus}} | ConvertTo-Json -Compress")
DISK_NOTE = ("Health is Windows' own summary status, as reported. It is not a SMART analysis and does not "
             "predict failure. It is unrelated to free space.")
VOLUMES_NOTE = ("These are drive letters (volumes), not physical disks. Network drives and optical drives are "
                "skipped. Free space says nothing about the health of the disk.")
UNKNOWN = {"", "unknown", "unspecified"}


def _fail(msg: str) -> Reading:
    raise CollectionError(msg)


def _capacity(raw: object, source: str) -> Reading:
    n = to_int(raw)
    if not n or n <= 0:
        raise CollectionError("Capacity was not reported")
    return Reading(format_bytes(n), source, "Drive makers count 1 TB as 1,000,000,000,000 bytes, so Windows shows less.")


def _enum_field(raw: object, source: str, what: str, note: str = "") -> Reading:
    v = clean_value(raw)
    if v.lower() in UNKNOWN:
        raise CollectionError(f"Windows could not determine {what}")
    return Reading(v, source, note)


def _disk_sections(s: DeviceSources, now) -> list[InfoSection]:
    rows, fallback, primary_err = [], False, None
    try:
        rows = s.powershell_json(PHYSICAL_DISK_SCRIPT)
    except Exception as exc:  # noqa: BLE001 - boundary
        primary_err = as_collection_error(exc)
    if not rows:
        try:
            rows = s.cim_all("Win32_DiskDrive", ["Model", "Size", "InterfaceType"])
            fallback = True
        except Exception as fb_exc:  # noqa: BLE001 - boundary
            fb_err = as_collection_error(fb_exc)
            reason = (f"Get-PhysicalDisk: {primary_err}. " if primary_err else "Get-PhysicalDisk returned no disks. ")
            msg = f"{reason}Win32_DiskDrive: {fb_err}."
            return [InfoSection("storage", "Storage devices", [
                make_field("disks", "Storage devices", SRC_PD, lambda: _fail(msg))], now, DISK_NOTE)]
        if not rows:
            return [InfoSection("storage", "Storage devices", [
                make_field("disks", "Storage devices", SRC_DD, lambda: _fail("Windows reported no storage devices"))],
                now, DISK_NOTE)]

    sections = []
    for i, r in enumerate(rows, 1):
        model = clean_value(r.get("Model")) or clean_value(r.get("FriendlyName"))
        if fallback:
            fields = [
                make_field("model", "Model", SRC_DD, lambda m=model: Reading(m or "Unknown device", SRC_DD)),
                make_field("capacity", "Capacity", SRC_DD, lambda r=r: _capacity(r.get("Size"), SRC_DD)),
                make_field("media_type", "Type (SSD/HDD)", SRC_DD, lambda: _fail(
                    "Needs the Windows Storage module, which was not available")),
                make_field("bus_type", "Interface", SRC_DD, lambda r=r: _enum_field(r.get("InterfaceType"), SRC_DD, "the interface")),
                make_field("health", "Health (Windows summary)", SRC_DD, lambda: _fail(
                    "No reliable health source was available")),
            ]
        else:
            fields = [
                make_field("model", "Model", SRC_PD, lambda m=model: Reading(m or "Unknown device", SRC_PD)),
                make_field("capacity", "Capacity", SRC_PD, lambda r=r: _capacity(r.get("Size"), SRC_PD)),
                make_field("media_type", "Type (SSD/HDD)", SRC_PD, lambda r=r: _enum_field(
                    r.get("MediaType"), SRC_PD, "whether this is an SSD or HDD")),
                make_field("bus_type", "Interface", SRC_PD, lambda r=r: _enum_field(r.get("BusType"), SRC_PD, "the interface")),
                make_field("health", "Health (Windows summary)", SRC_PD, lambda r=r: _enum_field(
                    r.get("HealthStatus"), SRC_PD, "a health status", "As reported by Windows; not a SMART analysis.")),
            ]
        sections.append(InfoSection(f"storage_disk_{i}", f"Storage device {i}" + (f" \u2014 {model}" if model else ""),
                                    fields, now, DISK_NOTE if i == 1 else ""))
    return sections


def _volume_sections(s: DeviceSources, now) -> list[InfoSection]:
    try:
        vols = [v for v in s.volumes() if v[1] and "cdrom" not in v[2] and "remote" not in v[2]]
        err = None if vols else CollectionError("Windows reported no local drives")
    except Exception as exc:  # noqa: BLE001 - boundary
        vols, err = [], CollectionError(f"Drive list unavailable ({type(exc).__name__})")
    if err is not None:
        return [InfoSection("volumes", "Drives and free space", [
            make_field("volumes", "Drives", SRC_VOL, lambda: _fail(str(err)))], now, VOLUMES_NOTE)]

    def volume(mount: str, fstype: str, opts: str) -> Reading:
        try:
            total, _used, free = s.disk_usage(mount)
        except OSError as exc:
            raise CollectionError("Drive not ready or access denied") from exc
        pct = f" ({free / total:.0%} free)" if total > 0 else ""
        note = "Removable drive." if "removable" in opts else ""
        return Reading(f"{fstype} \u00b7 {format_bytes(total)} total \u00b7 {format_bytes(free)} free{pct}", SRC_VOL, note)

    fields = [make_field(f"volume_{i}", mount, SRC_VOL, lambda v=v: volume(*v)) for i, v in enumerate(vols, 1)
              for mount in [v[0]]]
    return [InfoSection("volumes", "Drives and free space", fields, now, VOLUMES_NOTE)]


def collect_storage(sources: DeviceSources | None = None) -> list[InfoSection]:
    s = sources or default_device_sources()
    now = s.now()
    return _disk_sections(s, now) + _volume_sections(s, now)


if __name__ == "__main__":  # python -m pcinsight.core.storage_info
    from .models import Status
    for sec in collect_storage():
        print(f"\n== {sec.title} ==")
        for f in sec.fields:
            print(f"{f.label:28} {f.value if f.status is Status.OK else '<' + f.status.value + '> ' + f.note}")
