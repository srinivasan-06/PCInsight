"""Module 9 - cross-collector reliability contract (MOCKED system data only).

Every collector must honour the same promises no matter how the operating system misbehaves:
  1. it never raises (a broken PC must not crash a scan),
  2. every field has a valid status; OK fields have a value, non-OK fields have no value and an explanation,
  3. nothing is invented (no 'None', 'nan', 'null' text) and
  4. the text of an unexpected exception (which may hold paths, names or addresses) never reaches the user.

These tests prove that PCInsight *handles* these situations. They do NOT prove that detection works on any
real PC - that is what tests/test_integration_windows.py is for (run it on Windows with test.bat).
"""
from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import replace
import types

import pytest

from helpers import NOW, make_cpu_sources, make_device_sources, make_net_sources, make_port_sources, make_sources
from pcinsight.core import common
from pcinsight.core.common import CollectionError
from pcinsight.core.connectivity import ConnectivitySources, run_connectivity_checks
from pcinsight.core.cpu_board_info import CpuBoardSources, collect_cpu_board_bios
from pcinsight.core.device_sources import DeviceSources
from pcinsight.core.gpu_info import collect_gpus
from pcinsight.core.memory_info import collect_memory
from pcinsight.core.models import InfoSection, Status, SystemOverview
from pcinsight.core.network_info import NetworkSources, collect_network
from pcinsight.core.ports_info import PortSources, collect_ports
from pcinsight.core.storage_info import collect_storage
from pcinsight.core.system_info import SystemSources, collect_system_overview

SECRET = "SECRET-DETAIL-C:\\Users\\alice\\192.168.7.7"

# ---------------------------------------------------------------------------------------------------------------
# the contract


def all_fields(result) -> list:
    if isinstance(result, SystemOverview):
        return list(result.fields)
    if hasattr(result, "sections"):          # NetworkScan / ConnectivityResult
        result = result.sections
    assert isinstance(result, list) and all(isinstance(s, InfoSection) for s in result)
    return [f for s in result for f in s.fields]


def assert_contract(result, *, leaked_ok: bool = False) -> list:
    fields = all_fields(result)
    for f in fields:
        assert isinstance(f.status, Status), f
        if f.status is Status.OK:
            assert f.value and f.value.strip(), f"OK field without a value: {f.key}"
        else:
            assert f.value is None, f"{f.status} field {f.key} carries a value: {f.value!r}"
        if f.status in (Status.UNAVAILABLE, Status.UNSUPPORTED):
            assert f.note and f.note.strip(), f"{f.status} field {f.key} has no explanation"
        assert (f.value or "").strip().lower() not in ("none", "nan", "null"), f"{f.key} shows a Python placeholder"
        shown = f"{f.value or ''} {f.note}".lower()
        assert not re.search(r"\b(None|NaN|nan)\b|traceback", f"{f.value or ''} {f.note}"), f"{f.key}: {shown!r}"
        if not leaked_ok:
            assert "secret-detail" not in shown, f"{f.key} leaked an exception message: {shown!r}"
            assert "alice" not in shown and "192.168.7.7" not in shown
    return fields


# ---------------------------------------------------------------------------------------------------------------
# a source set in which EVERY call fails with the given error

ERRORS = [
    pytest.param(PermissionError(SECRET), id="PermissionError"),
    pytest.param(OSError(5, SECRET), id="OSError-access-denied"),
    pytest.param(FileNotFoundError(SECRET), id="FileNotFoundError"),
    pytest.param(TimeoutError(SECRET), id="TimeoutError"),
    pytest.param(subprocess.TimeoutExpired(SECRET, 1), id="TimeoutExpired"),
    pytest.param(ValueError(SECRET), id="ValueError"),
    pytest.param(KeyError(SECRET), id="KeyError"),
    pytest.param(AttributeError(SECRET), id="AttributeError"),
    pytest.param(RuntimeError(SECRET), id="RuntimeError"),
    pytest.param(UnicodeDecodeError("utf-8", b"\xff", 0, 1, SECRET), id="UnicodeDecodeError"),
    pytest.param(CollectionError("The thing could not be read"), id="CollectionError"),
]


def boom(exc):
    def raiser(*a, **k):
        raise exc
    return raiser


def failing_system(exc) -> SystemSources:
    b = boom(exc)
    return SystemSources(registry=b, cim_query=b, boot_time=b, node=b, machine=b, platform_version=b,
                         env={}, now=lambda: NOW)


def failing_cpu(exc) -> CpuBoardSources:
    b = boom(exc)
    return CpuBoardSources(registry=b, cim_query=b, cpu_count=b, cpu_freq_mhz=b, now=lambda: NOW)


def failing_devices(exc) -> DeviceSources:
    b = boom(exc)
    return DeviceSources(registry=b, cim_all=b, powershell_json=b, memory_stats=b, volumes=b, disk_usage=b,
                         now=lambda: NOW)


def failing_network(exc) -> NetworkSources:
    b = boom(exc)
    return NetworkSources(interfaces=b, if_stats=b, powershell_json=b, now=lambda: NOW)


def failing_ports(exc) -> PortSources:
    b = boom(exc)
    return PortSources(connections=b, process_name=b, service_name=b, now=lambda: NOW)


def failing_connectivity(exc) -> ConnectivitySources:
    b = boom(exc)
    return ConnectivitySources(ping=b, tcp_connect=b, resolve=b, now=lambda: NOW)


COLLECTORS = {
    "system": lambda e: collect_system_overview(failing_system(e)),
    "cpu_board_bios": lambda e: collect_cpu_board_bios(failing_cpu(e)),
    "memory": lambda e: collect_memory(failing_devices(e)),
    "gpu": lambda e: collect_gpus(failing_devices(e)),
    "storage": lambda e: collect_storage(failing_devices(e)),
    "network": lambda e: collect_network(failing_network(e)),
    "ports": lambda e: collect_ports(failing_ports(e)),
    "connectivity": lambda e: run_connectivity_checks(["192.168.1.1"], failing_connectivity(e)),
}


@pytest.mark.parametrize("exc", ERRORS)
@pytest.mark.parametrize("name", COLLECTORS)
def test_when_every_system_call_fails_the_collector_still_answers_honestly(name, exc):
    """Missing / unavailable hardware information and permission restrictions, for every collector."""
    result = COLLECTORS[name](exc)
    fields = assert_contract(result)
    assert fields, f"{name}: a failing system must still produce rows that tell the user what happened"
    # nothing succeeded, so nothing may claim success for hardware it could not read
    hardware_claims = [f for f in fields if f.status is Status.OK and f.source not in ("psutil", "Python platform module")]
    for f in hardware_claims:
        # only values derived locally (never from the failing sources) may still be OK, e.g. computer name from the
        # environment - they must still have honest content
        assert f.value.strip()


@pytest.mark.parametrize("name", COLLECTORS)
def test_failures_report_a_problem_count_so_the_ui_can_flag_them(name):
    result = COLLECTORS[name](PermissionError(SECRET))
    secs = result if isinstance(result, list) else getattr(result, "sections", None)
    if isinstance(result, SystemOverview):
        assert result.unavailable_count >= 1
    else:
        assert sum(s.unavailable_count for s in secs) >= 1, f"{name} hid a failure"


# ---------------------------------------------------------------------------------------------------------------
# hardware that is simply not there: the source answers, with nothing


def test_no_gpu_no_memory_no_disks_no_volumes_no_adapters_no_ports():
    empty = make_device_sources(cim_all=lambda c, p: [], powershell_json=lambda s: [],
                                volumes=lambda: [], registry=boom(CollectionError("not present")))
    for fn in (collect_memory, collect_gpus, collect_storage):
        secs = fn(empty)
        assert_contract(secs)                                   # may be [] or rows that say "nothing found"
    net = collect_network(make_net_sources(ifaces={}, stats={}, ps=[]))
    assert_contract(net)
    assert net.gateways == []
    ports = collect_ports(make_port_sources())
    assert_contract(ports)


def test_registry_returns_odd_value_types_without_crashing():
    """REG_BINARY gives bytes, REG_MULTI_SZ gives a list, REG_DWORD an int; firmware can store junk."""
    odd = [b"\x00\x01\xfe", ["A", "B"], 5, "", "   ", "\x00\x00", "x" * 5000, "tab\tand\nnewline", None,
           "caf\u00e9 \u2014 \u4e2d\u6587", 3.5, True, {"a": 1}]
    for value in odd:
        read = lambda path, name, v=value: v  # noqa: E731
        assert_contract(collect_system_overview(replace(make_sources(), registry=read)))
        assert_contract(collect_cpu_board_bios(replace(make_cpu_sources(), registry=read)))


def test_cim_returns_rows_with_missing_blank_or_wrong_typed_columns():
    for rows in ([{}], [{"Name": "", "Capacity": "", "Manufacturer": " "}],
                 [{"Capacity": "not-a-number", "Speed": "fast", "AdapterRAM": "-1"}],
                 [{"AdapterRAM": "4294967295", "Name": "N" * 400}], [{}, {}, {}]):
        src = make_device_sources(cim_all=lambda c, p, rows=rows: [dict(r) for r in rows],
                                  powershell_json=lambda s, rows=rows: [dict(r) for r in rows])
        for fn in (collect_memory, collect_gpus, collect_storage):
            assert_contract(fn(src))


def test_powershell_returns_nonsense_shapes_to_the_network_collector():
    for ps in ([], [{}], [{"adapters": None}], [{"adapters": "oops"}], [{"adapters": [1, 2]}], [{"adapters": [{}]}],
               [{"adapters": [{"Name": None, "InterfaceIndex": "x"}], "routes": [None], "dns": 5}], ["a"], [[]]):
        assert_contract(collect_network(make_net_sources(ps=ps)))


# ---------------------------------------------------------------------------------------------------------------
# permission restriction, one value at a time: other values must still be reported


def test_one_denied_value_does_not_hide_the_others():
    def reg(path, name):
        if name == "SystemManufacturer":
            raise PermissionError(SECRET)
        raise CollectionError("Registry value not present on this system")
    ov = collect_system_overview(replace(make_sources(), registry=reg))
    assert_contract(ov)
    assert ov.get("manufacturer").status is Status.UNAVAILABLE
    assert ov.get("computer_name").status is Status.OK                 # unaffected
    assert ov.get("uptime").status is Status.OK


def test_unexpected_boot_time_values_do_not_crash():
    for bad in (0, -1, 1e30, float("nan"), float("inf"), "x", None):
        assert_contract(collect_system_overview(make_sources(boot_time=lambda b=bad: b)))


# ---------------------------------------------------------------------------------------------------------------
# unsupported Windows data: the real default sources on a PC that has no registry / no PowerShell


class _FakeWinreg(types.ModuleType):
    HKEY_LOCAL_MACHINE = 0x80000002
    KEY_READ = 0x20019
    KEY_WOW64_64KEY = 0x100

    def __init__(self, error=None, value="v"):
        super().__init__("winreg")
        self._error, self._value = error, value

    def OpenKey(self, *a):  # noqa: N802
        if self._error:
            raise self._error
        return self

    def QueryValueEx(self, key, name):  # noqa: N802
        return (self._value, 1)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.parametrize("error, expected", [
    (FileNotFoundError(), "not present"),
    (PermissionError(), "Permission denied"),
    (OSError(5, "x"), "could not be read"),
    (OSError(1450, "insufficient system resources"), "could not be read"),
])
def test_registry_reader_translates_windows_errors(monkeypatch, error, expected):
    monkeypatch.setitem(sys.modules, "winreg", _FakeWinreg(error))
    with pytest.raises(CollectionError, match=expected):
        common.read_registry_value("SOFTWARE\\X", "Y")


def test_registry_reader_returns_the_value_when_present(monkeypatch):
    monkeypatch.setitem(sys.modules, "winreg", _FakeWinreg(value="Windows 11 Pro"))
    assert common.read_registry_value("SOFTWARE\\X", "Y") == "Windows 11 Pro"


def test_registry_reader_on_a_platform_without_winreg(monkeypatch):
    monkeypatch.setitem(sys.modules, "winreg", None)       # `import winreg` raises ImportError
    with pytest.raises(CollectionError, match="not available on this platform"):
        common.read_registry_value("SOFTWARE\\X", "Y")


class _Proc:
    def __init__(self, out="", code=0):
        self.stdout, self.returncode = out, code


@pytest.mark.parametrize("behaviour, message", [
    (FileNotFoundError(), "not found"),
    (subprocess.TimeoutExpired("powershell", 20), "timed out"),
    (PermissionError("blocked by policy"), "could not be started"),
    (OSError(740, "elevation required"), "could not be started"),
    (_Proc("", 1), "failed"),
    (_Proc("not json"), "unreadable"),
    (_Proc("[1, 2, 3]"), "unreadable"),
    (_Proc('"just a string"'), "unreadable"),
    (_Proc('{"a": '), "unreadable"),
])
def test_powershell_runner_failure_modes(monkeypatch, behaviour, message):
    def fake_run(*a, **k):
        if isinstance(behaviour, BaseException):
            raise behaviour
        return behaviour
    monkeypatch.setattr(common.subprocess, "run", fake_run)
    with pytest.raises(CollectionError, match=message):
        common.run_powershell_json("Get-Date")


def test_powershell_runner_accepts_empty_bom_object_and_list(monkeypatch):
    for out, expected in (("", []), ("\ufeff[]", []), ('\ufeff{"A": 1}', [{"A": 1}]), ('[{"A": 1}, {"A": 2}]', [{"A": 1}, {"A": 2}])):
        monkeypatch.setattr(common.subprocess, "run", lambda *a, out=out, **k: _Proc(out))
        assert common.run_powershell_json("x") == expected


def _locked_down_pc(monkeypatch):
    """A Windows PC without registry access and without PowerShell (Server Core, WinPE, group policy)."""
    monkeypatch.setitem(sys.modules, "winreg", None)
    monkeypatch.setattr(common.subprocess, "run", boom(FileNotFoundError("powershell.exe")))


@pytest.mark.parametrize("collect", [
    collect_system_overview, collect_cpu_board_bios, collect_memory, collect_gpus, collect_storage,
    collect_network, collect_ports,
], ids=lambda f: f.__name__)
def test_default_sources_without_registry_or_powershell(monkeypatch, collect):
    """The REAL collectors with their REAL default sources, minus registry and PowerShell. Runs on any OS."""
    _locked_down_pc(monkeypatch)
    result = collect()
    assert_contract(result)
    fields = all_fields(result)
    # values that can only come from the registry / CIM must be reported as unavailable, never invented
    registry_only = {"os_edition", "manufacturer", "model", "cpu_name", "bios_version", "board_model", "gpu_name"}
    for f in fields:
        if f.key in registry_only:
            assert f.status is not Status.OK, f"{f.key} claims a value although registry and CIM were unreachable"


def test_a_whole_scan_survives_a_pc_without_registry_or_powershell(monkeypatch):
    from pcinsight.core.scan import run_scan
    _locked_down_pc(monkeypatch)
    result = run_scan()
    assert result.system.fields and all_fields(result.hardware)
    assert_contract(result.system)
    assert_contract(result.hardware)


# ---------------------------------------------------------------------------------------------------------------
# Windows versions and editions that return unexpected data


@pytest.mark.parametrize("registry", [
    # Windows 7 / 8 style: no DisplayVersion, no UBR
    {("SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", "ProductName"): "Windows 7 Professional",
     ("SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", "CurrentBuildNumber"): "7601"},
    # Server edition
    {("SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", "ProductName"): "Windows Server 2022 Datacenter",
     ("SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", "CurrentBuildNumber"): "20348",
     ("SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", "UBR"): 2527},
    # build number is not numeric, UBR is a string
    {("SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", "ProductName"): "Windows 10 Pro",
     ("SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", "CurrentBuildNumber"): "twenty-two",
     ("SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", "UBR"): "n/a"},
    # Insider / future build
    {("SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", "ProductName"): "Windows 11 Pro",
     ("SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", "CurrentBuildNumber"): "99999",
     ("SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", "UBR"): 1,
     ("SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion", "DisplayVersion"): "30H2"},
    {},
], ids=["win7", "server", "garbage-build", "future-build", "empty-registry"])
def test_unusual_windows_versions_never_crash_and_never_invent(registry):
    ov = collect_system_overview(make_sources(registry=registry))
    assert_contract(ov)
    if not registry:
        assert ov.get("os_edition").status is Status.UNAVAILABLE


@pytest.mark.parametrize("machine, platform_version", [
    ("", ""), ("ARM64", "10.0.26100"), ("x86", "6.1.7601"), ("Itanium", "5.2"), ("RISCV", "weird"),
])
def test_unknown_architectures_and_platform_strings(machine, platform_version):
    ov = collect_system_overview(make_sources(machine=lambda m=machine: m, platform_version=lambda p=platform_version: p))
    assert_contract(ov)
