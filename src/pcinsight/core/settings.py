"""User settings, stored as a small JSON file. Loading never crashes: a damaged or hand-edited file falls
back to defaults (value by value where possible) and the damaged file is kept aside, not deleted."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from .paths import data_dir
from .ports_info import DEFAULT_IMPORTANT_PORTS

logger = logging.getLogger(__name__)

THEMES = ("light", "dark")
PAPERS = ("A4", "Letter")
RETENTION_DAYS_CHOICES = (7, 30, 90, 365, 0)           # 0 = keep forever
RETENTION_MAX_CHOICES = (10, 25, 50, 100, 500)
MAX_PORTS = 200
SCHEMA_VERSION = 1


class SettingsError(Exception):
    """Settings could not be saved. The message is safe to show to the user."""


@dataclass(frozen=True)
class Settings:
    theme: str = "light"
    paper: str = "A4"
    report_include_network: bool = True
    report_include_ports: bool = True
    report_include_connectivity: bool = True
    important_ports: tuple[int, ...] = tuple(DEFAULT_IMPORTANT_PORTS)
    history_enabled: bool = True
    retention_days: int = 90
    retention_max_scans: int = 50
    diagnostic_logging: bool = False


def parse_port_list(text: str) -> tuple[list[int], list[str], list[str]]:
    """Parse '22, 80 443' into (ports, errors, warnings). Errors mean the list must not be applied."""
    ports: list[int] = []
    errors: list[str] = []
    warnings: list[str] = []
    for token in (t for t in re.split(r"[,\s;]+", text.strip()) if t):
        if not re.fullmatch(r"[0-9]+", token):
            errors.append(f"\"{token}\" is not a port number")
            continue
        n = int(token)
        if not 1 <= n <= 65535:
            errors.append(f"{n} is outside the valid range 1-65535")
        elif n in ports:
            warnings.append(f"{n} is listed more than once (counted once)")
        else:
            ports.append(n)
    if len(ports) > MAX_PORTS:
        errors.append(f"At most {MAX_PORTS} ports are allowed (you entered {len(ports)})")
    return ports, errors, warnings


def _int_in(value: object, lo: int, hi: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi


def validate(raw: object) -> tuple[Settings, list[str]]:
    """Build Settings from untrusted data, replacing each bad value with its default. Returns (settings, notes)."""
    defaults = Settings()
    notes: list[str] = []
    if not isinstance(raw, dict):
        return defaults, ["The settings file did not contain a settings object"]
    out: dict[str, object] = {}

    def pick(key: str, ok, default):
        if key not in raw:
            out[key] = default
        elif ok(raw[key]):
            out[key] = raw[key]
        else:
            out[key] = default
            notes.append(f"Setting \"{key}\" was invalid and was reset")

    pick("theme", lambda v: v in THEMES, defaults.theme)
    pick("paper", lambda v: v in PAPERS, defaults.paper)
    for key in ("report_include_network", "report_include_ports", "report_include_connectivity",
                "history_enabled", "diagnostic_logging"):
        pick(key, lambda v: isinstance(v, bool), getattr(defaults, key))
    pick("retention_days", lambda v: _int_in(v, 0, 3650), defaults.retention_days)
    pick("retention_max_scans", lambda v: _int_in(v, 1, 1000), defaults.retention_max_scans)
    ports = raw.get("important_ports", None)
    if "important_ports" not in raw:
        out["important_ports"] = defaults.important_ports
    elif (isinstance(ports, list) and len(ports) <= MAX_PORTS and len(set(ports)) == len(ports)
          and all(_int_in(p, 1, 65535) for p in ports)):
        out["important_ports"] = tuple(ports)       # an empty list is allowed: "check no ports"
    else:
        out["important_ports"] = defaults.important_ports
        notes.append("Setting \"important_ports\" was invalid and was reset")
    return Settings(**out), notes   # type: ignore[arg-type]


class SettingsStore:
    """Holds the live settings and saves every change immediately and atomically."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else data_dir() / "settings.json"
        self.settings = Settings()
        self.load_warning = ""      # shown to the user when the file was damaged
        self.last_error = ""        # set when the latest change could not be written to disk
        self.load()

    def load(self) -> Settings:
        self.load_warning = ""
        if not self.path.exists():
            self.settings = Settings()
            return self.settings
        try:
            text = self.path.read_text(encoding="utf-8-sig")
            raw = json.loads(text)
        except (ValueError, UnicodeDecodeError):
            self.settings = Settings()
            self.load_warning = ("Your settings file was damaged, so default settings are being used. "
                                 f"The damaged file was kept as {self._quarantine().name}.")
            return self.settings
        except OSError as exc:
            self.settings = Settings()
            self.load_warning = f"Your settings file could not be read ({type(exc).__name__}); defaults are being used."
            return self.settings
        self.settings, notes = validate(raw)
        if notes:
            self.load_warning = "Some settings were invalid and were reset to defaults: " + "; ".join(notes) + "."
        return self.settings

    def _quarantine(self) -> Path:
        target = self.path.with_name(f"{self.path.name}.damaged-{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            os.replace(self.path, target)
        except OSError:
            logger.warning("Could not set the damaged settings file aside")
        return target

    def save(self, settings: Settings | None = None) -> None:
        data = asdict(settings or self.settings)
        data["important_ports"] = list(data["important_ports"])
        data["schema"] = SCHEMA_VERSION
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except PermissionError as exc:
            self._drop(tmp)
            raise SettingsError("PCInsight is not allowed to write its settings file.") from exc
        except OSError as exc:
            self._drop(tmp)
            raise SettingsError(f"The settings file could not be written ({type(exc).__name__}).") from exc

    @staticmethod
    def _drop(tmp: Path) -> None:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass

    def update(self, **changes: object) -> bool:
        """Apply and save changes. Returns False if saving failed (the change stays active until exit)."""
        candidate, _ = validate({**asdict(self.settings), **{k: (list(v) if k == "important_ports" else v)
                                                              for k, v in changes.items()}})
        self.settings = candidate
        self.last_error = ""
        try:
            self.save()
        except SettingsError as exc:
            self.last_error = f"{exc} Your change is active until you close PCInsight."
            return False
        return True

    def reset(self) -> bool:
        self.settings = replace(Settings())
        self.last_error = ""
        try:
            self.save()
        except SettingsError as exc:
            self.last_error = f"{exc} Defaults are active until you close PCInsight."
            return False
        return True
