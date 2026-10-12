import subprocess
from types import SimpleNamespace

import pytest

from pcinsight.core import common
from pcinsight.core.common import (CollectionError, format_bytes, query_cim_all, run_powershell_json,
                                   to_int)


@pytest.mark.parametrize("n,text", [
    (0, "0 bytes"), (1023, "1023 bytes"), (1024, "1 KB"), (1536, "1.5 KB"),
    (16 * 1024 ** 3, "16 GB"), (int(465.76 * 1024 ** 3), "465.8 GB"), (1024 ** 4, "1 TB")])
def test_format_bytes(n, text):
    assert format_bytes(n) == text


@pytest.mark.parametrize("v,expected", [("5", 5), (" 7 ", 7), (8, 8), ("1.7179869184E10", 17179869184),
                                        ("", None), (None, None), ("abc", None)])
def test_to_int(v, expected):
    assert to_int(v) == expected


def _run(stdout="", code=0):
    return lambda *a, **k: SimpleNamespace(stdout=stdout, stderr="", returncode=code)


def test_powershell_json_variants(monkeypatch):
    monkeypatch.setattr(common.subprocess, "run", _run(""))
    assert run_powershell_json("x") == []                       # no instances
    monkeypatch.setattr(common.subprocess, "run", _run('\ufeff{"a":1}'))
    assert run_powershell_json("x") == [{"a": 1}]               # BOM stripped, object -> list
    monkeypatch.setattr(common.subprocess, "run", _run('[{"a":1},{"a":2}]'))
    assert len(run_powershell_json("x")) == 2


@pytest.mark.parametrize("out,code", [("not json", 0), ("[1,2]", 0), ("5", 0), ("", 1)])
def test_powershell_json_bad(monkeypatch, out, code):
    monkeypatch.setattr(common.subprocess, "run", _run(out, code))
    with pytest.raises(CollectionError):
        run_powershell_json("x")


def test_powershell_requests_utf8(monkeypatch):
    seen = {}

    def fake(cmd, **k):
        seen.update(cmd=cmd, kw=k)
        return SimpleNamespace(stdout="[]", stderr="", returncode=0)

    monkeypatch.setattr(common.subprocess, "run", fake)
    run_powershell_json("Get-Thing")
    assert "UTF8" in seen["cmd"][-1] and seen["kw"]["encoding"] == "utf-8"


def test_query_cim_all_cleans_values(monkeypatch):
    monkeypatch.setattr(common.subprocess, "run", _run('[{"A":" x ","B":null,"C":5,"D":"ignored"}]'))
    assert query_cim_all("Win32_X", ["A", "B", "C", "Missing"]) == [{"A": "x", "B": "", "C": "5", "Missing": ""}]


def test_query_cim_all_rejects_bad_names():
    with pytest.raises(CollectionError):
        query_cim_all("Win32_X; calc", ["A"])
    with pytest.raises(CollectionError):
        query_cim_all("Win32_X", ["A | B"])


def test_timeout_and_missing_powershell(monkeypatch):
    for exc in (subprocess.TimeoutExpired("x", 1), FileNotFoundError(), PermissionError()):
        def boom(*a, **k):
            raise exc
        monkeypatch.setattr(common.subprocess, "run", boom)
        with pytest.raises(CollectionError):
            run_powershell_json("x")
