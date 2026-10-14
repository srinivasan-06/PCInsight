"""Turning a ScanResult into plain JSON-safe data and back (used by the scan history).
Loading validates everything: damaged or foreign data raises ValueError, never a crash later."""
from __future__ import annotations

from datetime import datetime

from .models import InfoField, InfoSection, Status, SystemOverview
from .scan import ScanResult

SCHEMA = 1


def _field_to(f: InfoField) -> dict:
    return {"key": f.key, "label": f.label, "value": f.value, "status": f.status.value,
            "source": f.source, "note": f.note}


def _section_to(s: InfoSection) -> dict:
    return {"key": s.key, "title": s.title, "fields": [_field_to(f) for f in s.fields],
            "collected_at": s.collected_at.isoformat(), "note": s.note}


def result_to_dict(r: ScanResult) -> dict:
    return {"schema": SCHEMA, "scanned_at": r.scanned_at.isoformat(),
            "system": {"fields": [_field_to(f) for f in r.system.fields],
                       "collected_at": r.system.collected_at.isoformat()},
            "hardware": [_section_to(s) for s in r.hardware],
            "errors": list(r.errors), "gateways": list(r.gateways)}


def _str(v: object, what: str, allow_none: bool = False) -> "str | None":
    if v is None and allow_none:
        return None
    if not isinstance(v, str):
        raise ValueError(f"{what} must be text")
    return v


def _dt(v: object, what: str) -> datetime:
    try:
        return datetime.fromisoformat(_str(v, what))  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{what} is not a valid date") from exc


def _field_from(d: object) -> InfoField:
    if not isinstance(d, dict):
        raise ValueError("a field must be an object")
    return InfoField(key=_str(d.get("key"), "key"), label=_str(d.get("label"), "label"),  # type: ignore[arg-type]
                     value=_str(d.get("value"), "value", allow_none=True), status=Status(d.get("status")),
                     source=_str(d.get("source"), "source"), note=_str(d.get("note", ""), "note"))  # type: ignore[arg-type]


def _list(v: object, what: str) -> list:
    if not isinstance(v, list):
        raise ValueError(f"{what} must be a list")
    return v


def _section_from(d: object) -> InfoSection:
    if not isinstance(d, dict):
        raise ValueError("a section must be an object")
    return InfoSection(key=_str(d.get("key"), "key"), title=_str(d.get("title"), "title"),  # type: ignore[arg-type]
                       fields=[_field_from(f) for f in _list(d.get("fields"), "fields")],
                       collected_at=_dt(d.get("collected_at"), "collected_at"), note=_str(d.get("note", ""), "note"))  # type: ignore[arg-type]


def result_from_dict(d: object) -> ScanResult:
    if not isinstance(d, dict):
        raise ValueError("a saved scan must be an object")
    schema = d.get("schema")
    if not isinstance(schema, int) or schema < 1:
        raise ValueError("unknown format")
    if schema > SCHEMA:
        raise ValueError("saved by a newer version of PCInsight")
    system = d.get("system")
    if not isinstance(system, dict):
        raise ValueError("system data is missing")
    return ScanResult(
        system=SystemOverview(fields=[_field_from(f) for f in _list(system.get("fields"), "system fields")],
                              collected_at=_dt(system.get("collected_at"), "system collected_at")),
        scanned_at=_dt(d.get("scanned_at"), "scanned_at"),
        hardware=[_section_from(s) for s in _list(d.get("hardware"), "hardware")],
        errors=[_str(e, "error") for e in _list(d.get("errors", []), "errors")],        # type: ignore[misc]
        gateways=[_str(g, "gateway") for g in _list(d.get("gateways", []), "gateways")])  # type: ignore[misc]
