"""Plain data models shared by collectors, UI and (later) the report generator."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Status(str, Enum):
    OK = "ok"                    # value was retrieved
    EMPTY = "empty"              # source answered, but the value is blank
    UNAVAILABLE = "unavailable"  # value could not be retrieved (see note)


@dataclass(frozen=True)
class InfoField:
    key: str
    label: str
    value: str | None
    status: Status
    source: str
    note: str = ""


@dataclass
class SystemOverview:
    fields: list[InfoField]
    collected_at: datetime

    def get(self, key: str) -> InfoField | None:
        return next((f for f in self.fields if f.key == key), None)

    @property
    def unavailable_count(self) -> int:
        return sum(1 for f in self.fields if f.status is not Status.OK)


def format_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")
