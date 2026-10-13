import threading

from helpers import NOW, sample_device_sections, sample_hardware, sample_network_sections, sample_result
from pcinsight.core.network_info import NetworkScan
from pcinsight.core.scan import run_scan

NONE = lambda: []  # noqa: E731
NO_NET = lambda: NetworkScan([], [])  # noqa: E731


def test_scan_combines_collectors_in_order():
    base = sample_result()
    r = run_scan(lambda: base.system, sample_hardware, lambda: sample_device_sections()[:2], NONE, NONE, NO_NET)
    assert r.system is base.system and r.errors == []
    assert [s.key for s in r.hardware] == ["cpu", "motherboard", "bios", "memory", "memory_module_1"]
    assert r.section("cpu").title == "Processor (CPU)" and r.section("nope") is None
    assert [s.key for s in r.sections_for("memory")] == ["memory", "memory_module_1"]
    assert r.scanned_at == NOW and r.gateways == []


def test_prefix_matching_is_exact():
    base = sample_result()
    r = run_scan(lambda: base.system, NONE, lambda: sample_device_sections(), NONE, NONE, NO_NET)
    assert [s.key for s in r.sections_for("gpu")] == ["gpu_1"]
    assert [s.key for s in r.sections_for("storage", "volumes")] == ["storage_disk_1", "volumes"]
    assert r.sections_for("mem") == []


def test_network_sections_and_gateways_carried_through():
    base = sample_result()
    net = NetworkScan(sample_network_sections(), ["192.168.1.1"])
    r = run_scan(lambda: base.system, NONE, NONE, NONE, NONE, lambda: net)
    assert [s.key for s in r.network_sections()] == ["network", "net_adapter_1", "net_adapter_2"]
    assert r.gateways == ["192.168.1.1"] and r.errors == []
    assert [s.key for s in r.sections_for("net")] == ["net_adapter_1", "net_adapter_2"]


def test_failures_are_isolated_and_reported():
    base = sample_result()

    def boom():
        raise RuntimeError("secret-internal")

    r = run_scan(lambda: base.system, boom, lambda: sample_device_sections()[:1], boom, NONE, boom)
    assert r.system is base.system and [s.key for s in r.hardware] == ["memory"]
    assert len(r.errors) == 3
    for prefix in ("CPU, motherboard and BIOS", "Graphics", "Network"):
        assert any(e.startswith(prefix) for e in r.errors)
    assert all("RuntimeError" in e and "secret" not in e for e in r.errors)
    assert r.gateways == []


def test_collectors_run_concurrently():
    base = sample_result()
    barrier = threading.Barrier(5, timeout=5)

    def waits():
        barrier.wait()  # only passes if all five collectors are running at the same time
        return []

    def waits_net():
        barrier.wait()
        return NetworkScan([], [])

    r = run_scan(lambda: base.system, waits, waits, waits, waits, waits_net)
    assert r.errors == []
