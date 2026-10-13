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


# ---- Module 4 helpers ----
from pcinsight.core.device_sources import DeviceSources  # noqa: E402

GIB = 1024 ** 3


def no_cim_all(cls, props):
    raise CollectionError("PowerShell was not found")


def no_ps(script):
    raise CollectionError("PowerShell was not found")


def make_device_sources(registry=None, **overrides) -> DeviceSources:
    base = dict(
        registry=fake_registry(registry or {}), cim_all=no_cim_all, powershell_json=no_ps,
        memory_stats=lambda: (32 * GIB, 8 * GIB),
        volumes=lambda: [("C:\\", "NTFS", "rw,fixed")],
        disk_usage=lambda p: (500 * GIB, 380 * GIB, 120 * GIB), now=lambda: NOW)
    base.update(overrides)
    return DeviceSources(**base)


def sample_device_sections() -> list:
    return [
        InfoSection("memory", "Memory (RAM)", [
            InfoField("total_physical", "Total physical memory", "31.9 GB", Status.OK, "test"),
            InfoField("installed", "Installed memory (sum of modules)", "32 GB", Status.OK, "test"),
            InfoField("slots_total", "Memory slots", "4", Status.OK, "test"),
            InfoField("slots_used", "Slots populated", "2", Status.OK, "test"),
        ], NOW),
        InfoSection("memory_module_1", "Memory module 1 \u2014 DIMM_A1", [
            InfoField("type", "Memory type", "DDR4", Status.OK, "test"),
            InfoField("speed", "Rated speed", None, Status.UNAVAILABLE, "test", "not reported"),
        ], NOW),
        InfoSection("gpu_1", "Graphics adapter 1 \u2014 Test GPU", [
            InfoField("gpu_name", "Adapter", "Test GPU 3080", Status.OK, "test"),
            InfoField("vram", "Video memory (VRAM)", "10 GB", Status.OK, "test"),
        ], NOW),
        InfoSection("storage_disk_1", "Storage device 1 \u2014 Test SSD", [
            InfoField("model", "Model", "Test SSD 970", Status.OK, "test"),
            InfoField("capacity", "Capacity", "931.5 GB", Status.OK, "test"),
        ], NOW),
        InfoSection("volumes", "Drives and free space", [
            InfoField("volume_1", "C:\\", "NTFS \u00b7 500 GB total", Status.OK, "test"),
        ], NOW),
    ]


def sample_everything() -> ScanResult:
    r = sample_full_result()
    r.hardware = r.hardware + sample_device_sections()
    return r


# ---- Module 5 helpers ----
from pcinsight.core.network_info import NetworkScan, NetworkSources  # noqa: E402


def ps_root(adapters=(), routes=(), dns=(), dhcp=(), leases=(), failed=()):
    return [{"adapters": list(adapters), "routes": list(routes), "dns": list(dns),
             "dhcp": list(dhcp), "leases": list(leases), "failed": list(failed)}]


def eth_ps(idx=7, name="Ethernet", status="Up", **extra):
    ad = {"Name": name, "InterfaceDescription": "Intel(R) Ethernet Connection", "InterfaceIndex": idx,
          "Status": status, "LinkSpeed": "1 Gbps", "MediaType": "802.3", "PhysicalMediaType": "802.3",
          "Virtual": False, "HardwareInterface": True}
    ad.update(extra)
    return ad


def full_ps():
    return ps_root(
        adapters=[eth_ps()],
        routes=[{"InterfaceIndex": 7, "Family": "IPv4", "NextHop": "192.168.1.1"},
                {"InterfaceIndex": 7, "Family": "IPv6", "NextHop": "::"}],
        dns=[{"InterfaceIndex": 7, "Family": "IPv4", "Servers": ["192.168.1.1", "1.1.1.1"]},
             {"InterfaceIndex": 7, "Family": "IPv6", "Servers": []}],
        dhcp=[{"InterfaceIndex": 7, "Family": "IPv4", "Dhcp": "Enabled"}],
        leases=[{"InterfaceIndex": 7, "DHCPEnabled": True, "DHCPServer": "192.168.1.1",
                 "LeaseObtained": "2026-10-12 08:00", "LeaseExpires": "2026-10-13 08:00"}])


ETH_ROWS = [("mac", "AA-BB-CC-DD-EE-FF", ""), ("ipv4", "192.168.1.20", "255.255.255.0"),
            ("ipv6", "fe80::1234%Ethernet", "ffff:ffff:ffff:ffff::"),
            ("ipv6", "2001:db8::20", "ffff:ffff:ffff:ffff::")]


def make_net_sources(ifaces=None, stats=None, ps=None, ps_error=None, **kw) -> NetworkSources:
    ifaces = {"Ethernet": ETH_ROWS} if ifaces is None else ifaces
    stats = {"Ethernet": (True, 1000)} if stats is None else stats

    def powershell(script):
        if ps_error is not None:
            raise ps_error
        return ps if ps is not None else full_ps()

    base = dict(interfaces=lambda: ifaces, if_stats=lambda: stats, powershell_json=powershell, now=lambda: NOW)
    base.update(kw)
    return NetworkSources(**base)


def sample_network_sections() -> list:
    return [
        InfoSection("network", "Network overview", [
            InfoField("adapters", "Adapters found", "2 adapters (1 up)", Status.OK, "test")], NOW, "note"),
        InfoSection("net_adapter_1", "Ethernet \u2014 Test NIC", [
            InfoField("status", "Status", "Up (connected)", Status.OK, "test"),
            InfoField("ipv4", "IPv4 address", "192.168.1.20 \u00b7 mask 255.255.255.0 \u00b7 network 192.168.1.0/24",
                      Status.OK, "test"),
            InfoField("gateway", "Default gateway", "192.168.1.1 (IPv4)", Status.OK, "test"),
        ], NOW),
        InfoSection("net_adapter_2", "Wi-Fi \u2014 Test WLAN", [
            InfoField("status", "Status", "Disconnected (no link)", Status.OK, "test"),
            InfoField("ipv4", "IPv4 address", None, Status.EMPTY, "test", "No IPv4 address assigned."),
            InfoField("gateway", "Default gateway", None, Status.EMPTY, "test", "No default gateway on this adapter."),
        ], NOW),
    ]


def sample_everything_with_network() -> ScanResult:
    r = sample_everything()
    r.hardware = r.hardware + sample_network_sections()
    r.gateways = ["192.168.1.1"]
    return r


# ---- Module 6 helpers ----
from pcinsight.core.common import CollectionError as _CE  # noqa: E402
from pcinsight.core.ports_info import PortSources, RawEndpoint  # noqa: E402

PROCS = {4: "System", 1234: "svchost.exe", 2200: "mysqld.exe", 3300: "python.exe"}


def proc_name(pid):
    if pid == 5555:
        raise _CE("access denied")
    if pid == 6666:
        raise _CE("the process had already exited")
    if pid in PROCS:
        return PROCS[pid]
    raise _CE("lookup failed")


def ep(proto, address, port, pid=1234, family=None):
    return RawEndpoint(proto, family or ("ipv6" if ":" in address else "ipv4"), address, port, pid)


def make_port_sources(tcp=(), udp=(), tcp_error=None, udp_error=None, names=None, **kw) -> PortSources:
    def conns(kind):
        err = tcp_error if kind == "tcp" else udp_error
        if err is not None:
            raise err
        return list(tcp if kind == "tcp" else udp)

    base = dict(connections=conns, process_name=names or proc_name,
                service_name=lambda port, proto: None, now=lambda: NOW)
    base.update(kw)
    return PortSources(**base)


def sample_ports_sections() -> list:
    return [
        InfoSection("ports", "Listening ports overview", [
            InfoField("tcp_count", "Listening TCP endpoints", "3", Status.OK, "test"),
            InfoField("udp_count", "UDP endpoints (reachability not verified)", "2", Status.OK, "test"),
            InfoField("important", "Important ports with a local listener", "135, 445 listening (2 of 15)", Status.OK, "test"),
        ], NOW, "overview note"),
        InfoSection("ports_important", "Important ports", [
            InfoField("port_445", "Port 445 \u00b7 SMB", "Listening locally\n0.0.0.0:445 \u00b7 all interfaces \u00b7 System (PID 4)",
                      Status.OK, "test"),
            InfoField("port_22", "Port 22 \u00b7 SSH", "No local listener detected", Status.OK, "test"),
        ], NOW),
        InfoSection("ports_tcp", "All listening TCP endpoints", [
            InfoField("tcp_1", "445/TCP \u00b7 SMB", "Listening locally\n0.0.0.0:445 \u00b7 all interfaces \u00b7 System (PID 4)", Status.OK, "test"),
            InfoField("tcp_2", "3306/TCP \u00b7 MySQL", "Listening locally\n127.0.0.1:3306 \u00b7 loopback only \u00b7 Process details unavailable (access denied; PID 5555)",
                      Status.OK, "test"),
        ], NOW),
        InfoSection("ports_udp", "All UDP endpoints", [
            InfoField("udp_1", "5353/UDP \u00b7 mDNS", "UDP endpoint detected; remote reachability not verified\n0.0.0.0:5353 \u00b7 all interfaces \u00b7 svchost.exe (PID 1234)",
                      Status.OK, "test"),
        ], NOW),
    ]


def sample_with_ports() -> ScanResult:
    r = sample_everything_with_network()
    r.hardware = r.hardware + sample_ports_sections()
    return r
