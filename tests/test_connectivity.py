import subprocess
from types import SimpleNamespace

import pytest

from helpers import NOW
from pcinsight.core import connectivity as cv
from pcinsight.core.common import CollectionError
from pcinsight.core.connectivity import ConnectivitySources, run_connectivity_checks
from pcinsight.core.models import Status


def sources(ping=None, tcp=None, resolve=None):
    return ConnectivitySources(ping=ping or (lambda gw: (True, 3.0)),
                               tcp_connect=tcp or (lambda h, p, t: 12.0),
                               resolve=resolve or (lambda name: 2), now=lambda: NOW)


def run(gateways=("192.168.1.1",), **kw):
    res = run_connectivity_checks(list(gateways), sources(**kw))
    return res, {f.key: f for f in res.sections[0].fields}


def test_all_checks_succeed():
    res, f = run()
    assert res.ran_at == NOW and res.sections[0].key == "net_connectivity"
    assert f["gateway_1"].value == "Reply received (3 ms)" and f["gateway_1"].label == "Ping default gateway 192.168.1.1"
    assert f["internet"].value == "Connected to 1.1.1.1:443 (12 ms)" and f["internet"].note == ""
    assert f["dns"].value.startswith("Resolved example.com (")
    assert all(x.status is Status.OK for x in f.values())
    assert "separate from the local configuration" in res.sections[0].note


def test_no_reply_is_a_result_not_an_error_and_is_explained():
    _, f = run(ping=lambda gw: (False, None))
    assert f["gateway_1"].status is Status.OK and f["gateway_1"].value.startswith("No reply")
    assert "ignore ping" in f["gateway_1"].note


def test_reply_without_time():
    assert run(ping=lambda gw: (True, None))[1]["gateway_1"].value == "Reply received"


def test_ping_cannot_run_is_unavailable():
    def no_ping(gw):
        raise CollectionError("ping.exe was not found")
    f = run(ping=no_ping)[1]["gateway_1"]
    assert f.status is Status.UNAVAILABLE and "ping.exe" in f.note


def test_no_gateway_known():
    f = run(gateways=())[1]["gateway"]
    assert f.status is Status.UNAVAILABLE and "Run a scan first" in f.note


def test_only_two_unique_gateways_pinged():
    pinged = []

    def ping(gw):
        pinged.append(gw)
        return True, 1.0

    _, f = run(gateways=("10.0.0.1", "10.0.0.1", "10.0.0.2", "10.0.0.3"), ping=ping)
    assert sorted(pinged) == ["10.0.0.1", "10.0.0.2"] and {"gateway_1", "gateway_2"} <= set(f)


def test_internet_falls_back_to_second_target():
    def tcp(h, p, t):
        if h == "1.1.1.1":
            raise TimeoutError()
        return 20.0
    f = run(tcp=tcp)[1]["internet"]
    assert f.value == "Connected to 8.8.8.8:443 (20 ms)" and "backup target" in f.note


@pytest.mark.parametrize("exc,why", [(TimeoutError(), "timed out"), (ConnectionRefusedError(), "connection refused"),
                                     (OSError("secret"), "network unreachable or blocked")])
def test_internet_failure_reasons(exc, why):
    def tcp(h, p, t):
        raise exc
    f = run(tcp=tcp)[1]["internet"]
    assert f.status is Status.OK and f.value.startswith("Could not connect") and why in f.value
    assert "secret" not in f.value and "firewall" in f.note


def test_dns_failure():
    def resolve(name):
        raise OSError("nope")
    f = run(resolve=resolve)[1]["dns"]
    assert f.value.startswith("Could not resolve example.com") and "DNS servers" in f.note


def test_unexpected_exception_in_a_check_is_contained():
    def boom(h, p, t):
        raise RuntimeError("secret")
    f = run(tcp=boom)[1]
    assert f["internet"].status is Status.UNAVAILABLE and "secret" not in f["internet"].note
    assert f["dns"].status is Status.OK


# --- default implementations -----------------------------------------------------------

def _proc(out, code=0):
    return lambda *a, **k: SimpleNamespace(stdout=out, stderr="", returncode=code)


@pytest.mark.parametrize("out,expected", [
    ("Reply from 192.168.1.1: bytes=32 time=12ms TTL=64", (True, 12.0)),
    ("Reply from 192.168.1.1: bytes=32 time<1ms TTL=64", (True, 1.0)),
    ("Antwort von 192.168.1.1: Bytes=32 Zeit=7ms TTL=64", (True, 7.0)),
    ("Reply from 192.168.1.1: bytes=32 TTL=64", (True, None)),
    ("Reply from 192.168.1.5: Destination host unreachable.", (False, None)),
    ("Request timed out.", (False, None))])
def test_ping_output_parsing(monkeypatch, out, expected):
    monkeypatch.setattr(cv, "_is_windows", lambda: True)
    monkeypatch.setattr(cv.subprocess, "run", _proc(out))
    assert cv._ping("192.168.1.1") == expected


def test_ping_rejects_non_ip_and_non_windows(monkeypatch):
    with pytest.raises(CollectionError):
        cv._ping("1.1.1.1; calc")
    with pytest.raises(CollectionError):
        cv._ping("example.com")
    monkeypatch.setattr(cv, "_is_windows", lambda: False)
    with pytest.raises(CollectionError):
        cv._ping("192.168.1.1")


def test_ping_process_errors(monkeypatch):
    monkeypatch.setattr(cv, "_is_windows", lambda: True)

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired("ping", 1)
    monkeypatch.setattr(cv.subprocess, "run", timeout)
    assert cv._ping("192.168.1.1") == (False, None)
    for exc in (FileNotFoundError(), PermissionError()):
        def boom(*a, **k):
            raise exc
        monkeypatch.setattr(cv.subprocess, "run", boom)
        with pytest.raises(CollectionError):
            cv._ping("192.168.1.1")


def test_ping_uses_argument_list_not_shell(monkeypatch):
    seen = {}

    def fake(cmd, **k):
        seen.update(cmd=cmd, kw=k)
        return SimpleNamespace(stdout="TTL=1", stderr="", returncode=0)
    monkeypatch.setattr(cv, "_is_windows", lambda: True)
    monkeypatch.setattr(cv.subprocess, "run", fake)
    cv._ping("192.168.1.1")
    assert seen["cmd"][0] == "ping" and seen["cmd"][-1] == "192.168.1.1" and not seen["kw"].get("shell")


def test_resolve_timeout_and_error(monkeypatch):
    monkeypatch.setattr(cv, "DNS_TIMEOUT_S", 0.05)
    import socket
    import time
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: time.sleep(0.3) or [])
    with pytest.raises(TimeoutError):
        cv._resolve("example.com")

    def err(*a, **k):
        raise socket.gaierror("no")
    monkeypatch.setattr(socket, "getaddrinfo", err)
    monkeypatch.setattr(cv, "DNS_TIMEOUT_S", 2.0)
    with pytest.raises(OSError):
        cv._resolve("example.com")


def test_targets_are_documented_constants():
    assert cv.INTERNET_TARGETS == [("1.1.1.1", 443), ("8.8.8.8", 443)] and cv.DNS_NAME == "example.com"


def test_resolve_unexpected_exception_becomes_oserror(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: None)  # would raise TypeError inside the thread
    with pytest.raises(OSError):
        cv._resolve("example.com")
