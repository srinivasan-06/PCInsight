"""Scan orchestration. Each collector is guarded so one failure never blocks the others."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .cpu_board_info import collect_cpu_board_bios
from .models import InfoSection, SystemOverview
from .system_info import collect_system_overview

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    system: SystemOverview
    scanned_at: datetime
    hardware: list[InfoSection] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def section(self, key: str) -> InfoSection | None:
        return next((s for s in self.hardware if s.key == key), None)


def run_scan(system_collector: Callable[[], SystemOverview] = collect_system_overview,
             hardware_collector: Callable[[], list[InfoSection]] = collect_cpu_board_bios) -> ScanResult:
    system = system_collector()
    hardware: list[InfoSection] = []
    errors: list[str] = []
    try:
        hardware = hardware_collector()
    except Exception as exc:
        logger.exception("CPU/motherboard/BIOS collection failed")
        errors.append(f"CPU, motherboard and BIOS could not be read ({type(exc).__name__})")
    return ScanResult(system=system, scanned_at=system.collected_at, hardware=hardware, errors=errors)
