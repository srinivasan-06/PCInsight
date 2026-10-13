"""Runs the REAL network PowerShell script against stand-in cmdlets, using any PowerShell on this machine
(Windows PowerShell on Windows, pwsh elsewhere). Guards the bug where a harmless 'not found' notice made
the script throw away real gateway/DNS data."""
import json
import shutil
import subprocess

import pytest

from helpers import ETH_ROWS, make_net_sources
from pcinsight.core.network_info import NETWORK_SCRIPT, collect_network

EXE = shutil.which("powershell") or shutil.which("pwsh") or shutil.which("pwsh", path="/tmp/ps7")
pytestmark = pytest.mark.skipif(EXE is None, reason="PowerShell not installed")

STUBS = r"""
function Get-NetAdapter { [CmdletBinding()] param([switch]$IncludeHidden)
  [pscustomobject]@{Name='Wi-Fi';InterfaceDescription='Test WLAN';InterfaceIndex=5;Status='Up';LinkSpeed='400 Mbps';MediaType='Native 802.11';PhysicalMediaType='Native 802.11';Virtual=$false;HardwareInterface=$true}
  if ($IncludeHidden) { [pscustomobject]@{Name='Local Area Connection* 1';InterfaceDescription='Wi-Fi Direct Virtual Adapter';InterfaceIndex=9;Status='Disconnected';LinkSpeed='0 bps';MediaType='802.3';PhysicalMediaType='Unspecified';Virtual=$true;HardwareInterface=$false} } }
function Get-NetRoute { [CmdletBinding()] param($DestinationPrefix)
  [pscustomobject]@{InterfaceIndex=5;AddressFamily='IPv4';NextHop='192.168.1.1'}
  Write-Error -Message 'No MSFT_NetRoute objects found for the IPv6 prefix.' -Category ObjectNotFound }
function Get-DnsClientServerAddress { [CmdletBinding()] param()
  [pscustomobject]@{InterfaceIndex=5;AddressFamily='IPv4';ServerAddresses=@('192.168.1.1')}
  [pscustomobject]@{InterfaceIndex=5;AddressFamily='IPv6';ServerAddresses=@()}
  Write-Error -Message 'Interface 9 not found' -Category ObjectNotFound }
function Get-NetIPInterface { [CmdletBinding()] param()
  [pscustomobject]@{InterfaceIndex=5;AddressFamily='IPv4';Dhcp='Enabled'} }
function Get-CimInstance { [CmdletBinding()] param([Parameter(Position=0)]$ClassName,$Filter)
  [pscustomobject]@{InterfaceIndex=5;DHCPEnabled=$true;DHCPServer='192.168.1.1';DHCPLeaseObtained=[datetime]'2026-10-13 04:23';DHCPLeaseExpires=[datetime]'2026-10-14 04:23'} }
"""


def run_script(stubs: str) -> dict:
    proc = subprocess.run([EXE, "-NoProfile", "-NonInteractive", "-Command", stubs + NETWORK_SCRIPT],
                          capture_output=True, text=True, encoding="utf-8", timeout=60,
                          env={**__import__("os").environ, "DOTNET_SYSTEM_GLOBALIZATION_INVARIANT": "1"})
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().lstrip("\ufeff"))


def test_not_found_notices_do_not_discard_real_data():
    d = run_script(STUBS)
    assert d["routes"] == [{"InterfaceIndex": 5, "Family": "IPv4", "NextHop": "192.168.1.1"}]
    assert len(d["dns"]) == 2 and d["dns"][0]["Servers"] in ("192.168.1.1", ["192.168.1.1"])
    assert len(d["dhcp"]) == 1 and len(d["leases"]) == 1
    assert d["failed"] == []
    assert {a["Name"] for a in d["adapters"]} == {"Wi-Fi", "Local Area Connection* 1"}   # hidden adapters included


def test_missing_cmdlet_is_reported_as_failed_not_empty():
    d = run_script(STUBS + "function Get-NetRoute { throw 'boom' }\n")
    assert d["failed"] == ["routes"] and d["routes"] == []
    assert len(d["dns"]) == 2                                  # other sections unaffected


def test_real_error_with_no_data_is_failed_but_not_found_alone_is_not():
    bad = "function Get-DnsClientServerAddress { [CmdletBinding()] param() Write-Error -Message 'denied' -Category PermissionDenied }\n"
    assert run_script(STUBS + bad)["failed"] == ["dns"]
    only_notfound = "function Get-NetRoute { [CmdletBinding()] param($DestinationPrefix) Write-Error -Message 'none' -Category ObjectNotFound }\n"
    d = run_script(STUBS + only_notfound)
    assert d["failed"] == [] and d["routes"] == []             # genuinely no default route: not a failure


def test_end_to_end_gateway_and_dns_reach_the_report():
    d = run_script(STUBS)
    rows = [("mac", "58-A0-23-A9-63-02", ""), ("ipv4", "192.168.1.3", "255.255.255.0")]
    src = make_net_sources(ifaces={"Wi-Fi": rows}, stats={"Wi-Fi": (True, 400)}, ps=[d])
    scan = collect_network(src)
    wifi = next(s for s in scan.sections if s.key == "net_adapter_1")
    assert wifi.get("gateway").value == "192.168.1.1 (IPv4)"
    assert wifi.get("dns").value == "192.168.1.1"
    assert wifi.get("dhcp_server").value == "192.168.1.1"
    assert scan.gateways == ["192.168.1.1"]
