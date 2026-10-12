import time
from datetime import datetime, timedelta

from pcinsight.core.models import InfoField, Status, SystemOverview
from pcinsight.core.scan import ScanResult
from pcinsight.core.system_info import BIOS_KEY, CV_KEY, CollectionError, SystemSources

NOW = datetime(2026, 10, 12, 12, 0, 0)
BOOT = NOW - timedelta(days=1, hours=1, minutes=5)

BASE_REGISTRY = {
    (CV_KEY, "ProductName"): "Windows 10 Pro",
    (CV_KEY, "CurrentBuildNumber"): "22631",
    (CV_KEY, "UBR"): 3593,
    (CV_KEY, "DisplayVersion"): "23H2",
    (BIOS_KEY, "SystemManufacturer"): "Acme Corp",
    (BIOS_KEY, "SystemProductName"): "Widget 9",
}


def fake_registry(values):
    def read(path, name):
        try:
            return values[(path, name)]
        except KeyError:
            raise CollectionError("Registry value not present on this system")
    return read


def no_cim(cls, props):
    raise CollectionError("PowerShell was not found")


def make_sources(registry=None, **overrides) -> SystemSources:
    values = dict(BASE_REGISTRY if registry is None else registry)
    base = dict(
        registry=fake_registry(values), cim_query=no_cim,
        boot_time=lambda: BOOT.timestamp(), node=lambda: "NODE-PC", machine=lambda: "AMD64",
        platform_version=lambda: "10.0.22631", env={"COMPUTERNAME": "TEST-PC"}, now=lambda: NOW)
    base.update(overrides)
    return SystemSources(**base)


def sample_result(unavailable: bool = False, long_name: bool = False) -> ScanResult:
    model = "Z" * 150 if long_name else "Widget 9"
    fields = [
        InfoField("computer_name", "Computer name", "TEST-PC", Status.OK, "test"),
        InfoField("os_edition", "Windows edition", "Windows 11 Pro", Status.OK, "test"),
        InfoField("os_build", "Windows build", "22631.3593", Status.OK, "test"),
        InfoField("model", "System model", model, Status.OK, "test"),
        InfoField("uptime", "Uptime", "1 day", Status.OK, "test"),
    ]
    if unavailable:
        fields.append(InfoField("manufacturer", "System manufacturer", None, Status.UNAVAILABLE,
                                "test", "Permission denied"))
        fields.append(InfoField("os_version", "Windows version", None, Status.EMPTY, "test"))
    return ScanResult(SystemOverview(fields, NOW), NOW)


def wait_until(qapp, predicate, timeout=5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# ---- Module 3 helpers ----
from datetime import datetime as _dt  # noqa: E402

from pcinsight.core.cpu_board_info import BIOS_KEY as CB_BIOS_KEY, CPU_KEY, CpuBoardSources  # noqa: E402
from pcinsight.core.models import InfoSection  # noqa: E402

CPU_REGISTRY = {
    (CPU_KEY, "ProcessorNameString"): "Intel(R) Core(TM) i7-9700K CPU @ 3.60GHz   ",
    (CPU_KEY, "VendorIdentifier"): "GenuineIntel",
    (CB_BIOS_KEY, "BaseBoardManufacturer"): "ASUSTeK COMPUTER INC.",
    (CB_BIOS_KEY, "BaseBoardProduct"): "PRIME Z390-A",
    (CB_BIOS_KEY, "BIOSVendor"): "American Megatrends Inc.",
    (CB_BIOS_KEY, "BIOSVersion"): "2401",
    (CB_BIOS_KEY, "BIOSReleaseDate"): "03/15/2023",
}


def make_cpu_sources(registry=None, **overrides) -> CpuBoardSources:
    values = dict(CPU_REGISTRY if registry is None else registry)
    base = dict(registry=fake_registry(values), cim_query=no_cim,
                cpu_count=lambda logical: 16 if logical else 8,
                cpu_freq_mhz=lambda: 3600.0, now=lambda: NOW)
    base.update(overrides)
    return CpuBoardSources(**base)


def sample_hardware() -> list:
    return [
        InfoSection("cpu", "Processor (CPU)", [
            InfoField("cpu_name", "CPU name", "Test CPU 9000", Status.OK, "test"),
            InfoField("physical_cores", "Physical cores", "8", Status.OK, "test"),
            InfoField("logical_processors", "Logical processors (threads)", "16", Status.OK, "test"),
        ], NOW, "Cores belong to the CPU."),
        InfoSection("motherboard", "Motherboard", [
            InfoField("board_model", "Motherboard model", "Test Board", Status.OK, "test"),
            InfoField("chipset", "Chipset", None, Status.UNSUPPORTED, "test", "no interface"),
        ], NOW),
        InfoSection("bios", "BIOS / UEFI firmware", [
            InfoField("bios_version", "BIOS version", None, Status.UNAVAILABLE, "test", "denied"),
        ], NOW),
    ]


def sample_full_result() -> ScanResult:
    r = sample_result()
    r.hardware = sample_hardware()
    return r
