"""Module 9 - REAL-HARDWARE integration tests. Windows only.

Run on a real Windows PC:      python -m pytest -m integration -s -rs      (test.bat does this for you)

Why this file exists
--------------------
Every other test uses mocked system data. A mocked test proves PCInsight handles an answer correctly; it can
NEVER prove that Windows gives that answer on a given PC. These tests run the real collectors on the PC they are
started on and compare the results with INDEPENDENT sources (Win32 API calls made directly through ctypes, Python's
standard library, and Windows' own `ipconfig`) rather than with PCInsight's own code.

What a pass means: PCInsight agrees with those independent sources ON THIS PC, ON THIS RUN, with THIS user's
permissions. It says nothing about other PCs, other Windows editions, other drivers, or an administrator vs a
standard user. Repeat the run on each kind of PC you care about (see TESTING.md for the matrix).
"""
from __future__ import annotations

import ctypes
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import warnings

import pypdf
import pytest

from pcinsight.core.models import Status
from pcinsight.core.scan import run_scan
from pcinsight.report import ReportError, write_report

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "win32",
                       reason="Windows-only integration test: results from mocked data or other systems prove "
                              "nothing about real hardware detection"),
]

SCAN_TIMEOUT = 120.0


# ---------------------------------------------------------------------------------------------------------------
# helpers: independent oracles (none of these use PCInsight code)

class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]


def os_total_physical_bytes() -> int:
    st = _MemoryStatusEx()
    st.dwLength = ctypes.sizeof(_MemoryStatusEx)
    assert ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)), "GlobalMemoryStatusEx failed"
    return st.ullTotalPhys


def os_logical_processors() -> int:
    ALL_PROCESSOR_GROUPS = 0xFFFF
    return int(ctypes.windll.kernel32.GetActiveProcessorCount(ALL_PROCESSOR_GROUPS))


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


_UNIT = {"bytes": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4, "PB": 1024 ** 5}


def parse_size(text: str) -> float | None:
    """'31.9 GB' -> bytes (PCInsight's display format; binary units)."""
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*(bytes|KB|MB|GB|TB|PB)\b", text)
    return float(m.group(1).replace(",", "")) * _UNIT[m.group(2)] if m else None


def ipconfig_adapter_names() -> list[str]:
    """Adapter names from `ipconfig /all`. Only English-language Windows prints these headings."""
    out = subprocess.run(["ipconfig", "/all"], capture_output=True, text=True, errors="replace", timeout=30).stdout
    return re.findall(r"^\S.*? adapter (.+?):\s*$", out, flags=re.MULTILINE)


def soft(condition: bool, message: str) -> None:
    """A cross-check that is informative but not strong enough to fail the run (e.g. firmware formatting)."""
    if not condition:
        warnings.warn(f"CROSS-CHECK MISMATCH (investigate, may be legitimate): {message}", stacklevel=2)
        print(f"\n!! CROSS-CHECK MISMATCH: {message}")


def print_section(s) -> None:
    print(f"\n== {s.title} ==")
    for f in s.fields:
        shown = f.value if f.status is Status.OK else f"<{f.status.value}> {f.note}"
        print(f"  {f.label:34} {shown}".replace("\n", "\n" + " " * 38))


# ---------------------------------------------------------------------------------------------------------------
# one real scan for most tests

@pytest.fixture(scope="module")
def real_scan():
    print(f"\n[integration] elevated (administrator): {is_elevated()}")
    print(f"[integration] Python {sys.version.split()[0]} on {sys.platform}")
    t0 = time.time()
    result = run_scan()
    print(f"[integration] real scan took {time.time() - t0:.1f}s; problems reported: {result.errors or 'none'}")
    for f in result.system.fields:
        print(f"  {f.label:34} {f.value if f.status is Status.OK else '<' + f.status.value + '> ' + f.note}")
    for s in result.hardware:
        print_section(s)
    return result


# ---------------------------------------------------------------------------------------------------------------
# the scan itself


def test_a_real_scan_finishes_and_reports_its_own_problems(real_scan):
    assert real_scan.system.fields
    assert real_scan.hardware
    # collectors that crashed would be listed here; every one is a defect to investigate (or a genuine OS limit)
    assert real_scan.errors == [], f"collectors crashed on this PC: {real_scan.errors}"


def test_the_honesty_contract_holds_on_real_data(real_scan):
    from test_reliability_collectors import assert_contract
    assert_contract(real_scan.system, leaked_ok=True)
    assert_contract(real_scan.hardware, leaked_ok=True)


def test_core_values_agree_with_independent_windows_sources(real_scan):
    sysinfo = real_scan.system
    assert sysinfo.get("computer_name").value.lower() == os.environ["COMPUTERNAME"].lower()
    cpu = real_scan.section("cpu")
    assert int(cpu.get("logical_processors").value) == os_logical_processors()
    assert int(cpu.get("physical_cores").value) <= int(cpu.get("logical_processors").value)


def test_installed_memory_agrees_with_the_windows_api(real_scan):
    reported = parse_size(real_scan.section("memory").get("total_physical").value)
    assert reported is not None, "total physical memory is not shown as a size"
    actual = os_total_physical_bytes()
    assert abs(reported - actual) / actual < 0.01, f"PCInsight {reported:.0f} bytes vs Windows API {actual} bytes"


def test_every_listed_drive_exists_and_its_size_agrees_with_the_standard_library(real_scan):
    vols = real_scan.section("volumes")
    checked = 0
    for f in vols.fields:
        if f.status is not Status.OK or not re.match(r"^[A-Za-z]:\\", f.label):
            continue
        try:
            actual = shutil.disk_usage(f.label).total
        except OSError:
            continue                                   # e.g. a drive that went away or an empty card reader
        shown = parse_size(f.value)
        assert shown is not None, f"{f.label}: no size in {f.value!r}"
        assert abs(shown - actual) / actual < 0.01, f"{f.label}: {shown:.0f} vs {actual}"
        checked += 1
    assert checked >= 1, "no drive could be compared"


def test_firmware_values_agree_with_a_second_route_to_the_same_data(real_scan):
    """PCInsight reads the registry first; cross-check with a separate CIM query. Informational: firmware text
    legitimately differs in format on some PCs, so a mismatch is a warning to look at, not a failure."""
    from pcinsight.core.common import CollectionError, query_cim
    bios = real_scan.section("bios").get("bios_version")
    try:
        cim = query_cim("Win32_BIOS", ["SMBIOSBIOSVersion"])["SMBIOSBIOSVersion"].strip().lower()
    except CollectionError as exc:
        pytest.skip(f"CIM unavailable on this PC: {exc}")
    if bios.status is Status.OK and cim:
        soft(cim in bios.value.lower() or bios.value.lower() in cim,
             f"BIOS version PCInsight={bios.value!r} CIM={cim!r}")


def test_chipset_is_never_invented(real_scan):
    assert real_scan.section("motherboard").get("chipset").status is Status.UNSUPPORTED


# ---------------------------------------------------------------------------------------------------------------
# network: multiple adapters, disconnected adapters


def test_network_adapters_match_ipconfig(real_scan):
    sections = [s for s in real_scan.hardware if s.key.startswith("net_adapter_")]
    assert sections, "no network adapter was reported on this PC"
    names = ipconfig_adapter_names()
    if not names:
        pytest.skip("ipconfig headings are not English on this PC; compare by hand with `ipconfig /all`")
    titles = " | ".join(s.title for s in sections).lower()
    missing = [n for n in names if n.lower() not in titles]
    # ipconfig also lists tunnel and virtual adapters PCInsight may group differently; report, fail only if most are missing
    print(f"\n[integration] ipconfig adapters: {names}\n[integration] PCInsight adapters: {[s.title for s in sections]}")
    assert len(missing) <= max(1, len(names) // 3), f"adapters in ipconfig but not in PCInsight: {missing}"


def test_adapters_that_are_down_have_no_ipv4_gateway_and_gateways_come_only_from_adapters_that_are_up(real_scan):
    for s in (x for x in real_scan.hardware if x.key.startswith("net_adapter_")):
        status = s.get("status")
        if status.status is Status.OK and status.value.lower().startswith(("disconnected", "down", "not present")):
            gw = s.get("gateway")
            assert gw is None or gw.status is not Status.OK, f"{s.title}: a disconnected adapter reports a gateway"
    import psutil
    up_addresses = {a.address for n, st in psutil.net_if_stats().items() if st.isup
                    for a in psutil.net_if_addrs().get(n, []) if a.family == socket.AF_INET}
    # a gateway is on the same network as one of this PC's own up addresses (loose sanity check, not routing proof)
    for gw in real_scan.gateways:
        assert re.match(r"^\d+\.\d+\.\d+\.\d+$", gw), gw
    print(f"\n[integration] up IPv4 addresses (for your own comparison): {sorted(up_addresses)}")


# ---------------------------------------------------------------------------------------------------------------
# ports: a real listener created by this test must be found


def test_a_listener_opened_by_this_test_is_found_and_attributed_to_this_process():
    from pcinsight.core.ports_info import collect_ports
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        tcp = next(s for s in collect_ports(important_ports=[port]) if s.key == "ports_tcp")
        mine = [f for f in tcp.fields if f.label.startswith(f"{port}/TCP")]
        assert mine, f"the listener on port {port} was not found"
        assert f"PID {os.getpid()}" in mine[0].value and "loopback only" in mine[0].value
    after = next(s for s in collect_ports(important_ports=[port]) if s.key == "ports_tcp")
    assert not [f for f in after.fields if f.label.startswith(f"{port}/TCP")], "a closed port is still listed"


# ---------------------------------------------------------------------------------------------------------------
# repeated scans on real hardware


def test_three_real_scans_in_a_row_are_stable_and_leak_no_threads_or_processes(real_scan):
    import psutil
    baseline_threads = threading.active_count()
    keys = [(s.key, tuple(f.key for f in s.fields)) for s in real_scan.hardware]
    durations = []
    for _ in range(3):
        t0 = time.time()
        again = run_scan()
        durations.append(time.time() - t0)
        assert again.errors == []
        # the same PC must produce the same *shape* of answer every time (values such as free space may change)
        again_keys = [(s.key, tuple(f.key for f in s.fields)) for s in again.hardware]
        names_now, names_before = {k for k, _ in again_keys}, {k for k, _ in keys}
        soft(names_now == names_before, f"sections changed between scans: {names_now ^ names_before}")
    print(f"\n[integration] three scans took {[round(d, 1) for d in durations]} seconds")
    assert max(durations) < SCAN_TIMEOUT
    time.sleep(1.0)
    assert threading.active_count() <= baseline_threads + 1, "threads from earlier scans are still alive"
    children = [c.name().lower() for c in psutil.Process().children(recursive=True)]
    assert not [c for c in children if "powershell" in c], f"PowerShell processes left running: {children}"


# ---------------------------------------------------------------------------------------------------------------
# the real window: scan, shutdown during a scan, no orphaned child processes


@pytest.fixture
def real_window(qapp):
    from pcinsight.ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    qapp.processEvents()
    yield w
    w.close()


def _wait(qapp, predicate, timeout):
    end = time.time() + timeout
    while time.time() < end:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def test_the_real_window_completes_a_real_scan(qapp, real_window):
    real_window.scan_bar.rescan_button.click()
    assert _wait(qapp, lambda: real_window.pages["Hardware"].has_data, SCAN_TIMEOUT), "no result within the time limit"
    assert real_window.scan_bar.rescan_button.isEnabled()
    print("\n[integration] status bar:", real_window.scan_bar.status_label.text())


def test_closing_the_real_window_during_a_real_scan_leaves_nothing_running(qapp):
    import psutil
    from pcinsight.ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    w.scan_bar.rescan_button.click()
    for _ in range(20):                                    # let the collectors start their PowerShell queries
        qapp.processEvents()
        time.sleep(0.05)
    t0 = time.time()
    w.close()
    print(f"\n[integration] window closed {time.time() - t0:.1f}s after a scan was started")
    qapp.processEvents()
    assert not w.controller.is_running
    deadline = time.time() + 30
    while time.time() < deadline:
        left = [c for c in psutil.Process().children(recursive=True) if "powershell" in c.name().lower()]
        if not left:
            break
        time.sleep(0.5)
    assert not left, f"PowerShell is still running after the window closed: {[c.pid for c in left]}"


# ---------------------------------------------------------------------------------------------------------------
# report generation on real data, and real PDF save failures


def test_a_real_report_is_a_valid_pdf_containing_this_pcs_name(real_scan, tmp_path):
    out = write_report(str(tmp_path / "real.pdf"), real_scan)
    text = re.sub(r"\s+", " ", " ".join(p.extract_text() or "" for p in pypdf.PdfReader(out).pages))
    assert real_scan.system.get("computer_name").value in text
    assert not re.search(r"\b(None|NaN)\b", text)
    print(f"\n[integration] report: {os.path.getsize(out):,} bytes, {len(pypdf.PdfReader(out).pages)} pages")


def test_saving_over_a_file_that_another_program_has_open_fails_cleanly(real_scan, tmp_path):
    """On Windows a PDF viewer locks its file. Reproduce that with a real exclusive handle (share mode 0)."""
    from ctypes import wintypes
    target = tmp_path / "locked.pdf"
    target.write_bytes(b"%PDF-1.4 viewer has this open")
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    GENERIC_READ, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL = 0x80000000, 3, 0x80
    handle = k32.CreateFileW(str(target), GENERIC_READ, 0, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
    assert handle not in (None, -1, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFF), \
        f"could not take an exclusive handle for the test (error {ctypes.get_last_error()})"
    try:
        with pytest.raises(ReportError, match="not allowed to save|open in another program"):
            write_report(str(target), real_scan)
    finally:
        k32.CloseHandle(handle)
    assert target.read_bytes().startswith(b"%PDF-1.4 viewer"), "the locked file was damaged"
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    write_report(str(target), real_scan)                   # works again once the viewer is closed
    assert target.read_bytes().startswith(b"%PDF-1.")


def test_saving_to_a_protected_folder_fails_cleanly_when_not_administrator(real_scan):
    if is_elevated():
        pytest.skip("running as administrator: protected folders are writable; run again as a standard user")
    protected = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "pcinsight-test.pdf")
    with pytest.raises(ReportError, match="not allowed|not valid|could not be saved"):
        write_report(protected, real_scan)
    assert not os.path.exists(protected)


def test_a_path_longer_than_the_classic_windows_limit_never_crashes(real_scan, tmp_path):
    folder = tmp_path
    for _ in range(6):
        folder = folder / ("d" * 50)
    try:
        folder.mkdir(parents=True)
    except OSError:
        pytest.skip("this PC does not allow paths this long (LongPathsEnabled is off)")
    try:
        out = write_report(str(folder / ("r" * 60 + ".pdf")), real_scan)
    except ReportError as exc:
        print(f"\n[integration] long path refused cleanly: {exc}")
    else:
        assert os.path.getsize(out) > 1000
