import pytest

from helpers import CPU_REGISTRY, NOW, make_cpu_sources
from pcinsight.core.common import CollectionError
from pcinsight.core.cpu_board_info import (BIOS_KEY, collect_cpu_board_bios, default_sources,
                                           normalize_bios_date)
from pcinsight.core.models import Status


def collect(**kw):
    secs = collect_cpu_board_bios(make_cpu_sources(**kw))
    return {s.key: s for s in secs}


def test_sections_and_all_fields_ok():
    secs = collect()
    assert list(secs) == ["cpu", "motherboard", "bios"]
    cpu, board, bios = secs["cpu"], secs["motherboard"], secs["bios"]
    assert cpu.get("cpu_name").value == "Intel(R) Core(TM) i7-9700K CPU @ 3.60GHz"  # whitespace tidied
    assert cpu.get("cpu_manufacturer").value == "Intel"
    assert cpu.get("physical_cores").value == "8"
    assert cpu.get("logical_processors").value == "16"
    assert cpu.get("cpu_frequency").value == "3,600 MHz (3.60 GHz)"
    assert board.get("board_manufacturer").value == "ASUSTeK COMPUTER INC."
    assert board.get("board_model").value == "PRIME Z390-A"
    assert bios.get("bios_vendor").value == "American Megatrends Inc."
    assert bios.get("bios_version").value == "2401"
    assert bios.get("bios_date").value == "2023-03-15"
    assert all(s.collected_at == NOW for s in secs.values())


def test_cpu_note_explains_cores_belong_to_cpu():
    assert "not the motherboard" in collect()["cpu"].note


def test_chipset_is_never_invented():
    reg = {**CPU_REGISTRY, (BIOS_KEY, "Chipset"): "Z390", (BIOS_KEY, "BaseBoardVersion"): "Z390"}
    f = collect(registry=reg)["motherboard"].get("chipset")
    assert f.status is Status.UNSUPPORTED and f.value is None and "does not" in f.note
    # expected-unsupported data must not count as a scan problem
    assert collect()["motherboard"].unavailable_count == 0


def test_unknown_vendor_shown_raw_with_note():
    reg = {**CPU_REGISTRY, ("HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0", "VendorIdentifier"): "Qualcomm"}
    f = collect(registry=reg)["cpu"].get("cpu_manufacturer")
    assert f.value == "Qualcomm" and "as reported" in f.note


def test_amd_vendor_mapped():
    reg = {**CPU_REGISTRY, ("HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0", "VendorIdentifier"): "AuthenticAMD"}
    assert collect(registry=reg)["cpu"].get("cpu_manufacturer").value == "AMD"


def test_registry_missing_everything_marks_unavailable_not_crash():
    secs = collect(registry={})
    for key in ("cpu_name", "cpu_manufacturer"):
        f = secs["cpu"].get(key)
        assert f.status is Status.UNAVAILABLE and "Registry:" in f.note and "CIM:" in f.note
    # psutil-based fields are unaffected
    assert secs["cpu"].get("physical_cores").status is Status.OK
    for sec in ("motherboard", "bios"):
        assert any(f.status is Status.UNAVAILABLE for f in secs[sec].fields)


def test_cim_fallback_for_each_class():
    answers = {"Win32_Processor": {"Name": "CIM CPU", "Manufacturer": "AuthenticAMD"},
               "Win32_BaseBoard": {"Manufacturer": "CimBoardCo", "Product": "CimBoard"},
               "Win32_BIOS": {"Manufacturer": "CimBios", "SMBIOSBIOSVersion": "V1", "ReleaseDate": "/Date(1678838400000)/"}}
    calls = []

    def cim(cls, props):
        calls.append(cls)
        return {props[0]: answers[cls][props[0]]}

    secs = collect(registry={}, cim_query=cim)
    assert secs["cpu"].get("cpu_name").value == "CIM CPU"
    assert secs["cpu"].get("cpu_manufacturer").value == "AMD"
    assert secs["motherboard"].get("board_model").value == "CimBoard"
    assert secs["bios"].get("bios_version").value == "V1"
    assert secs["bios"].get("bios_date").value == "2023-03-15"
    assert "CIM" in secs["bios"].get("bios_vendor").source
    assert {"Win32_Processor", "Win32_BaseBoard", "Win32_BIOS"} <= set(calls)


def test_placeholder_board_values_flagged_not_hidden():
    reg = {**CPU_REGISTRY, (BIOS_KEY, "BaseBoardProduct"): "Default string"}
    f = collect(registry=reg)["motherboard"].get("board_model")
    assert f.status is Status.OK and f.value == "Default string" and "placeholder" in f.note


def test_empty_vs_unavailable():
    reg = {**CPU_REGISTRY, (BIOS_KEY, "BIOSVersion"): "  "}
    assert collect(registry=reg)["bios"].get("bios_version").status is Status.EMPTY
    reg2 = {k: v for k, v in CPU_REGISTRY.items() if k[1] != "BIOSVersion"}
    assert collect(registry=reg2)["bios"].get("bios_version").status is Status.UNAVAILABLE


@pytest.mark.parametrize("phys,logi", [(None, None), (0, 0)])
def test_counts_not_reported(phys, logi):
    cpu = collect(cpu_count=lambda logical: logi if logical else phys)["cpu"]
    assert cpu.get("physical_cores").status is Status.UNAVAILABLE
    assert cpu.get("logical_processors").status is Status.UNAVAILABLE


@pytest.mark.parametrize("val", [None, 0, -5.0])
def test_frequency_not_reported(val):
    f = collect(cpu_freq_mhz=lambda: val)["cpu"].get("cpu_frequency")
    assert f.status is Status.UNAVAILABLE


def test_unexpected_exceptions_contained():
    def boom(*a):
        raise RuntimeError("secret-internal")
    secs = collect(cpu_count=boom, cpu_freq_mhz=boom)
    for key in ("physical_cores", "logical_processors", "cpu_frequency"):
        f = secs["cpu"].get(key)
        assert f.status is Status.UNAVAILABLE and "secret" not in f.note
    assert secs["cpu"].get("cpu_name").status is Status.OK


def test_long_names_preserved():
    long = "X" * 200
    reg = {**CPU_REGISTRY, (BIOS_KEY, "BaseBoardProduct"): long}
    assert collect(registry=reg)["motherboard"].get("board_model").value == long


@pytest.mark.parametrize("raw,expected", [
    ("03/15/2023", ("2023-03-15", "")),
    ("2023-03-15", ("2023-03-15", "")),
    ("20230315000000.000000+000", ("2023-03-15", "")),
    ("/Date(1678838400000)/", ("2023-03-15", "")),
    ("", ("", "")),
])
def test_bios_date_formats(raw, expected):
    assert normalize_bios_date(raw) == expected


def test_bios_date_two_digit_year_and_unrecognised():
    d, note = normalize_bios_date("03/15/23")
    assert d == "2023-03-15" and "two-digit" in note
    d, note = normalize_bios_date("Spring 2023")
    assert d == "Spring 2023" and "not recognised" in note
    d, note = normalize_bios_date("99/99/9999")
    assert d == "99/99/9999" and "not recognised" in note


def test_default_sources_never_crash():
    secs = collect_cpu_board_bios()  # real machine, whatever the OS
    assert len(secs) == 3 and sum(len(s.fields) for s in secs) == 11
    assert secs[1].get("chipset").status is Status.UNSUPPORTED
