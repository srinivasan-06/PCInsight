import inspect
import os
import socket

import pytest

from helpers import PROCS, ep, make_port_sources
from pcinsight.core import ports_info
from pcinsight.core.common import CollectionError
from pcinsight.core.models import Status
from pcinsight.core.ports_info import (DEFAULT_IMPORTANT_PORTS, ST_LISTENING, ST_NONE, ST_NO_PROCESS, ST_UDP,
                                       classify_binding, collect_ports, normalize_ports)

TCP = [ep("tcp", "0.0.0.0", 135, 1234), ep("tcp", "::", 135, 1234), ep("tcp", "0.0.0.0", 445, 4),
       ep("tcp", "127.0.0.1", 3306, 2200), ep("tcp", "192.168.1.3", 5040, 1234)]
UDP = [ep("udp", "0.0.0.0", 5353, 1234), ep("udp", "127.0.0.1", 50000, 3300), ep("udp", "::", 53, 1234)]


def collect(tcp=TCP, udp=UDP, important=None, **kw):
    return {s.key: s for s in collect_ports(make_port_sources(tcp, udp, **kw), important)}


def value(sec, key):
    return sec.get(key).value


def test_four_sections_and_default_important_list():
    secs = collect()
    assert list(secs) == ["ports", "ports_important", "ports_tcp", "ports_udp"]
    assert DEFAULT_IMPORTANT_PORTS == [21, 22, 23, 25, 53, 80, 135, 139, 443, 445, 1433, 3306, 3389, 5432, 5900]
    assert len(secs["ports_important"].fields) == 15


def test_exact_status_wording():
    assert (ST_LISTENING, ST_NONE, ST_NO_PROCESS, ST_UDP) == (
        "Listening locally", "No local listener detected", "Process details unavailable",
        "UDP endpoint detected; remote reachability not verified")


def test_all_tcp_listeners_shown_not_only_important_ones():
    tcp = collect()["ports_tcp"]
    labels = [f.label for f in tcp.fields]
    assert len(labels) == 5 and any(l.startswith("5040/TCP") for l in labels)   # 5040 is not an important port
    assert all(f.value.startswith(ST_LISTENING) for f in tcp.fields)


def test_port_to_process_mapping():
    tcp = {f.label.split(" ")[0] + "@" + f.value.splitlines()[1].split(" \u00b7 ")[0]: f.value for f in collect()["ports_tcp"].fields}
    assert tcp["445/TCP@0.0.0.0:445"].endswith("System (PID 4)")
    assert tcp["135/TCP@0.0.0.0:135"].endswith("svchost.exe (PID 1234)")
    assert tcp["3306/TCP@127.0.0.1:3306"].endswith("mysqld.exe (PID 2200)")


def test_each_pid_is_looked_up_once():
    calls = []

    def names(pid):
        calls.append(pid)
        return PROCS[pid]

    collect(names=names)
    assert sorted(calls) == sorted(set(calls)) and set(calls) == {4, 1234, 2200, 3300}


def test_ipv4_and_ipv6_listeners_are_separate_rows():
    rows = [f.value for f in collect()["ports_tcp"].fields if f.label.startswith("135/TCP")]
    assert len(rows) == 2 and any("[::]:135" in r for r in rows) and any("0.0.0.0:135" in r for r in rows)


@pytest.mark.parametrize("addr,label,fragment", [
    ("0.0.0.0", "all interfaces", "not tested"), ("::", "all interfaces", "not tested"),
    ("127.0.0.1", "loopback only", "only programs on this computer"), ("::1", "loopback only", "only programs"),
    ("::ffff:127.0.0.1", "loopback only", "only programs"),
    ("192.168.1.3", "specific address", "single address 192.168.1.3"),
    ("fe80::1%Ethernet", "specific address", "single address fe80::1"),
    ("not-an-ip", "unrecognised address", "unknown")])
def test_binding_classification(addr, label, fragment):
    got_label, sentence = classify_binding(addr)
    assert got_label == label and fragment in sentence


def test_no_row_claims_remote_reachability():
    secs = collect()
    for sec in secs.values():
        for f in sec.fields:
            text = f"{f.value or ''} {f.note}".lower()
            assert "reachable from the internet" not in text and "exposed to the internet" not in text
            assert "is open to" not in text and "port is open" not in text.replace("open or closed", "")
    wildcard = next(f for f in secs["ports_tcp"].fields if f.label.startswith("445/TCP"))
    assert "depends on your firewall" in wildcard.note and "not tested" in wildcard.note
    loop = next(f for f in secs["ports_tcp"].fields if f.label.startswith("3306/TCP"))
    assert "only programs on this computer" in loop.note


def test_important_ports_listening_and_absent():
    imp = collect()["ports_important"]
    p445, p22 = imp.get("port_445"), imp.get("port_22")
    assert p445.value.startswith(ST_LISTENING) and "System (PID 4)" in p445.value
    assert p22.value == ST_NONE
    assert "does not prove the port is closed from outside" in p22.note
    assert "normal for most of these ports not to be in use" in p22.note
    assert imp.get("port_3306").note.endswith("so only programs on this computer can connect.")   # loopback-only wording
    assert "depends on your firewall" in imp.get("port_135").note


def test_important_port_with_udp_too():
    imp = collect()["ports_important"]
    assert "UDP endpoint also detected on port 53; remote reachability not verified" in imp.get("port_53").value
    assert imp.get("port_53").value.startswith(ST_NONE)          # TCP: no listener; UDP only mentioned
    assert ST_UDP not in imp.get("port_135").value


def test_udp_is_separate_and_never_open_or_closed():
    secs = collect()
    for f in secs["ports_udp"].fields:
        first, second = f.value.splitlines()[:2]
        assert first == ST_UDP and ST_LISTENING not in f.value
        assert "cannot say whether this port is open or closed" in f.note
    assert not any(f.value.startswith(ST_UDP) for f in secs["ports_tcp"].fields)
    assert not any(ST_UDP in (f.value or "").splitlines()[0] for f in secs["ports_important"].fields)


def test_process_lookup_failures_are_shown_honestly():
    tcp = [ep("tcp", "0.0.0.0", 8000, 5555), ep("tcp", "0.0.0.0", 8001, 6666), ep("tcp", "0.0.0.0", 8002, None),
           ep("tcp", "0.0.0.0", 8003, 777)]
    secs = collect(tcp=tcp, udp=[])
    vals = {f.label.split("/")[0]: f.value.splitlines()[1] for f in secs["ports_tcp"].fields}
    assert f"{ST_NO_PROCESS} (access denied; PID 5555)" in vals["8000"]
    assert f"{ST_NO_PROCESS} (the process had already exited; PID 6666)" in vals["8001"]
    assert f"{ST_NO_PROCESS} (no process ID reported)" in vals["8002"]
    assert f"{ST_NO_PROCESS} (lookup failed; PID 777)" in vals["8003"]
    assert all(f.status is Status.OK for f in secs["ports_tcp"].fields)         # row still shown
    assert secs["ports"].get("process_gaps").value == "4 of 4 TCP, 0 of 0 UDP"
    assert "administrator" in secs["ports"].get("process_gaps").note


def test_unexpected_process_lookup_exception_is_contained():
    def boom(pid):
        raise RuntimeError("secret-internal")
    secs = collect(names=boom)
    row = secs["ports_tcp"].fields[0]
    assert row.status is Status.OK and "lookup failed" in row.value and "secret" not in row.value


def test_overview_counts_and_important_summary():
    ov = collect()["ports"]
    assert ov.get("tcp_count").value == "5" and ov.get("udp_count").value == "3"
    assert ov.get("important").value == "135, 445, 3306 listening (3 of 15)"
    assert ov.get("process_gaps").value == "0 of 5 TCP, 0 of 3 UDP"
    assert "no other computer is scanned" in ov.note and "never changes firewall rules" in ov.note


def test_configurable_important_ports():
    imp = collect(important=[8080, 22, 8080, 0, 70000, -1, "443", True, 3306])["ports_important"]
    assert [f.key for f in imp.fields] == ["port_8080", "port_22", "port_3306"]
    assert imp.get("port_3306").value.startswith(ST_LISTENING)
    empty = collect(important=[])
    assert empty["ports_important"].fields[0].status is Status.EMPTY
    assert empty["ports"].get("important").status is Status.EMPTY


def test_normalize_ports():
    assert normalize_ports([5, 5, "x", None, 65535, 65536, 1.5]) == [5, 65535]


def test_service_names_known_dynamic_unknown_and_system_fallback():
    s = make_port_sources(TCP, UDP, service_name=ports_info._service_name)
    secs = {x.key: x for x in collect_ports(s)}
    row445 = next(f for f in secs["ports_tcp"].fields if f.label.startswith("445/TCP"))
    assert row445.label == "445/TCP \u00b7 SMB (Windows file sharing)"
    assert "conventionally used for SMB" in row445.note and "cannot confirm" in row445.note
    dyn = collect(tcp=[ep("tcp", "0.0.0.0", 49664)])["ports_tcp"].fields[0]
    assert "dynamic range" in dyn.note and dyn.label == "49664/TCP"
    unk = collect(tcp=[ep("tcp", "0.0.0.0", 40000)])["ports_tcp"].fields[0]
    assert "No conventional service name is known for port 40000" in unk.note


def test_tcp_table_failure_does_not_hide_udp():
    secs = collect(tcp_error=CollectionError("Access is denied reading the socket table"))
    assert secs["ports_tcp"].fields[0].status is Status.UNAVAILABLE and "denied" in secs["ports_tcp"].fields[0].note
    assert all(f.status is Status.UNAVAILABLE for f in secs["ports_important"].fields)
    assert secs["ports"].get("tcp_count").status is Status.UNAVAILABLE
    assert secs["ports"].get("udp_count").value == "3"
    assert secs["ports_udp"].fields[0].status is Status.OK


def test_udp_table_failure_does_not_hide_tcp_and_unexpected_errors_are_contained():
    secs = collect(udp_error=RuntimeError("secret"))
    assert secs["ports_udp"].fields[0].status is Status.UNAVAILABLE and "secret" not in secs["ports_udp"].fields[0].note
    assert secs["ports_tcp"].fields[0].status is Status.OK
    assert secs["ports"].get("important").status is Status.OK


def test_empty_results():
    secs = collect(tcp=[], udp=[])
    assert secs["ports_tcp"].fields[0].status is Status.EMPTY and secs["ports_udp"].fields[0].status is Status.EMPTY
    assert all(f.value == ST_NONE for f in secs["ports_important"].fields)
    assert secs["ports"].get("tcp_count").value == "0"
    assert secs["ports"].get("important").value == "none listening (0 of 15)"


def test_duplicates_removed_and_many_endpoints():
    dup = [ep("tcp", "0.0.0.0", 80, 1234)] * 3
    assert len(collect(tcp=dup)["ports_tcp"].fields) == 1
    many = [ep("tcp", "0.0.0.0", 10000 + i, 1234) for i in range(800)]
    secs = collect(tcp=many, udp=[])
    assert len(secs["ports_tcp"].fields) == 800 and secs["ports_tcp"].fields[0].label.startswith("10000/TCP")


def test_two_programs_on_one_port_both_listed():
    secs = collect(tcp=[ep("tcp", "127.0.0.1", 9000, 2200), ep("tcp", "192.168.1.3", 9000, 3300)], important=[9000])
    value_lines = secs["ports_important"].get("port_9000").value.splitlines()
    assert value_lines[0] == ST_LISTENING and len(value_lines) == 3


def test_module_is_read_only_and_makes_no_network_calls():
    src = inspect.getsource(ports_info)
    # Look for the actual commands/APIs that would change firewall rules, stop programs or send traffic
    # (the user-facing text legitimately says the app never changes firewall rules).
    for forbidden in ("netsh", "advfirewall", "NetFirewallRule", "subprocess", ".connect(", "sendto", "create_connection",
                      "taskkill", "os.kill", ".terminate(", ".kill(", "Stop-Service", "sc.exe"):
        assert forbidden not in src, forbidden


def test_addresses_never_logged(caplog):
    import logging
    with caplog.at_level(logging.DEBUG):
        collect(names=lambda pid: (_ for _ in ()).throw(RuntimeError("x")), tcp_error=None)
        collect(tcp_error=RuntimeError("boom"))
    assert "192.168.1.3" not in caplog.text and "1234" not in caplog.text


# ---- real sockets on whatever OS runs the tests (no admin needed) ------------------------------------------

def test_real_listening_sockets_are_attributed_to_this_process():
    import psutil
    tcp_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    udp_srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        tcp_srv.bind(("127.0.0.1", 0))
        tcp_srv.listen(1)
        udp_srv.bind(("127.0.0.1", 0))
        tport, uport = tcp_srv.getsockname()[1], udp_srv.getsockname()[1]
        secs = {s.key: s for s in collect_ports(important_ports=[tport])}
        me = f"(PID {os.getpid()})"
        name = psutil.Process().name()

        trow = next(f for f in secs["ports_tcp"].fields if f.label.startswith(f"{tport}/TCP"))
        assert trow.value.splitlines()[0] == ST_LISTENING
        assert f"127.0.0.1:{tport}" in trow.value and "loopback only" in trow.value
        assert name in trow.value and me in trow.value                       # port -> process mapping, for real

        urow = next(f for f in secs["ports_udp"].fields if f.label.startswith(f"{uport}/UDP"))
        assert urow.value.splitlines()[0] == ST_UDP and me in urow.value

        imp = secs["ports_important"].get(f"port_{tport}")
        assert imp.value.startswith(ST_LISTENING) and me in imp.value
    finally:
        tcp_srv.close()
        udp_srv.close()


def test_a_closed_real_port_is_reported_as_no_listener():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                                                                 # nothing listens here any more
    imp = {x.key: x for x in collect_ports(important_ports=[port])}["ports_important"]
    assert imp.get(f"port_{port}").value == ST_NONE


def test_default_sources_never_crash():
    secs = collect_ports()
    assert [s.key for s in secs] == ["ports", "ports_important", "ports_tcp", "ports_udp"]
