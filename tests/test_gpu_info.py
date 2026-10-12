from helpers import GIB, make_device_sources
from pcinsight.core.common import CollectionError
from pcinsight.core.gpu_info import GPU_CLASS_KEY, collect_gpus
from pcinsight.core.models import Status

G1 = {"Name": "NVIDIA GeForce RTX 3080", "DriverVersion": "31.0.15.3623",
      "DriverDate": "/Date(1693526400000)/", "AdapterRAM": "4293918720"}
G2 = {"Name": "Intel(R) UHD Graphics 630", "DriverVersion": "30.0.101.1340",
      "DriverDate": "2022-05-01", "AdapterRAM": str(1 * GIB)}


def reg(**subs):
    out = {}
    for idx, (desc, vram) in subs.items():
        out[(f"{GPU_CLASS_KEY}\\{idx}", "DriverDesc")] = desc
        if vram is not None:
            out[(f"{GPU_CLASS_KEY}\\{idx}", "HardwareInformation.qwMemorySize")] = vram
    return out


def collect(rows, registry=None, **kw):
    return {s.key: s for s in collect_gpus(make_device_sources(
        registry=registry, cim_all=lambda c, p: rows, **kw))}


def test_vram_from_registry_beats_4gb_legacy_cap():
    secs = collect([G1, G2], reg(**{"0000": (G1["Name"], 10 * GIB)}))
    g1, g2 = secs["gpu_1"], secs["gpu_2"]
    assert g1.title.endswith("NVIDIA GeForce RTX 3080")
    assert g1.get("vram").value == "10 GB" and "registry" in g1.get("vram").source
    assert g1.get("driver_version").value == "31.0.15.3623" and "vendor may show" in g1.get("driver_version").note
    assert g1.get("driver_date").value == "2023-09-01"
    assert g2.get("vram").value == "1 GB" and g2.get("driver_date").value == "2022-05-01"
    assert "share system memory" in g1.note


def test_legacy_cap_is_not_reported_as_exact():
    for capped in ("4293918720", "4294967295"):  # values Windows reports for cards with 4 GB or more
        f = collect([{**G1, "AdapterRAM": capped}])["gpu_1"].get("vram")
        assert f.status is Status.OK and f.value == "4 GB or more" and "at most 4 GB" in f.note
    f = collect([{**G1, "AdapterRAM": str(2 * GIB)}])["gpu_1"].get("vram")
    assert f.value == "2 GB"  # a genuine 2 GB card is still reported exactly


def test_registry_value_as_binary_bytes():
    raw = (6 * GIB).to_bytes(8, "little")
    f = collect([G1], reg(**{"0000": (G1["Name"], raw)}))["gpu_1"].get("vram")
    assert f.value == "6 GB"


def test_identical_cards_map_to_separate_registry_keys():
    secs = collect([G1, G1], reg(**{"0000": (G1["Name"], 8 * GIB), "0001": (G1["Name"], 12 * GIB)}))
    assert secs["gpu_1"].get("vram").value == "8 GB" and secs["gpu_2"].get("vram").value == "12 GB"


def test_vram_unavailable_when_nothing_reported():
    f = collect([{**G2, "AdapterRAM": ""}])["gpu_1"].get("vram")
    assert f.status is Status.UNAVAILABLE


def test_missing_name_and_unknown_date_format():
    sec = collect([{**G2, "Name": "", "DriverDate": "Spring"}])["gpu_1"]
    assert sec.get("gpu_name").value == "Unknown adapter" and sec.title == "Graphics adapter 1"
    assert "not recognised" in sec.get("driver_date").note


def test_cim_failure_gives_single_unavailable_section():
    def cim(c, p):
        raise CollectionError("The PowerShell query timed out")
    secs = collect_gpus(make_device_sources(cim_all=cim))
    assert len(secs) == 1 and secs[0].get("gpus").status is Status.UNAVAILABLE
    assert "timed out" in secs[0].get("gpus").note


def test_zero_adapters():
    secs = collect_gpus(make_device_sources(cim_all=lambda c, p: []))
    assert "no graphics adapters" in secs[0].get("gpus").note.lower()


def test_unexpected_registry_exception_contained():
    def boom(path, name):
        raise RuntimeError("secret")
    sec = collect_gpus(make_device_sources(registry=None, cim_all=lambda c, p: [G1], ))[0]
    assert sec.get("gpu_name").status is Status.OK
    secs = collect_gpus(make_device_sources(cim_all=lambda c, p: [G1], registry=boom))
    f = secs[0].get("vram")
    assert f.status is Status.UNAVAILABLE and "secret" not in f.note


def test_default_sources_never_crash():
    assert collect_gpus()[0].key.startswith("gpu")
