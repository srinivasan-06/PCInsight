"""Module 5a: local network configuration (no traffic is sent; nothing leaves this PC).

Base data (names, status, IP addresses, MAC, subnet mask) comes from psutil and always works.
Enrichment (adapter type, link speed, gateway, DNS, DHCP) comes from ONE PowerShell call; if it
fails, those fields are marked unavailable with the reason while the base data is still shown.
Addresses are never written to logs.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .common import CollectionError, Reading, clean_value, make_field, run_powershell_json, to_int
from .models import InfoSection

SRC_PSUTIL = "psutil"
SRC_NET = "Windows networking (PowerShell)"
PRIVACY_NOTE = ("IP and MAC addresses identify this computer on your network. PCInsight keeps them on this "
                "PC, hides loopback interfaces, and does not collect Wi-Fi network names (SSIDs) or signal strength.")
ADAPTER_NOTE = ("Everything below is local configuration read from this computer; no network traffic is sent. "
                "Use the connectivity tests on this page to check whether a path actually works.")

NETWORK_SCRIPT = r"""
$global:failed = @()
function Get-Section($name, [scriptblock]$sb) {
  try { return @(& $sb) } catch {
    if ($_.CategoryInfo.Category -ne 'ObjectNotFound') { $global:failed += $name }
    return @()
  }
}
$adapters = @(Get-Section 'adapters' { Get-NetAdapter -ErrorAction Stop | Select-Object Name,InterfaceDescription,InterfaceIndex,@{n='Status';e={[string]$_.Status}},@{n='LinkSpeed';e={[string]$_.LinkSpeed}},@{n='MediaType';e={[string]$_.MediaType}},@{n='PhysicalMediaType';e={[string]$_.PhysicalMediaType}},@{n='Virtual';e={[bool]$_.Virtual}},@{n='HardwareInterface';e={[bool]$_.HardwareInterface}} })
$routes = @(Get-Section 'routes' { Get-NetRoute -DestinationPrefix '0.0.0.0/0','::/0' -ErrorAction Stop | Select-Object InterfaceIndex,@{n='Family';e={[string]$_.AddressFamily}},NextHop })
$dns = @(Get-Section 'dns' { Get-DnsClientServerAddress -ErrorAction Stop | Select-Object InterfaceIndex,@{n='Family';e={[string]$_.AddressFamily}},@{n='Servers';e={@($_.ServerAddresses)}} })
$dhcp = @(Get-Section 'dhcp' { Get-NetIPInterface -ErrorAction Stop | Select-Object InterfaceIndex,@{n='Family';e={[string]$_.AddressFamily}},@{n='Dhcp';e={[string]$_.Dhcp}} })
$leases = @(Get-Section 'leases' { Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=TRUE' -ErrorAction Stop | Select-Object InterfaceIndex,DHCPEnabled,DHCPServer,@{n='LeaseObtained';e={if($_.DHCPLeaseObtained){$_.DHCPLeaseObtained.ToString('yyyy-MM-dd HH:mm')}}},@{n='LeaseExpires';e={if($_.DHCPLeaseExpires){$_.DHCPLeaseExpires.ToString('yyyy-MM-dd HH:mm')}}} })
[pscustomobject]@{adapters=$adapters;routes=$routes;dns=$dns;dhcp=$dhcp;leases=$leases;failed=@($global:failed)} | ConvertTo-Json -Depth 4 -Compress
"""

STATUS_TEXT = {"up": "Up (connected)", "disconnected": "Disconnected (no link)", "disabled": "Disabled",
               "not present": "Not present", "testing": "Testing", "dormant": "Dormant",
               "lower layer down": "Lower layer down"}


@dataclass(frozen=True)
class NetworkSources:
    interfaces: Callable[[], dict[str, list[tuple[str, str, str]]]]   # name -> [(family, address, netmask)]
    if_stats: Callable[[], dict[str, tuple[bool, int]]]               # name -> (is_up, speed_mbps)
    powershell_json: Callable[[str], list[dict]]
    now: Callable[[], datetime]


def _interfaces() -> dict[str, list[tuple[str, str, str]]]:
    import socket

    import psutil
    out: dict[str, list[tuple[str, str, str]]] = {}
    for name, addrs in psutil.net_if_addrs().items():
        rows = []
        for a in addrs:
            if a.family == socket.AF_INET:
                fam = "ipv4"
            elif a.family == socket.AF_INET6:
                fam = "ipv6"
            elif a.family == psutil.AF_LINK:
                fam = "mac"
            else:
                continue
            rows.append((fam, a.address or "", a.netmask or ""))
        out[name] = rows
    return out


def _if_stats() -> dict[str, tuple[bool, int]]:
    import psutil
    return {n: (st.isup, st.speed) for n, st in psutil.net_if_stats().items()}


def default_sources() -> NetworkSources:
    return NetworkSources(interfaces=_interfaces, if_stats=_if_stats,
                          powershell_json=run_powershell_json, now=datetime.now)


@dataclass
class NetworkScan:
    sections: list[InfoSection]
    gateways: list[str] = field(default_factory=list)   # IPv4 default gateways of adapters that are up


# --- parsing the PowerShell result ------------------------------------------------------

@dataclass
class _Ps:
    adapters: dict[str, dict]                       # lower-case name -> row
    routes: dict[tuple[int, str], list[str]]
    dns: dict[tuple[int, str], list[str]]
    dhcp: dict[tuple[int, str], str]
    leases: dict[int, dict]
    failed: set[str]


def _as_list(v: object) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [clean_value(x) for x in v if clean_value(x)]
    return [clean_value(v)] if clean_value(v) else []


def _parse_ps(rows: list[dict]) -> _Ps:
    if not rows or not isinstance(rows[0], dict):
        raise CollectionError("PowerShell returned no network data")
    root = rows[0]
    failed = set(_as_list(root.get("failed")))
    tables: dict[str, list[dict]] = {}
    for key in ("adapters", "routes", "dns", "dhcp", "leases"):
        val = root.get(key)
        if not isinstance(val, list):
            failed.add(key)
            val = []
        tables[key] = [r for r in val if isinstance(r, dict)]
    adapters = {clean_value(r.get("Name")).lower(): r for r in tables["adapters"] if clean_value(r.get("Name"))}
    routes: dict[tuple[int, str], list[str]] = {}
    for r in tables["routes"]:
        idx, hop = to_int(r.get("InterfaceIndex")), clean_value(r.get("NextHop"))
        if idx is None or hop in ("", "0.0.0.0", "::"):   # on-link routes are not gateways
            continue
        routes.setdefault((idx, clean_value(r.get("Family"))), []).append(hop)
    dns: dict[tuple[int, str], list[str]] = {}
    for r in tables["dns"]:
        idx = to_int(r.get("InterfaceIndex"))
        if idx is not None:
            dns.setdefault((idx, clean_value(r.get("Family"))), []).extend(_as_list(r.get("Servers")))
    dhcp = {(to_int(r.get("InterfaceIndex")), clean_value(r.get("Family"))): clean_value(r.get("Dhcp"))
            for r in tables["dhcp"] if to_int(r.get("InterfaceIndex")) is not None}
    leases = {to_int(r.get("InterfaceIndex")): r for r in tables["leases"] if to_int(r.get("InterfaceIndex")) is not None}
    return _Ps(adapters, routes, dns, dhcp, leases, failed)  # type: ignore[arg-type]


# --- formatting helpers --------------------------------------------------------------------

def _strip_scope(addr: str) -> str:
    return addr.split("%", 1)[0]


def _ipv4_line(addr: str, mask: str) -> str:
    parts = [addr]
    if mask:
        parts.append(f"mask {mask}")
        try:
            parts.append(f"network {ipaddress.ip_network(f'{addr}/{mask}', strict=False)}")
        except ValueError:
            pass
    if addr.startswith("169.254."):
        parts.append("self-assigned")
    return " \u00b7 ".join(parts)


def _ipv6_line(addr: str, mask: str) -> str:
    addr = _strip_scope(addr)
    line = addr
    if mask:
        try:
            line += f"/{bin(int(ipaddress.ip_address(mask))).count('1')}"
        except ValueError:
            pass
    if addr.lower().startswith("fe80:"):
        line += " (link-local)"
    return line


def _is_loopback_only(rows: list[tuple[str, str, str]]) -> bool:
    ips = [(f, _strip_scope(a)) for f, a, _m in rows if f in ("ipv4", "ipv6") and a]
    has_mac = any(f == "mac" and a and set(a) - set("0:-") for f, a, _m in rows)
    return bool(ips) and not has_mac and all(a.startswith("127.") or a == "::1" for _f, a in ips)


def _kind_of(text: str) -> "str | None":
    t = text.lower()
    if "802.11" in t or "wireless lan" in t:
        return "Wi-Fi"
    if "bluetooth" in t:
        return "Bluetooth"
    if "wireless wan" in t or "mobile" in t:
        return "Mobile broadband"
    if "802.3" in t:
        return "Ethernet"
    return None


def _media_kind(ad: dict) -> str:
    # PhysicalMediaType is the more specific field (a Bluetooth adapter reports MediaType "802.3").
    physical, media = clean_value(ad.get("PhysicalMediaType")), clean_value(ad.get("MediaType"))
    kind = _kind_of(physical) or _kind_of(media)
    if kind:
        return kind
    raw = physical or media
    if not raw or raw.lower() in ("unspecified", "unknown"):
        raise CollectionError("Windows did not report the connection type")
    return raw


# --- collector -------------------------------------------------------------------------------

def _fail(msg: str) -> Reading:
    raise CollectionError(msg)


def collect_network(sources: NetworkSources | None = None) -> NetworkScan:
    s = sources or default_sources()
    now = s.now()
    try:
        ifaces = s.interfaces()
    except Exception as exc:  # noqa: BLE001 - boundary; never log addresses
        reason = f"Could not list network adapters ({type(exc).__name__})"
        return NetworkScan([InfoSection("network", "Network adapters", [
            make_field("adapters", "Network adapters", SRC_PSUTIL, lambda: _fail(reason))], now, PRIVACY_NOTE)])
    try:
        stats = s.if_stats()
    except Exception:  # noqa: BLE001
        stats = {}
    ps: _Ps | None = None
    ps_err = ""
    try:
        ps = _parse_ps(s.powershell_json(NETWORK_SCRIPT))
    except CollectionError as exc:
        ps_err = str(exc)

    visible = {n: rows for n, rows in ifaces.items() if not _is_loopback_only(rows)}
    names = list(visible)
    if ps:
        known = {n.lower() for n in names}
        names += [clean_value(r.get("Name")) for k, r in ps.adapters.items() if k not in known]

    def info(name: str) -> dict:
        ad = ps.adapters.get(name.lower()) if ps else None
        idx = to_int(ad.get("InterfaceIndex")) if ad else None
        is_up = (clean_value(ad.get("Status")).lower() == "up") if ad and clean_value(ad.get("Status")) \
            else bool(stats.get(name, (False, 0))[0])
        return {"ad": ad, "idx": idx, "up": is_up}

    meta = {n: info(n) for n in names}
    names.sort(key=lambda n: (not meta[n]["up"], n.lower()))

    sections: list[InfoSection] = []
    gateways: list[str] = []
    for i, name in enumerate(names, 1):
        rows = visible.get(name, [])
        ad, idx, up = meta[name]["ad"], meta[name]["idx"], meta[name]["up"]
        v4 = [(a, m) for f, a, m in rows if f == "ipv4" and a]
        v6 = [(a, m) for f, a, m in rows if f == "ipv6" and a]
        mac = next((a for f, a, _m in rows if f == "mac" and a), "") or (clean_value(ad.get("MacAddress")) if ad else "")

        def need_ps(section: str | None = None):
            if ps is None:
                raise CollectionError(ps_err or "Windows networking data was not available")
            if section and section in ps.failed:
                raise CollectionError(f"Windows could not provide this data ({section})")
            if idx is None:
                raise CollectionError("This adapter was not matched to Windows networking data")

        def status() -> Reading:
            if ad is not None and clean_value(ad.get("Status")):
                raw = clean_value(ad.get("Status"))
                return Reading(STATUS_TEXT.get(raw.lower(), raw), SRC_NET)
            if name in stats:
                return Reading("Up" if stats[name][0] else "Down (disconnected or disabled)", SRC_PSUTIL,
                               "Detailed status needs PowerShell data." if ps is None else "")
            raise CollectionError("Status was not reported")

        def kind() -> Reading:
            if ps is None:
                raise CollectionError(ps_err or "Windows networking data was not available")
            if ad is None:
                raise CollectionError("Windows did not describe this adapter")
            return Reading(_media_kind(ad), SRC_NET)

        def adapter_class() -> Reading:
            if ps is None:
                raise CollectionError(ps_err or "Windows networking data was not available")
            if ad is None:
                raise CollectionError("Windows did not describe this adapter")
            virtual = clean_value(ad.get("Virtual")).lower() == "true"
            hardware = clean_value(ad.get("HardwareInterface")).lower() != "false"
            return Reading("Virtual / software adapter" if virtual or not hardware else "Physical adapter", SRC_NET,
                           "Based on Windows' adapter flags.")

        def speed() -> Reading:
            raw = clean_value(ad.get("LinkSpeed")) if ad else ""
            if raw and not raw.lower().startswith("0 "):
                return Reading(raw, SRC_NET)
            mbps = stats.get(name, (False, 0))[1]
            if mbps and mbps > 0:
                return Reading(f"{mbps:,} Mbps", SRC_PSUTIL)
            raise CollectionError("Link speed not reported (the adapter may be disconnected)")

        def mac_field() -> Reading:
            if not mac:
                raise CollectionError("No MAC address reported")
            return Reading(mac, SRC_PSUTIL)

        def ipv4() -> Reading:
            note = "" if not any(a.startswith("169.254.") for a, _ in v4) else \
                "A 169.254.x.x address is self-assigned: no DHCP server answered."
            if not v4:
                return Reading("", SRC_PSUTIL, "No IPv4 address assigned.")
            return Reading("\n".join(_ipv4_line(a, m) for a, m in v4), SRC_PSUTIL, note)

        def ipv6() -> Reading:
            if not v6:
                return Reading("", SRC_PSUTIL, "No IPv6 address assigned.")
            return Reading("\n".join(_ipv6_line(a, m) for a, m in v6), SRC_PSUTIL)

        def gateway() -> Reading:
            need_ps("routes")
            gws = [f"{h} (IPv4)" for h in ps.routes.get((idx, "IPv4"), [])] + \
                  [f"{h} (IPv6)" for h in ps.routes.get((idx, "IPv6"), [])]
            return Reading("\n".join(gws), SRC_NET, "" if gws else "No default gateway on this adapter.")

        def dns() -> Reading:
            need_ps("dns")
            servers = [f"{h}" for fam in ("IPv4", "IPv6") for h in ps.dns.get((idx, fam), [])]
            return Reading("\n".join(servers), SRC_NET, "" if servers else "No DNS servers configured on this adapter.")

        def dhcp() -> Reading:
            need_ps("dhcp")
            v = ps.dhcp.get((idx, "IPv4"))
            if not v:
                raise CollectionError("Windows did not report DHCP settings for this adapter")
            return Reading(f"{v} (IPv4)", SRC_NET)

        def lease_row() -> dict:
            need_ps("leases")
            return ps.leases.get(idx, {})

        def dhcp_server() -> Reading:
            r = lease_row()
            if clean_value(r.get("DHCPEnabled")).lower() != "true":
                return Reading("", SRC_NET, "This adapter is not using DHCP.")
            return Reading(clean_value(r.get("DHCPServer")), SRC_NET)

        def dhcp_lease() -> Reading:
            r = lease_row()
            if clean_value(r.get("DHCPEnabled")).lower() != "true":
                return Reading("", SRC_NET, "This adapter is not using DHCP.")
            got, exp = clean_value(r.get("LeaseObtained")), clean_value(r.get("LeaseExpires"))
            if not got and not exp:
                return Reading("", SRC_NET, "No lease times reported.")
            return Reading(f"obtained {got or '?'} \u00b7 expires {exp or '?'}", SRC_NET)

        desc = clean_value(ad.get("InterfaceDescription")) if ad else ""
        fields = [
            make_field("status", "Status", SRC_NET, status),
            make_field("connection_type", "Connection type", SRC_NET, kind),
            make_field("adapter_class", "Adapter kind", SRC_NET, adapter_class),
            make_field("link_speed", "Link speed", SRC_NET, speed),
            make_field("mac", "MAC address", SRC_PSUTIL, mac_field),
            make_field("ipv4", "IPv4 address", SRC_PSUTIL, ipv4),
            make_field("ipv6", "IPv6 address", SRC_PSUTIL, ipv6),
            make_field("gateway", "Default gateway", SRC_NET, gateway),
            make_field("dns", "DNS servers", SRC_NET, dns),
            make_field("dhcp", "DHCP", SRC_NET, dhcp),
            make_field("dhcp_server", "DHCP server", SRC_NET, dhcp_server),
            make_field("dhcp_lease", "DHCP lease", SRC_NET, dhcp_lease),
        ]
        sections.append(InfoSection(f"net_adapter_{i}", f"{name} \u2014 {desc}" if desc else name, fields, now))
        if up and ps is not None and idx is not None and "routes" not in ps.failed:
            for h in ps.routes.get((idx, "IPv4"), []):
                if h not in gateways:
                    gateways.append(h)

    total, up_count = len(names), sum(1 for n in names if meta[n]["up"])
    overview = [make_field("adapters", "Adapters found", SRC_PSUTIL, lambda: Reading(
        f"{total} adapter{'s' if total != 1 else ''} ({up_count} up)", SRC_PSUTIL,
        "" if ps is not None else "Adapter details are limited because PowerShell data was unavailable."))]
    sections.insert(0, InfoSection("network", "Network overview", overview, now, ADAPTER_NOTE + " " + PRIVACY_NOTE))
    return NetworkScan(sections, gateways)


if __name__ == "__main__":  # python -m pcinsight.core.network_info
    from .models import Status
    scan = collect_network()
    for sec in scan.sections:
        print(f"\n== {sec.title} ==")
        for f in sec.fields:
            print(f"{f.label:18} {(f.value if f.status is Status.OK else '<' + f.status.value + '> ' + f.note)!s}")
    print("\nDefault IPv4 gateways:", scan.gateways)
