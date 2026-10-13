"""Module 6: local listening-port analyzer.

Looks ONLY at this computer's own socket table. It sends no traffic, scans no other computer, and never
changes firewall rules or stops programs. It never claims a port is reachable from elsewhere, and never
labels UDP endpoints open/closed (UDP has no connection state).
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable

from .common import CollectionError
from .models import InfoField, InfoSection, Status

logger = logging.getLogger(__name__)

SRC = "psutil (this computer's socket table)"
DEFAULT_IMPORTANT_PORTS = [21, 22, 23, 25, 53, 80, 135, 139, 443, 445, 1433, 3306, 3389, 5432, 5900]

# The four statuses used throughout (kept as constants so tests can pin the exact wording).
ST_LISTENING = "Listening locally"
ST_NONE = "No local listener detected"
ST_NO_PROCESS = "Process details unavailable"
ST_UDP = "UDP endpoint detected; remote reachability not verified"

OVERVIEW_NOTE = (
    "This page looks only at this computer; nothing is sent to other computers and no other computer is scanned. "
    "\"Listening locally\" means a program on this PC is waiting for connections on that port. It does not mean other "
    "computers can reach it: your firewall, router and network decide that, and PCInsight does not test it. "
    "\"No local listener detected\" does not prove a port is closed from outside. UDP has no connection state, so UDP "
    "endpoints are listed without claiming they are open or closed. Some process names need administrator rights; "
    "PCInsight does not require them. It never changes firewall rules or stops programs.")

# Conventional names for port numbers. A name is a hint about convention, never proof of what is running.
KNOWN_SERVICES: dict[int, str] = {
    20: "FTP data", 21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 67: "DHCP server", 68: "DHCP client",
    80: "HTTP", 110: "POP3", 123: "NTP", 135: "Microsoft RPC endpoint mapper", 137: "NetBIOS name service",
    138: "NetBIOS datagram service", 139: "NetBIOS session service", 143: "IMAP", 161: "SNMP", 389: "LDAP",
    443: "HTTPS", 445: "SMB (Windows file sharing)", 465: "SMTPS", 587: "SMTP submission", 636: "LDAPS",
    993: "IMAPS", 995: "POP3S", 1433: "Microsoft SQL Server", 1900: "SSDP / UPnP discovery", 3306: "MySQL / MariaDB",
    3389: "Remote Desktop (RDP)", 3702: "WS-Discovery", 5353: "mDNS (Bonjour)", 5355: "LLMNR", 5357: "WSDAPI",
    5432: "PostgreSQL", 5900: "VNC", 5985: "WinRM (HTTP)", 5986: "WinRM (HTTPS)",
    7680: "Windows Delivery Optimization", 8080: "HTTP alternate (often a proxy or dev server)",
    8443: "HTTPS alternate",
}
DYNAMIC_PORT_START = 49152


@dataclass(frozen=True)
class RawEndpoint:
    protocol: str            # "tcp" or "udp"
    family: str              # "ipv4" or "ipv6"
    address: str
    port: int
    pid: "int | None"


@dataclass(frozen=True)
class PortSources:
    connections: Callable[[str], list[RawEndpoint]]       # "tcp" -> listeners only; "udp" -> all local endpoints
    process_name: Callable[[int], str]                    # raises CollectionError(reason) when unavailable
    service_name: Callable[[int, str], "str | None"]
    now: Callable[[], datetime]


def _connections(kind: str) -> list[RawEndpoint]:
    import psutil
    out: list[RawEndpoint] = []
    for c in psutil.net_connections(kind=kind):
        if not c.laddr:
            continue
        if kind == "tcp" and c.status != psutil.CONN_LISTEN:
            continue
        family = "ipv6" if c.family == socket.AF_INET6 else "ipv4"
        out.append(RawEndpoint(kind, family, c.laddr.ip, int(c.laddr.port), c.pid))
    return out


def _process_name(pid: int) -> str:
    import psutil
    try:
        return psutil.Process(pid).name()
    except psutil.NoSuchProcess as exc:
        raise CollectionError("the process had already exited") from exc
    except psutil.AccessDenied as exc:
        raise CollectionError("access denied") from exc
    except Exception as exc:  # noqa: BLE001 - boundary
        raise CollectionError("lookup failed") from exc


def _service_name(port: int, proto: str) -> "str | None":
    if port in KNOWN_SERVICES:
        return KNOWN_SERVICES[port]
    try:
        return f"{socket.getservbyport(port, proto)} (system services list)"
    except OSError:
        return None


def default_sources() -> PortSources:
    return PortSources(connections=_connections, process_name=_process_name,
                       service_name=_service_name, now=datetime.now)


def normalize_ports(ports: Iterable[object]) -> list[int]:
    """Keep valid TCP/UDP port numbers (1-65535), drop duplicates, preserve order."""
    seen: list[int] = []
    for p in ports:
        if isinstance(p, bool) or not isinstance(p, int) or not 1 <= p <= 65535 or p in seen:
            continue
        seen.append(p)
    return seen


def classify_binding(address: str) -> tuple[str, str]:
    """(short label, one-sentence explanation) for a bound address."""
    raw = address.split("%", 1)[0]
    try:
        ip = ipaddress.ip_address(raw)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
    except ValueError:
        return ("unrecognised address",
                "The bound address could not be interpreted, so its exposure is unknown.")
    if ip.is_unspecified:
        return ("all interfaces",
                "Bound to all network interfaces; whether other computers can reach it depends on your firewall "
                "and network, which PCInsight has not tested.")
    if ip.is_loopback:
        return ("loopback only", "Bound to loopback, so only programs on this computer can connect to it.")
    return ("specific address",
            f"Bound to the single address {raw}; whether other computers can reach it depends on your firewall "
            "and network, which PCInsight has not tested.")


def _fmt_addr(address: str, port: int) -> str:
    return f"[{address}]:{port}" if ":" in address else f"{address}:{port}"


def _service_note(port: int, proto: str, s: PortSources) -> str:
    try:
        name = s.service_name(port, proto)
    except Exception:  # noqa: BLE001
        name = None
    if name:
        return f"Port {port} is conventionally used for {name}; PCInsight cannot confirm that is what is running."
    if port >= DYNAMIC_PORT_START:
        return (f"Port {port} is in the dynamic range (often used by Windows RPC and other programs); "
                "there is no conventional service name for it.")
    return f"No conventional service name is known for port {port}."


class _Resolver:
    """Looks up each PID once per scan and keeps the honest reason when a lookup fails."""

    def __init__(self, fn: Callable[[int], str]):
        self._fn = fn
        self._cache: dict[int, tuple["str | None", str]] = {}

    def lookup(self, pid: "int | None") -> tuple["str | None", str]:
        if not pid:
            return None, "no process ID reported"
        if pid not in self._cache:
            try:
                name = self._fn(pid)
                self._cache[pid] = (name, "") if name else (None, "no name returned")
            except CollectionError as exc:
                self._cache[pid] = (None, str(exc))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Process lookup failed: %s", type(exc).__name__)   # never log PIDs/addresses
                self._cache[pid] = (None, "lookup failed")
        return self._cache[pid]

    def describe(self, pid: "int | None") -> tuple[str, bool]:
        """(text, ok). Never raises."""
        name, reason = self.lookup(pid)
        if name:
            return f"{name} (PID {pid})", True
        extra = f"; PID {pid}" if pid else ""
        return f"{ST_NO_PROCESS} ({reason}{extra})", False


def _ok(key: str, label: str, value: str, note: str = "") -> InfoField:
    return InfoField(key, label, value, Status.OK, SRC, note)


def _fail(key: str, label: str, note: str) -> InfoField:
    return InfoField(key, label, None, Status.UNAVAILABLE, SRC, note)


def _load(s: PortSources, kind: str) -> tuple[list[RawEndpoint], str]:
    try:
        raw = s.connections(kind)
    except CollectionError as exc:
        return [], str(exc)
    except Exception as exc:  # noqa: BLE001 - boundary
        logger.warning("Socket table read failed: %s", type(exc).__name__)
        return [], f"The socket table could not be read ({type(exc).__name__})"
    unique = {(e.protocol, e.family, e.address, e.port, e.pid): e for e in raw}
    return sorted(unique.values(), key=lambda e: (e.port, e.address, e.pid or 0)), ""


def collect_ports(sources: PortSources | None = None,
                  important_ports: Iterable[object] | None = None) -> list[InfoSection]:
    s = sources or default_sources()
    now = s.now()
    important = normalize_ports(DEFAULT_IMPORTANT_PORTS if important_ports is None else important_ports)
    resolver = _Resolver(s.process_name)
    tcp, tcp_err = _load(s, "tcp")
    udp, udp_err = _load(s, "udp")

    def endpoint_line(e: RawEndpoint) -> tuple[str, bool]:
        label, _ = classify_binding(e.address)
        proc, ok = resolver.describe(e.pid)
        return f"{_fmt_addr(e.address, e.port)} \u00b7 {label} \u00b7 {proc}", ok

    # --- all TCP listeners -----------------------------------------------------------------
    tcp_gaps = 0
    if tcp_err:
        tcp_fields = [_fail("tcp", "Listening TCP endpoints", tcp_err)]
    elif not tcp:
        tcp_fields = [InfoField("tcp", "Listening TCP endpoints", None, Status.EMPTY, SRC,
                                "No listening TCP endpoints were detected on this computer.")]
    else:
        tcp_fields = []
        for i, e in enumerate(tcp, 1):
            line, ok = endpoint_line(e)
            tcp_gaps += not ok
            svc = s.service_name(e.port, "tcp") if e.port in KNOWN_SERVICES else None
            label = f"{e.port}/TCP" + (f" \u00b7 {svc}" if svc else "")
            note = f"{_service_note(e.port, 'tcp', s)} {classify_binding(e.address)[1]}"
            tcp_fields.append(_ok(f"tcp_{i}", label, f"{ST_LISTENING}\n{line}", note))

    # --- all UDP endpoints (never classified open/closed) ------------------------------------
    udp_gaps = 0
    if udp_err:
        udp_fields = [_fail("udp", "UDP endpoints", udp_err)]
    elif not udp:
        udp_fields = [InfoField("udp", "UDP endpoints", None, Status.EMPTY, SRC,
                                "No local UDP endpoints were detected on this computer.")]
    else:
        udp_fields = []
        for i, e in enumerate(udp, 1):
            line, ok = endpoint_line(e)
            udp_gaps += not ok
            svc = s.service_name(e.port, "udp") if e.port in KNOWN_SERVICES else None
            label = f"{e.port}/UDP" + (f" \u00b7 {svc}" if svc else "")
            note = ("UDP has no connection state, so PCInsight cannot say whether this port is open or closed. "
                    f"{_service_note(e.port, 'udp', s)} {classify_binding(e.address)[1]}")
            udp_fields.append(_ok(f"udp_{i}", label, f"{ST_UDP}\n{line}", note))

    # --- the configurable list of important ports ---------------------------------------------
    imp_fields: list[InfoField] = []
    listening_ports: list[int] = []
    if not important:
        imp_fields = [InfoField("important", "Important ports", None, Status.EMPTY, SRC,
                                "No important ports are configured.")]
    for p in important:
        svc = KNOWN_SERVICES.get(p)
        label = f"Port {p}" + (f" \u00b7 {svc}" if svc else "")
        if tcp_err:
            imp_fields.append(_fail(f"port_{p}", label, tcp_err))
            continue
        hits = [e for e in tcp if e.port == p]
        udp_hits = [e for e in udp if e.port == p] if not udp_err else []
        extra = f"\nUDP endpoint also detected on port {p}; remote reachability not verified" if udp_hits else ""
        if hits:
            listening_ports.append(p)
            lines = "\n".join(endpoint_line(e)[0] for e in hits)
            if all(classify_binding(e.address)[0] == "loopback only" for e in hits):
                tail = "Only loopback listeners were found, so only programs on this computer can connect."
            else:
                tail = ("Listening locally does not mean other computers can reach this port; that depends on "
                        "your firewall and network, which PCInsight has not tested.")
            imp_fields.append(_ok(f"port_{p}", label, f"{ST_LISTENING}\n{lines}{extra}",
                                  f"{_service_note(p, 'tcp', s)} {tail}"))
        else:
            imp_fields.append(_ok(
                f"port_{p}", label, f"{ST_NONE}{extra}",
                f"No program on this PC is listening on TCP port {p}. That does not prove the port is closed from "
                "outside, and it is normal for most of these ports not to be in use."))

    # --- overview -----------------------------------------------------------------------------------------
    n_tcp, n_udp = len(tcp), len(udp)
    if important and not tcp_err:
        imp_text = (f"{', '.join(map(str, listening_ports))} listening ({len(listening_ports)} of {len(important)})"
                    if listening_ports else f"none listening (0 of {len(important)})")
        imp_overview = _ok("important", "Important ports with a local listener", imp_text,
                           "Having one of these listening is not automatically a problem; it depends on the program "
                           "and on your firewall.")
    elif tcp_err:
        imp_overview = _fail("important", "Important ports with a local listener", tcp_err)
    else:
        imp_overview = InfoField("important", "Important ports with a local listener", None, Status.EMPTY, SRC,
                                 "No important ports are configured.")
    gaps = (_ok("process_gaps", "Endpoints without a process name",
                f"{tcp_gaps} of {n_tcp} TCP, {udp_gaps} of {n_udp} UDP",
                "Windows can refuse process names for system or other users' programs. Running PCInsight as "
                "administrator may reveal more; it is not required.")
            if not tcp_err and not udp_err else _fail("process_gaps", "Endpoints without a process name",
                                                      tcp_err or udp_err))
    overview = [
        _ok("tcp_count", "Listening TCP endpoints", str(n_tcp)) if not tcp_err
        else _fail("tcp_count", "Listening TCP endpoints", tcp_err),
        _ok("udp_count", "UDP endpoints (reachability not verified)", str(n_udp)) if not udp_err
        else _fail("udp_count", "UDP endpoints (reachability not verified)", udp_err),
        imp_overview, gaps,
    ]
    return [
        InfoSection("ports", "Listening ports overview", overview, now, OVERVIEW_NOTE),
        InfoSection("ports_important", "Important ports", imp_fields, now,
                    "TCP ports from your important-port list. Not every port here is expected to be open."),
        InfoSection("ports_tcp", "All listening TCP endpoints", tcp_fields, now),
        InfoSection("ports_udp", "All UDP endpoints", udp_fields, now,
                    "UDP endpoints are listed separately and are never classified as open or closed."),
    ]


if __name__ == "__main__":  # python -m pcinsight.core.ports_info
    for sec in collect_ports():
        print(f"\n== {sec.title} ({len(sec.fields)}) ==")
        for f in sec.fields[:40]:
            print(f"{f.label:44} {(f.value if f.status is Status.OK else '<' + f.status.value + '> ' + f.note).splitlines()[0]}")
