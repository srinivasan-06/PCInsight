import subprocess
from types import SimpleNamespace

import pytest

from helpers import BASE_REGISTRY, BIOS_KEY, CV_KEY, NOW, make_sources, no_cim
from pcinsight.core import system_info as si
from pcinsight.core.models import Status
from pcinsight.core.system_info import CollectionError, collect_system_overview, format_uptime


def collect(**kw):
    return collect_system_overview(make_sources(**kw))


def test_all_fields_ok():
    ov = collect()
    assert [f.status for f in ov.fields] == [Status.OK] * 9
    assert ov.get("computer_name").value == "TEST-PC"
    assert ov.get("os_version").value == "23H2"
    assert ov.get("os_build").value == "22631.3593"
    assert ov.get("architecture").value == "x64 (AMD64)"
    assert ov.get("manufacturer").value == "Acme Corp"
    assert ov.get("model").value == "Widget 9"
    assert ov.get("last_boot").value == "2026-10-11 10:55"
    assert ov.get("uptime").value == "1 day, 1 hour, 5 minutes"
    assert ov.collected_at == NOW and ov.unavailable_count == 0


def test_windows_11_label_corrected_from_build_number():
    f = collect().get("os_edition")
    assert f.value == "Windows 11 Pro" and "corrected" in f.note


def test_windows_10_label_not_changed():
    reg = {**BASE_REGISTRY, (CV_KEY, "CurrentBuildNumber"): "19045"}
    f = collect(registry=reg).get("os_edition")
    assert f.value == "Windows 10 Pro" and f.note == ""


def test_registry_failure_marks_unavailable_without_crashing():
    ov = collect(registry={})
    assert ov.get("os_edition").status is Status.UNAVAILABLE
    assert ov.get("os_version").status is Status.UNAVAILABLE
    assert ov.get("manufacturer").status is Status.UNAVAILABLE
    # other collectors unaffected; build falls back to the platform module
    assert ov.get("computer_name").status is Status.OK
    assert ov.get("uptime").status is Status.OK
    b = ov.get("os_build")
    assert b.status is Status.OK and b.value == "10.0.22631" and "fell back" in b.note


def test_build_fallback_rejects_non_windows_version_string():
    ov = collect(registry={}, platform_version=lambda: "#1 SMP Debian")
    assert ov.get("os_build").status is Status.UNAVAILABLE


def test_empty_is_distinct_from_unavailable():
    reg = {**BASE_REGISTRY, (BIOS_KEY, "SystemProductName"): "   "}
    ov = collect(registry=reg)
    assert ov.get("model").status is Status.EMPTY
    assert ov.get("manufacturer").status is Status.OK
    ov2 = collect(registry={k: v for k, v in BASE_REGISTRY.items() if k[1] != "SystemProductName"})
    assert ov2.get("model").status is Status.UNAVAILABLE


def test_placeholder_firmware_value_is_flagged_not_hidden():
    reg = {**BASE_REGISTRY, (BIOS_KEY, "SystemManufacturer"): "To Be Filled By O.E.M."}
    f = collect(registry=reg).get("manufacturer")
    assert f.status is Status.OK and "placeholder" in f.note


def test_cim_fallback_used_when_registry_missing():
    reg = {k: v for k, v in BASE_REGISTRY.items() if k[0] != BIOS_KEY}
    calls = []

    answers = {"Manufacturer": "CimCo", "Model": "CimBox"}

    def cim(cls, props):
        calls.append((cls, tuple(props)))
        return {props[0]: answers[props[0]]}

    ov = collect(registry=reg, cim_query=cim)
    assert ov.get("manufacturer").value == "CimCo" and "CIM" in ov.get("manufacturer").source
    assert ov.get("model").value == "CimBox"
    assert calls[0][0] == "Win32_ComputerSystem"


def test_registry_and_cim_both_fail_reports_both_reasons():
    reg = {k: v for k, v in BASE_REGISTRY.items() if k[0] != BIOS_KEY}
    f = collect(registry=reg).get("manufacturer")
    assert f.status is Status.UNAVAILABLE and "Registry:" in f.note and "CIM:" in f.note


def test_unexpected_exception_is_contained():
    def boom():
        raise RuntimeError("secret-internal-detail")
    ov = collect(boot_time=boom)
    for key in ("last_boot", "uptime"):
        f = ov.get(key)
        assert f.status is Status.UNAVAILABLE and "secret" not in f.note
    assert ov.get("computer_name").status is Status.OK


def test_boot_time_in_future_is_unavailable():
    ov = collect(boot_time=lambda: (NOW.timestamp() + 5000))
    assert ov.get("uptime").status is Status.UNAVAILABLE
    assert "future" in ov.get("uptime").note


@pytest.mark.parametrize("secs,text", [
    (10, "less than a minute"), (60, "1 minute"), (3600, "1 hour"),
    (90061, "1 day, 1 hour, 1 minute"), (2 * 86400 + 3 * 3600, "2 days, 3 hours")])
def test_format_uptime(secs, text):
    assert format_uptime(secs) == text


@pytest.mark.parametrize("env,machine,expected", [
    ({"PROCESSOR_ARCHITECTURE": "AMD64"}, "x", "x64 (AMD64)"),
    ({"PROCESSOR_ARCHITECTURE": "x86", "PROCESSOR_ARCHITEW6432": "AMD64"}, "x", "x64 (AMD64)"),
    ({"PROCESSOR_ARCHITECTURE": "ARM64"}, "x", "ARM64"),
    ({"PROCESSOR_ARCHITECTURE": "x86"}, "x", "x86 (32-bit)"),
    ({}, "riscv64", "RISCV64"),
])
def test_architecture(env, machine, expected):
    assert collect(env=env, machine=lambda: machine).get("architecture").value == expected


def test_architecture_missing():
    assert collect(env={}, machine=lambda: "").get("architecture").status is Status.UNAVAILABLE


def test_computer_name_falls_back_to_node():
    assert collect(env={}).get("computer_name").value == "NODE-PC"


# --- query_cim ---------------------------------------------------------------------

def _run_returning(stdout="", returncode=0):
    return lambda *a, **k: SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


def test_query_cim_parses_object_and_list(monkeypatch):
    monkeypatch.setattr(si.subprocess, "run", _run_returning('{"Manufacturer":"A","Model":null}'))
    assert si.query_cim("Win32_ComputerSystem", ["Manufacturer", "Model"]) == {"Manufacturer": "A", "Model": ""}
    monkeypatch.setattr(si.subprocess, "run", _run_returning('[{"Model":"B"}]'))
    assert si.query_cim("Win32_ComputerSystem", ["Model"]) == {"Model": "B"}


@pytest.mark.parametrize("exc", [FileNotFoundError(), subprocess.TimeoutExpired("x", 1), PermissionError()])
def test_query_cim_process_errors(monkeypatch, exc):
    def raiser(*a, **k):
        raise exc
    monkeypatch.setattr(si.subprocess, "run", raiser)
    with pytest.raises(CollectionError):
        si.query_cim("Win32_ComputerSystem", ["Model"])


@pytest.mark.parametrize("out,code", [("", 1), ("not json", 0), ("[]", 0), ("123", 0)])
def test_query_cim_bad_output(monkeypatch, out, code):
    monkeypatch.setattr(si.subprocess, "run", _run_returning(out, code))
    with pytest.raises(CollectionError):
        si.query_cim("Win32_ComputerSystem", ["Model"])


def test_query_cim_rejects_injection():
    with pytest.raises(CollectionError):
        si.query_cim("Win32_ComputerSystem; calc", ["Model"])
    with pytest.raises(CollectionError):
        si.query_cim("Win32_ComputerSystem", ["Model | x"])


def test_default_sources_never_crash():
    ov = collect_system_overview()  # real machine, whatever the OS
    assert len(ov.fields) == 9
