"""Real-machine checks. Windows only. Run with: python -m pytest tests/test_system_integration.py -s"""
import os
import re
import sys

import pytest

from pcinsight.core.models import Status
from pcinsight.core.system_info import collect_system_overview

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only integration test")


@pytest.fixture(scope="module")
def overview():
    ov = collect_system_overview()
    for f in ov.fields:
        print(f"{f.label:22} {f.status.value:12} {f.value or f.note}")
    return ov


def test_core_fields_present(overview):
    for key in ("computer_name", "os_edition", "os_build", "architecture", "last_boot", "uptime"):
        assert overview.get(key).status is Status.OK, key


def test_values_match_the_machine(overview):
    assert overview.get("computer_name").value.lower() == os.environ["COMPUTERNAME"].lower()
    assert re.match(r"^\d{5}(\.\d+)?$", overview.get("os_build").value)
    assert overview.get("os_edition").value.startswith("Windows")


# ---- Module 3 real-machine checks ----
from pcinsight.core.cpu_board_info import collect_cpu_board_bios  # noqa: E402


@pytest.fixture(scope="module")
def hardware():
    secs = {s.key: s for s in collect_cpu_board_bios()}
    for s in secs.values():
        print(f"\n== {s.title} ==")
        for f in s.fields:
            print(f"{f.label:30} {f.status.value:12} {f.value or f.note}")
    return secs


def test_cpu_real_data(hardware):
    cpu = hardware["cpu"]
    for key in ("cpu_name", "cpu_manufacturer", "physical_cores", "logical_processors"):
        assert cpu.get(key).status is Status.OK, key
    assert int(cpu.get("logical_processors").value) >= int(cpu.get("physical_cores").value) >= 1


def test_bios_real_data(hardware):
    assert hardware["bios"].get("bios_version").status is Status.OK


def test_chipset_reported_as_unsupported(hardware):
    assert hardware["motherboard"].get("chipset").status is Status.UNSUPPORTED


# ---- Module 4 real-machine checks ----
from pcinsight.core.gpu_info import collect_gpus  # noqa: E402
from pcinsight.core.memory_info import collect_memory  # noqa: E402
from pcinsight.core.storage_info import collect_storage  # noqa: E402


def _show(secs):
    for s in secs:
        print(f"\n== {s.title} ==")
        for f in s.fields:
            print(f"{f.label:36} {f.status.value:12} {f.value or f.note}")


def test_memory_real_data():
    secs = collect_memory()
    _show(secs)
    m = secs[0]
    assert m.get("total_physical").status is Status.OK and m.get("available").status is Status.OK


def test_gpu_real_data():
    secs = collect_gpus()
    _show(secs)
    assert secs[0].key.startswith("gpu_") and secs[0].get("gpu_name").status is Status.OK


def test_storage_real_data():
    secs = collect_storage()
    _show(secs)
    disks = [s for s in secs if s.key.startswith("storage_disk_")]
    assert disks and disks[0].get("capacity").status is Status.OK
    vols = next(s for s in secs if s.key == "volumes")
    assert any(f.status is Status.OK for f in vols.fields)


# ---- Module 5 real-machine checks ----
from pcinsight.core.connectivity import run_connectivity_checks  # noqa: E402
from pcinsight.core.network_info import collect_network  # noqa: E402


def test_network_real_data():
    scan = collect_network()
    for s in scan.sections:
        print(f"\n== {s.title} ==")
        for f in s.fields:
            print(f"{f.label:18} {f.status.value:12} {f.value or f.note}")
    print("\nDefault IPv4 gateways:", scan.gateways)
    adapters = [s for s in scan.sections if s.key.startswith("net_adapter_")]
    assert adapters
    assert any(s.get("status").status is Status.OK and s.get("mac").status is Status.OK for s in adapters)
    assert any(s.get("ipv4").status is Status.OK for s in adapters)


def test_connectivity_runs_without_crashing():
    """Sends real probes (gateway ping, TCP 1.1.1.1:443, DNS lookup). Passes offline too."""
    res = run_connectivity_checks(collect_network().gateways)
    for f in res.sections[0].fields:
        print(f"{f.label:36} {f.status.value:12} {f.value or f.note}")
    assert {"internet", "dns"} <= {f.key for f in res.sections[0].fields}
