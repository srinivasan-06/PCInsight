import logging

import pytest

from helpers import ETH_ROWS, eth_ps, full_ps, make_net_sources, ps_root
from pcinsight.core.common import CollectionError
from pcinsight.core.models import Status
from pcinsight.core.network_info import NETWORK_SCRIPT, collect_network, default_sources


def collect(**kw):
    scan = collect_network(make_net_sources(**kw))
    return {s.key: s for s in scan.sections}, scan


def adapter(secs, i=1):
    return secs[f"net_adapter_{i}"]


def test_full_ethernet_adapter():
    secs, scan = collect()
    assert list(secs) == ["network", "net_adapter_1"]
    a = adapter(secs)
    assert a.title == "Ethernet \u2014 Intel(R) Ethernet Connection"
    assert a.get("status").value == "Up (connected)"
    assert a.get("connection_type").value == "Ethernet"
    assert a.get("adapter_class").value == "Physical adapter"
    assert a.get("link_speed").value == "1 Gbps"
    assert a.get("mac").value == "AA-BB-CC-DD-EE-FF"
    assert a.get("ipv4").value == "192.168.1.20 \u00b7 mask 255.255.255.0 \u00b7 network 192.168.1.0/24"
    assert a.get("ipv6").value == "fe80::1234/64 (link-local)\n2001:db8::20/64"   # scope id stripped
    assert a.get("gateway").value == "192.168.1.1 (IPv4)"                       # '::' on-link hop ignored
    assert a.get("dns").value == "192.168.1.1\n1.1.1.1"
    assert a.get("dhcp").value == "Enabled (IPv4)" and a.get("dhcp_server").value == "192.168.1.1"
    assert a.get("dhcp_lease").value == "obtained 2026-10-12 08:00 \u00b7 expires 2026-10-13 08:00"
    assert secs["network"].get("adapters").value == "1 adapter (1 up)"
    assert scan.gateways == ["192.168.1.1"]
    assert all(f.status is Status.OK for f in a.fields)


@pytest.mark.parametrize("phys,media,expected", [
    ("Native 802.11", "Native 802.11", "Wi-Fi"), ("802.3", "802.3", "Ethernet"),
    ("Bluetooth", "802.3", "Bluetooth"), ("Wireless WAN", "Wireless WAN", "Mobile broadband"),
    ("Cable Modem", "Unspecified", "Cable Modem")])
def test_connection_type_detection(phys, media, expected):
    ps = ps_root(adapters=[eth_ps(PhysicalMediaType=phys, MediaType=media)])
    secs, _ = collect(ps=ps)
    assert adapter(secs).get("connection_type").value == expected


def test_unknown_connection_type_is_unavailable_not_guessed():
    ps = ps_root(adapters=[eth_ps(PhysicalMediaType="Unspecified", MediaType="Unspecified")])
    assert adapter(collect(ps=ps)[0]).get("connection_type").status is Status.UNAVAILABLE


def test_disconnected_adapter_with_self_assigned_address():
    rows = [("mac", "11-22-33-44-55-66", ""), ("ipv4", "169.254.10.5", "255.255.0.0")]
    ps = ps_root(adapters=[eth_ps(name="Wi-Fi", status="Disconnected", LinkSpeed="0 bps",
                                  PhysicalMediaType="Native 802.11")],
                 dhcp=[{"InterfaceIndex": 7, "Family": "IPv4", "Dhcp": "Enabled"}],
                 leases=[{"InterfaceIndex": 7, "DHCPEnabled": True, "DHCPServer": "", "LeaseObtained": "", "LeaseExpires": ""}])
    secs, scan = collect(ifaces={"Wi-Fi": rows}, stats={"Wi-Fi": (False, 0)}, ps=ps)
    a = adapter(secs)
    assert a.get("status").value == "Disconnected (no link)"
    assert a.get("connection_type").value == "Wi-Fi"
    assert a.get("link_speed").status is Status.UNAVAILABLE
    ip = a.get("ipv4")
    assert "self-assigned" in ip.value and "no DHCP server answered" in ip.note
    assert a.get("gateway").status is Status.EMPTY and "No default gateway" in a.get("gateway").note
    assert a.get("dhcp_lease").status is Status.EMPTY
    assert scan.gateways == []                # disconnected adapters contribute no gateway
    assert secs["network"].get("adapters").value == "1 adapter (0 up)"


def test_virtual_adapter_flagged():
    ps = ps_root(adapters=[eth_ps(name="vEthernet", Virtual=True, HardwareInterface=False)])
    secs, _ = collect(ifaces={"vEthernet": ETH_ROWS}, stats={"vEthernet": (True, 10000)}, ps=ps)
    assert adapter(secs).get("adapter_class").value == "Virtual / software adapter"


def test_multiple_adapters_up_first_and_gateways_deduped():
    ps = ps_root(
        adapters=[eth_ps(1, "Ethernet", "Up"), eth_ps(2, "Wi-Fi", "Up", PhysicalMediaType="Native 802.11"),
                  eth_ps(3, "Bluetooth Network", "Disconnected")],
        routes=[{"InterfaceIndex": 1, "Family": "IPv4", "NextHop": "10.0.0.1"},
                {"InterfaceIndex": 2, "Family": "IPv4", "NextHop": "10.0.0.1"},
                {"InterfaceIndex": 3, "Family": "IPv4", "NextHop": "10.9.9.9"}],
        dns=[], dhcp=[], leases=[])
    ifaces = {"Bluetooth Network": [("mac", "00-00-00-00-00-03", "")], "Wi-Fi": ETH_ROWS, "Ethernet": ETH_ROWS}
    stats = {"Bluetooth Network": (False, 0), "Wi-Fi": (True, 300), "Ethernet": (True, 1000)}
    secs, scan = collect(ifaces=ifaces, stats=stats, ps=ps)
    assert [adapter(secs, i).title.split(" \u2014 ")[0] for i in (1, 2, 3)] == ["Ethernet", "Wi-Fi", "Bluetooth Network"]
    assert scan.gateways == ["10.0.0.1"]
    assert secs["network"].get("adapters").value == "3 adapters (2 up)"


def test_loopback_hidden():
    lo = [("ipv4", "127.0.0.1", "255.0.0.0"), ("ipv6", "::1", "")]
    secs, _ = collect(ifaces={"Loopback Pseudo-Interface 1": lo, "Ethernet": ETH_ROWS},
                      ps=ps_root(adapters=[eth_ps()]))
    assert secs["network"].get("adapters").value == "1 adapter (1 up)"
    assert "Loopback Pseudo-Interface 1" not in " ".join(s.title for s in secs.values())
    zero_mac = [("mac", "00:00:00:00:00:00", ""), ("ipv4", "127.0.0.1", "255.0.0.0")]
    assert collect(ifaces={"lo": zero_mac}, stats={}, ps=ps_root())[0]["network"].get("adapters").value == "0 adapters (0 up)"


def test_powershell_failure_keeps_base_data_and_explains():
    secs, scan = collect(ps_error=CollectionError("PowerShell was not found"))
    a = adapter(secs)
    assert a.title == "Ethernet"
    assert a.get("status").value == "Up" and "needs PowerShell" in a.get("status").note
    assert a.get("mac").status is Status.OK and a.get("ipv4").status is Status.OK
    assert a.get("link_speed").value == "1,000 Mbps"                     # psutil fallback
    for key in ("connection_type", "adapter_class", "gateway", "dns", "dhcp", "dhcp_server", "dhcp_lease"):
        f = a.get(key)
        assert f.status is Status.UNAVAILABLE and "PowerShell was not found" in f.note, key
    assert scan.gateways == []
    assert "limited" in secs["network"].get("adapters").note


def test_partial_powershell_failure_isolated_per_section():
    ps = full_ps()
    ps[0]["failed"] = ["routes"]
    secs, scan = collect(ps=ps)
    a = adapter(secs)
    assert a.get("gateway").status is Status.UNAVAILABLE and "routes" in a.get("gateway").note
    assert a.get("dns").status is Status.OK and a.get("dhcp").status is Status.OK
    assert scan.gateways == []


@pytest.mark.parametrize("bad", [[], [{}], [{"adapters": "nope"}]])
def test_unexpected_powershell_shapes_do_not_crash(bad):
    secs, _ = collect(ps=bad)
    a = adapter(secs)
    assert a.get("mac").status is Status.OK
    assert a.get("gateway").status is Status.UNAVAILABLE


def test_adapter_missing_from_powershell_data():
    secs, _ = collect(ps=ps_root(adapters=[eth_ps(name="Other")]))
    a = adapter(secs, 1)
    assert a.get("connection_type").status is Status.UNAVAILABLE and "did not describe" in a.get("connection_type").note
    assert a.get("gateway").status is Status.UNAVAILABLE and "not matched" in a.get("gateway").note


def test_powershell_only_adapter_disabled_is_listed():
    ps = ps_root(adapters=[eth_ps(1, "Ethernet"), eth_ps(9, "Ethernet 2", "Disabled", MacAddress="AA-AA-AA-AA-AA-AA")])
    secs, _ = collect(ps=ps)
    titles = [s.title.split(" \u2014 ")[0] for k, s in secs.items() if k.startswith("net_adapter")]
    assert titles == ["Ethernet", "Ethernet 2"]
    d = adapter(secs, 2)
    assert d.get("status").value == "Disabled" and d.get("mac").value == "AA-AA-AA-AA-AA-AA"
    assert d.get("ipv4").status is Status.EMPTY


def test_dhcp_disabled_static_address():
    ps = full_ps()
    ps[0]["dhcp"] = [{"InterfaceIndex": 7, "Family": "IPv4", "Dhcp": "Disabled"}]
    ps[0]["leases"] = [{"InterfaceIndex": 7, "DHCPEnabled": False}]
    a = adapter(collect(ps=ps)[0])
    assert a.get("dhcp").value == "Disabled (IPv4)"
    assert "not using DHCP" in a.get("dhcp_server").note and a.get("dhcp_server").status is Status.EMPTY


def test_no_mac_and_no_addresses():
    secs, _ = collect(ifaces={"Ethernet": []}, ps=ps_root(adapters=[eth_ps()]))
    a = adapter(secs)
    assert a.get("mac").status is Status.UNAVAILABLE
    assert a.get("ipv4").status is Status.EMPTY and a.get("ipv6").status is Status.EMPTY


def test_malformed_addresses_do_not_crash():
    rows = [("mac", "AA", ""), ("ipv4", "not-an-ip", "255.255.255.0"), ("ipv6", "zzz", "bad-mask")]
    a = adapter(collect(ifaces={"Ethernet": rows})[0])
    assert a.get("ipv4").status is Status.OK and a.get("ipv6").status is Status.OK


def test_listing_failure_gives_single_unavailable_section():
    def boom():
        raise OSError("secret-detail")
    secs, scan = collect(interfaces=boom)
    f = secs["network"].get("adapters")
    assert f.status is Status.UNAVAILABLE and "secret" not in f.note and "OSError" in f.note
    assert scan.gateways == []


def test_stats_failure_is_tolerated():
    def boom():
        raise RuntimeError("x")
    secs, _ = collect(if_stats=boom, ps=ps_root())
    assert adapter(secs).get("mac").status is Status.OK


def test_addresses_never_logged(caplog):
    with caplog.at_level(logging.DEBUG):
        collect(ps_error=CollectionError("PowerShell was not found"))
        collect(ps=[{"adapters": "bad"}])
    text = caplog.text
    for secret in ("192.168.1.20", "AA-BB-CC-DD-EE-FF", "2001:db8"):
        assert secret not in text


def test_powershell_script_is_constant_and_read_only():
    assert "Get-NetAdapter" in NETWORK_SCRIPT and "ConvertTo-Json" in NETWORK_SCRIPT
    for verb in ("Set-", "New-", "Remove-", "Disable-", "Enable-", "Restart-", "Invoke-", "Start-", "Stop-"):
        assert verb not in NETWORK_SCRIPT


def test_default_sources_never_crash():
    scan = collect_network()
    assert scan.sections[0].key == "network" and isinstance(scan.gateways, list)
    assert default_sources().interfaces is not None
