"""Injectable data sources shared by the memory, GPU and storage collectors."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .common import query_cim_all, read_registry_value, run_powershell_json


@dataclass(frozen=True)
class DeviceSources:
    registry: Callable[[str, str], object]
    cim_all: Callable[[str, list[str]], list[dict[str, str]]]
    powershell_json: Callable[[str], list[dict]]
    memory_stats: Callable[[], tuple[int, int]]            # (total, available) bytes
    volumes: Callable[[], list[tuple[str, str, str]]]      # (mountpoint, fstype, opts)
    disk_usage: Callable[[str], tuple[int, int, int]]      # (total, used, free) bytes
    now: Callable[[], datetime]


def _memory_stats() -> tuple[int, int]:
    import psutil
    vm = psutil.virtual_memory()
    return vm.total, vm.available


def _volumes() -> list[tuple[str, str, str]]:
    import psutil
    return [(p.mountpoint, p.fstype, p.opts) for p in psutil.disk_partitions(all=False)]


def _disk_usage(path: str) -> tuple[int, int, int]:
    import psutil
    u = psutil.disk_usage(path)
    return u.total, u.used, u.free


def default_device_sources() -> DeviceSources:
    return DeviceSources(registry=read_registry_value, cim_all=query_cim_all,
                         powershell_json=run_powershell_json, memory_stats=_memory_stats,
                         volumes=_volumes, disk_usage=_disk_usage, now=datetime.now)
