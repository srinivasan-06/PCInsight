"""Module 5b: optional connectivity tests. These DO send small network probes, so they only run
when the user asks. Targets: the default gateway (ping), 1.1.1.1 then 8.8.8.8 on TCP 443
(connection attempt only, no data sent), and a DNS lookup of example.com via the system resolver."""
from __future__ import annotations

import ipaddress
import os
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .common import CollectionError, Reading, make_field
from .models import InfoField, InfoSection

INTERNET_TARGETS = [("1.1.1.1", 443), ("8.8.8.8", 443)]
DNS_NAME = "example.com"
PING_TIMEOUT_MS = 2000
TCP_TIMEOUT_S = 3.0
DNS_TIMEOUT_S = 5.0
MAX_GATEWAYS = 2
SRC = "Connectivity test"
NOTE = ("These tests send small network probes right now and show whether a path currently works; results can "
        "change at any moment. They are separate from the local configuration, which is only read, never tested.")


@dataclass(frozen=True)
class ConnectivitySources:
    ping: Callable[[str], tuple[bool, "float | None"]]      # (replied, round-trip ms); raises CollectionError
    tcp_connect: Callable[[str, int, float], float]         # ms; raises OSError on failure
    resolve: Callable[[str], int]                           # number of addresses; raises OSError
    now: Callable[[], datetime]


@dataclass
class ConnectivityResult:
    sections: list[InfoSection]
    ran_at: datetime


def _is_windows() -> bool:
    return os.name == "nt"


def _ping(host: str) -> tuple[bool, "float | None"]:
    try:
        ipaddress.ip_address(host)
    except ValueError as exc:
        raise CollectionError("Gateway is not a valid IP address") from exc
    if not _is_windows():
        raise CollectionError("The ping test is only implemented for Windows")
    try:
        proc = subprocess.run(["ping", "-n", "1", "-w", str(PING_TIMEOUT_MS), host], capture_output=True,
                              text=True, errors="replace", timeout=PING_TIMEOUT_MS / 1000 + 4,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError as exc:
        raise CollectionError("ping.exe was not found") from exc
    except subprocess.TimeoutExpired:
        return False, None
    except OSError as exc:
        raise CollectionError("ping.exe could not be started") from exc
    out = proc.stdout or ""
    if "TTL=" not in out.upper():     # replies from the gateway itself saying "unreachable" have no TTL
        return False, None
    m = re.search(r"[=<]\s*(\d+)\s*ms", out, re.IGNORECASE)
    return True, float(m.group(1)) if m else None


def _tcp_connect(host: str, port: int, timeout: float) -> float:
    start = time.perf_counter()
    with socket.create_connection((host, port), timeout=timeout):
        return (time.perf_counter() - start) * 1000


def _resolve(name: str) -> int:
    box: dict[str, object] = {}

    def work() -> None:
        try:
            box["n"] = len({ai[4][0] for ai in socket.getaddrinfo(name, None)})
        except Exception as exc:  # noqa: BLE001 - anything in this thread must become a clean failure
            box["err"] = exc if isinstance(exc, OSError) else OSError(type(exc).__name__)

    t = threading.Thread(target=work, daemon=True)   # getaddrinfo cannot be interrupted; never block exit
    t.start()
    t.join(DNS_TIMEOUT_S)
    if t.is_alive():
        raise TimeoutError("DNS lookup timed out")
    if "err" in box:
        raise box["err"]  # type: ignore[misc]
    return int(box["n"])  # type: ignore[arg-type]


def default_sources() -> ConnectivitySources:
    return ConnectivitySources(ping=_ping, tcp_connect=_tcp_connect, resolve=_resolve, now=datetime.now)


def _why(exc: OSError) -> str:
    if isinstance(exc, TimeoutError):
        return "timed out"
    if isinstance(exc, ConnectionRefusedError):
        return "connection refused"
    return "network unreachable or blocked"


def run_connectivity_checks(gateways: list[str], sources: ConnectivitySources | None = None) -> ConnectivityResult:
    s = sources or default_sources()

    def gateway_field(i: int, gw: str) -> InfoField:
        def run() -> Reading:
            replied, ms = s.ping(gw)
            if replied:
                return Reading(f"Reply received" + (f" ({ms:.0f} ms)" if ms is not None else ""), SRC)
            return Reading(f"No reply within {PING_TIMEOUT_MS // 1000} seconds", SRC,
                           "Some routers ignore ping, so no reply does not prove the gateway is down.")
        return make_field(f"gateway_{i}", f"Ping default gateway {gw}", SRC, run)

    def internet_field() -> InfoField:
        def run() -> Reading:
            failures = []
            for n, (host, port) in enumerate(INTERNET_TARGETS):
                try:
                    ms = s.tcp_connect(host, port, TCP_TIMEOUT_S)
                except OSError as exc:
                    failures.append(f"{host}:{port} ({_why(exc)})")
                    continue
                note = "" if n == 0 else "The first target failed; the backup target succeeded."
                return Reading(f"Connected to {host}:{port} ({ms:.0f} ms)", SRC, note)
            return Reading("Could not connect: " + ", ".join(failures), SRC,
                           "A firewall, VPN or captive portal can also block this test.")
        return make_field("internet", "Internet connection (TCP)", SRC, run)

    def dns_field() -> InfoField:
        def run() -> Reading:
            start = time.perf_counter()
            try:
                s.resolve(DNS_NAME)
            except OSError as exc:
                return Reading(f"Could not resolve {DNS_NAME} ({_why(exc)})", SRC,
                               "Check the DNS servers listed for your adapter.")
            return Reading(f"Resolved {DNS_NAME} ({(time.perf_counter() - start) * 1000:.0f} ms)", SRC)
        return make_field("dns", "DNS name resolution", SRC, run)

    gws = list(dict.fromkeys(gateways))[:MAX_GATEWAYS]
    with ThreadPoolExecutor(max_workers=3 + len(gws)) as pool:
        gw_futs = [pool.submit(gateway_field, i, gw) for i, gw in enumerate(gws, 1)]
        net_fut, dns_fut = pool.submit(internet_field), pool.submit(dns_field)
        fields = [f.result() for f in gw_futs]
        if not gws:
            fields.append(make_field("gateway", "Ping default gateway", SRC, lambda: (_ for _ in ()).throw(
                CollectionError("No default gateway known. Run a scan first, or this PC may not have one."))))
        fields += [net_fut.result(), dns_fut.result()]
    ran_at = s.now()
    return ConnectivityResult([InfoSection("net_connectivity", "Connectivity tests", fields, ran_at, NOTE)], ran_at)


if __name__ == "__main__":  # python -m pcinsight.core.connectivity   (sends probes!)
    from .models import Status
    res = run_connectivity_checks([])
    for f in res.sections[0].fields:
        print(f"{f.label:36} {f.value if f.status is Status.OK else '<' + f.status.value + '> ' + f.note}")
