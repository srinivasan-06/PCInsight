"""Scan orchestration. Later modules add their collectors here."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import SystemOverview
from .system_info import collect_system_overview


@dataclass
class ScanResult:
    system: SystemOverview
    scanned_at: datetime


def run_scan() -> ScanResult:
    system = collect_system_overview()
    return ScanResult(system=system, scanned_at=system.collected_at)
