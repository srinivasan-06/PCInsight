"""Scan orchestration. Collectors run in parallel and are isolated from each other."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .cpu_board_info import collect_cpu_board_bios
from .gpu_info import collect_gpus
from .memory_info import collect_memory
from .models import InfoSection, SystemOverview
from .network_info import NetworkScan, collect_network
from .storage_info import collect_storage
from .system_info import collect_system_overview

logger = logging.getLogger(__name__)

NETWORK_PREFIXES = ("network", "net")


@dataclass
class ScanResult:
    system: SystemOverview
    scanned_at: datetime
    hardware: list[InfoSection] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    gateways: list[str] = field(default_factory=list)   # IPv4 default gateways of adapters that are up

    def section(self, key: str) -> InfoSection | None:
        return next((s for s in self.hardware if s.key == key), None)

    def network_sections(self) -> list[InfoSection]:
        return self.sections_for(*NETWORK_PREFIXES)

    def sections_for(self, *prefixes: str) -> list[InfoSection]:
        """Sections whose key equals a prefix or starts with '<prefix>_'."""
        return [s for s in self.hardware
                if any(s.key == p or s.key.startswith(p + "_") for p in prefixes)]


def run_scan(system_collector: Callable[[], SystemOverview] = collect_system_overview,
             hardware_collector: Callable[[], list[InfoSection]] = collect_cpu_board_bios,
             memory_collector: Callable[[], list[InfoSection]] = collect_memory,
             gpu_collector: Callable[[], list[InfoSection]] = collect_gpus,
             storage_collector: Callable[[], list[InfoSection]] = collect_storage,
             network_collector: Callable[[], NetworkScan] = collect_network) -> ScanResult:
    jobs = [("CPU, motherboard and BIOS", hardware_collector), ("Memory", memory_collector),
            ("Graphics", gpu_collector), ("Storage", storage_collector)]
    hardware: list[InfoSection] = []
    errors: list[str] = []
    gateways: list[str] = []
    with ThreadPoolExecutor(max_workers=len(jobs) + 1) as pool:
        futures = [(label, pool.submit(fn)) for label, fn in jobs]
        net_future = pool.submit(network_collector)
        system = system_collector()
        for label, fut in futures:
            try:
                hardware.extend(fut.result())
            except Exception as exc:  # noqa: BLE001 - isolate collectors
                logger.exception("%s collection failed", label)
                errors.append(f"{label} could not be read ({type(exc).__name__})")
        try:
            net = net_future.result()
            hardware.extend(net.sections)
            gateways = list(net.gateways)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Network collection failed")
            errors.append(f"Network could not be read ({type(exc).__name__})")
    return ScanResult(system=system, scanned_at=system.collected_at, hardware=hardware, errors=errors,
                      gateways=gateways)
