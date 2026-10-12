from helpers import GIB, make_device_sources
from pcinsight.core.common import CollectionError
from pcinsight.core.models import Status
from pcinsight.core.storage_info import collect_storage

D1 = {"FriendlyName": "Samsung SSD 970", "Model": "Samsung SSD 970 EVO", "Size": 1000204886016,
      "MediaType": "SSD", "BusType": "NVMe", "HealthStatus": "Healthy"}
D2 = {"FriendlyName": "WD HDD", "Model": "", "Size": 2000398934016,
      "MediaType": "HDD", "BusType": "USB", "HealthStatus": "Warning"}


def collect(rows=None, ps_err=None, **kw):
    def ps(script):
        if ps_err:
            raise ps_err
        return rows
    return {s.key: s for s in collect_storage(make_device_sources(powershell_json=ps, **kw))}


def test_disks_and_volumes_are_separate_sections():
    secs = collect([D1, D2])
    assert list(secs) == ["storage_disk_1", "storage_disk_2", "volumes"]
    d1, d2 = secs["storage_disk_1"], secs["storage_disk_2"]
    assert d1.get("model").value == "Samsung SSD 970 EVO" and d1.get("capacity").value == "931.5 GB"
    assert d1.get("media_type").value == "SSD" and d1.get("bus_type").value == "NVMe"
    assert d1.get("health").value == "Healthy" and "not a SMART" in d1.get("health").note
    assert "not a SMART analysis" in d1.note
    assert d2.get("model").value == "WD HDD"          # falls back to FriendlyName
    assert d2.get("health").value == "Warning"
    assert "drive letters" in secs["volumes"].note and "health" in secs["volumes"].note


def test_free_space_text_and_removable_note():
    secs = collect([D1], volumes=lambda: [("C:\\", "NTFS", "rw,fixed"), ("E:\\", "FAT32", "rw,removable")])
    c, e = secs["volumes"].get("volume_1"), secs["volumes"].get("volume_2")
    assert c.label == "C:\\" and c.value == "NTFS \u00b7 500 GB total \u00b7 120 GB free (24% free)"
    assert e.note == "Removable drive."


def test_cdrom_remote_and_empty_fs_skipped():
    vols = [("C:\\", "NTFS", "rw,fixed"), ("D:\\", "", "cdrom"), ("E:\\", "CDFS", "ro,cdrom"),
            ("Z:\\", "NTFS", "rw,remote")]
    assert [f.label for f in collect([D1], volumes=lambda: vols)["volumes"].fields] == ["C:\\"]


def test_unspecified_type_and_unknown_health_are_unavailable_not_guessed():
    d = {**D1, "MediaType": "Unspecified", "HealthStatus": "Unknown", "BusType": ""}
    sec = collect([d])["storage_disk_1"]
    for key in ("media_type", "health", "bus_type"):
        assert sec.get(key).status is Status.UNAVAILABLE
    assert sec.get("capacity").status is Status.OK


def test_fallback_to_win32_diskdrive_when_storage_module_missing():
    dd = [{"Model": "Generic Disk", "Size": str(500 * GIB), "InterfaceType": "SCSI"}]
    secs = collect(ps_err=CollectionError("The PowerShell query failed"), cim_all=lambda c, p: dd)
    sec = secs["storage_disk_1"]
    assert sec.get("model").value == "Generic Disk" and sec.get("capacity").value == "500 GB"
    assert sec.get("bus_type").value == "SCSI"
    assert sec.get("media_type").status is Status.UNAVAILABLE and sec.get("health").status is Status.UNAVAILABLE
    assert "Storage module" in sec.get("media_type").note and "reliable" in sec.get("health").note
    assert "volumes" in secs


def test_both_sources_fail_reports_both_reasons():
    def cim(c, p):
        raise CollectionError("PowerShell was not found")
    f = collect(ps_err=CollectionError("The PowerShell query timed out"), cim_all=cim)["storage"].get("disks")
    assert f.status is Status.UNAVAILABLE and "Get-PhysicalDisk" in f.note and "Win32_DiskDrive" in f.note
    # drive free space still works
    assert "volumes" in collect(ps_err=CollectionError("x"), cim_all=cim)


def test_zero_disks_everywhere():
    secs = collect([], cim_all=lambda c, p: [])
    assert "no storage devices" in secs["storage"].get("disks").note.lower()


def test_volume_errors_are_isolated():
    def usage(p):
        if p.startswith("E"):
            raise PermissionError("denied")
        return (100, 40, 60)
    secs = collect([D1], volumes=lambda: [("C:\\", "NTFS", "rw,fixed"), ("E:\\", "NTFS", "rw,removable")],
                   disk_usage=usage)
    v = secs["volumes"]
    assert v.get("volume_1").status is Status.OK
    assert v.get("volume_2").status is Status.UNAVAILABLE and "not ready" in v.get("volume_2").note


def test_zero_size_volume_no_division_error():
    f = collect([D1], disk_usage=lambda p: (0, 0, 0))["volumes"].get("volume_1")
    assert f.status is Status.OK and "free)" not in f.value


def test_volume_list_failure_and_none():
    def boom():
        raise RuntimeError("secret")
    f = collect([D1], volumes=boom)["volumes"].get("volumes")
    assert f.status is Status.UNAVAILABLE and "secret" not in f.note
    assert collect([D1], volumes=lambda: [])["volumes"].get("volumes").status is Status.UNAVAILABLE


def test_default_sources_never_crash():
    assert any(s.key == "volumes" for s in collect_storage())
