from helpers import NOW, sample_hardware, sample_result
from pcinsight.core.scan import run_scan


def test_scan_combines_collectors():
    base = sample_result()
    r = run_scan(lambda: base.system, sample_hardware)
    assert r.system is base.system and r.errors == []
    assert [s.key for s in r.hardware] == ["cpu", "motherboard", "bios"]
    assert r.section("cpu").title == "Processor (CPU)" and r.section("nope") is None
    assert r.scanned_at == NOW


def test_hardware_failure_does_not_block_system_results():
    base = sample_result()

    def boom():
        raise RuntimeError("secret-internal")

    r = run_scan(lambda: base.system, boom)
    assert r.system is base.system and r.hardware == []
    assert len(r.errors) == 1 and "RuntimeError" in r.errors[0] and "secret" not in r.errors[0]
