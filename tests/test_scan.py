from helpers import NOW, sample_device_sections, sample_hardware, sample_result
from pcinsight.core.scan import run_scan

NONE = lambda: []  # noqa: E731


def test_scan_combines_collectors_in_order():
    base = sample_result()
    r = run_scan(lambda: base.system, sample_hardware, lambda: sample_device_sections()[:2], NONE, NONE)
    assert r.system is base.system and r.errors == []
    assert [s.key for s in r.hardware] == ["cpu", "motherboard", "bios", "memory", "memory_module_1"]
    assert r.section("cpu").title == "Processor (CPU)" and r.section("nope") is None
    assert [s.key for s in r.sections_for("memory")] == ["memory", "memory_module_1"]
    assert r.scanned_at == NOW


def test_prefix_matching_is_exact():
    base = sample_result()
    r = run_scan(lambda: base.system, NONE, lambda: sample_device_sections(), NONE, NONE)
    assert [s.key for s in r.sections_for("memory")] == ["memory", "memory_module_1"]
    assert [s.key for s in r.sections_for("gpu")] == ["gpu_1"]
    assert [s.key for s in r.sections_for("storage", "volumes")] == ["storage_disk_1", "volumes"]
    assert r.sections_for("mem") == []


def test_failures_are_isolated_and_reported():
    base = sample_result()

    def boom():
        raise RuntimeError("secret-internal")

    r = run_scan(lambda: base.system, boom, lambda: sample_device_sections()[:1], boom, NONE)
    assert r.system is base.system and [s.key for s in r.hardware] == ["memory"]
    assert len(r.errors) == 2
    assert any(e.startswith("CPU, motherboard and BIOS") for e in r.errors)
    assert any(e.startswith("Graphics") for e in r.errors)
    assert all("RuntimeError" in e and "secret" not in e for e in r.errors)


def test_collectors_run_concurrently():
    import threading
    base = sample_result()
    barrier = threading.Barrier(4, timeout=5)

    def waits():
        barrier.wait()  # only passes if all four collectors are running at the same time
        return []

    r = run_scan(lambda: base.system, waits, waits, waits, waits)
    assert r.errors == []
