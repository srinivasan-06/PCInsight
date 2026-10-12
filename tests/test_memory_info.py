import pytest

from helpers import GIB, NOW, make_device_sources
from pcinsight.core.common import CollectionError
from pcinsight.core.memory_info import MODULE_FIELDS, collect_memory
from pcinsight.core.models import Status

MODULE = {"Capacity": str(16 * GIB), "SMBIOSMemoryType": "26", "Speed": "3200",
          "ConfiguredClockSpeed": "3200", "Manufacturer": "Corsair", "PartNumber": "CMK32GX4M2 ",
          "DeviceLocator": "DIMM_A1"}


def cim_for(modules=None, slots="4"):
    def cim(cls, props):
        if cls == "Win32_PhysicalMemory":
            if modules is None:
                raise CollectionError("The PowerShell query timed out")
            return modules
        if cls == "Win32_PhysicalMemoryArray":
            if slots is None:
                raise CollectionError("PowerShell was not found")
            return [{"MemoryDevices": slots}]
        raise AssertionError(cls)
    return cim


def collect(**kw):
    return {s.key: s for s in collect_memory(make_device_sources(**kw))}


def test_full_memory_report():
    secs = collect(cim_all=cim_for([MODULE, {**MODULE, "DeviceLocator": "DIMM_B1", "PartNumber": "X2"}]))
    assert list(secs) == ["memory", "memory_module_1", "memory_module_2"]
    m = secs["memory"]
    assert m.get("total_physical").value == "32 GB"
    assert m.get("available").value == "8 GB"
    assert m.get("in_use").value == "24 GB (75%)"
    assert m.get("installed").value == "32 GB"
    assert m.get("slots_total").value == "4" and m.get("slots_used").value == "2"
    mod = secs["memory_module_1"]
    assert mod.title == "Memory module 1 \u2014 DIMM_A1"
    assert mod.get("capacity").value == "16 GB" and mod.get("type").value == "DDR4"
    assert mod.get("speed").value == "3,200 MHz" and mod.get("configured_speed").value == "3,200 MHz"
    assert mod.get("manufacturer").value == "Corsair" and mod.get("part_number").value == "CMK32GX4M2"
    assert "MHz" in mod.note and "Serial numbers" in mod.note
    assert all(f.status is Status.OK for s in secs.values() for f in s.fields)


def test_physical_vs_available_are_separate_fields():
    m = collect(cim_all=cim_for([MODULE]))["memory"]
    assert m.get("total_physical").value != m.get("available").value


def test_serial_numbers_never_requested():
    asked = []

    def cim(cls, props):
        asked.extend(props)
        return [MODULE] if cls == "Win32_PhysicalMemory" else [{"MemoryDevices": "4"}]

    collect(cim_all=cim)
    assert not any("serial" in p.lower() for p in asked)
    assert not any("serial" in p.lower() for p in MODULE_FIELDS)


@pytest.mark.parametrize("code,text", [(26, "DDR4"), (34, "DDR5"), (24, "DDR3"), (30, "LPDDR4")])
def test_memory_type_codes(code, text):
    mod = collect(cim_all=cim_for([{**MODULE, "SMBIOSMemoryType": str(code)}]))["memory_module_1"]
    assert mod.get("type").value == text


@pytest.mark.parametrize("code", ["0", "2", ""])
def test_memory_type_not_reported(code):
    mod = collect(cim_all=cim_for([{**MODULE, "SMBIOSMemoryType": code}]))["memory_module_1"]
    assert mod.get("type").status is Status.UNAVAILABLE


def test_unrecognised_type_code_not_invented():
    f = collect(cim_all=cim_for([{**MODULE, "SMBIOSMemoryType": "99"}]))["memory_module_1"].get("type")
    assert f.status is Status.OK and "Unknown type" in f.value and "99" in f.value


def test_cim_failure_keeps_psutil_data():
    secs = collect(cim_all=cim_for(None))
    m = secs["memory"]
    assert m.get("total_physical").status is Status.OK
    for key in ("installed", "slots_used"):
        assert m.get(key).status is Status.UNAVAILABLE and "timed out" in m.get(key).note
    f = secs["memory_modules"].get("modules")
    assert f.status is Status.UNAVAILABLE and "timed out" in f.note


def test_no_modules_reported_virtual_machine():
    secs = collect(cim_all=cim_for([]))
    assert "virtual machines" in secs["memory_modules"].get("modules").note


def test_missing_capacity_makes_installed_unavailable():
    secs = collect(cim_all=cim_for([MODULE, {**MODULE, "Capacity": ""}]))
    assert secs["memory"].get("installed").status is Status.UNAVAILABLE
    assert secs["memory_module_2"].get("capacity").status is Status.UNAVAILABLE
    assert secs["memory_module_1"].get("capacity").status is Status.OK


@pytest.mark.parametrize("speed", ["", "0", None])
def test_speed_not_reported(speed):
    mod = collect(cim_all=cim_for([{**MODULE, "Speed": speed, "ConfiguredClockSpeed": speed}]))["memory_module_1"]
    assert mod.get("speed").status is Status.UNAVAILABLE


def test_placeholder_manufacturer_flagged():
    mod = collect(cim_all=cim_for([{**MODULE, "Manufacturer": "Unknown"}]))["memory_module_1"]
    assert "placeholder" in mod.get("manufacturer").note


def test_slots_failure_is_isolated():
    secs = collect(cim_all=cim_for([MODULE], slots=None))
    assert secs["memory"].get("slots_total").status is Status.UNAVAILABLE
    assert secs["memory"].get("slots_used").value == "1"


def test_psutil_failure_and_inconsistent_values():
    def boom():
        raise RuntimeError("secret")
    m = collect(cim_all=cim_for([MODULE]), memory_stats=boom)["memory"]
    for key in ("total_physical", "available", "in_use"):
        assert m.get(key).status is Status.UNAVAILABLE and "secret" not in m.get(key).note
    assert m.get("installed").status is Status.OK
    m2 = collect(cim_all=cim_for([MODULE]), memory_stats=lambda: (GIB, 2 * GIB))["memory"]
    assert m2.get("total_physical").status is Status.UNAVAILABLE and "inconsistent" in m2.get("total_physical").note


def test_default_sources_never_crash():
    secs = collect_memory()
    assert secs[0].key == "memory" and len(secs[0].fields) == 6
