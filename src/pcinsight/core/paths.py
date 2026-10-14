"""Where PCInsight keeps its own files (settings, scan history, logs). Never inside the program folder."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def data_dir(env: Mapping[str, str] | None = None, os_name: str | None = None, home: Path | None = None) -> Path:
    """Per-user data folder. Set PCINSIGHT_DATA_DIR to override (portable use, tests)."""
    env = os.environ if env is None else env
    os_name = os.name if os_name is None else os_name
    home = Path.home() if home is None else home
    override = env.get("PCINSIGHT_DATA_DIR")
    if override:
        return Path(override)
    if os_name == "nt":
        return Path(env.get("APPDATA") or home / "AppData" / "Roaming") / "PCInsight"
    return Path(env.get("XDG_DATA_HOME") or home / ".local" / "share") / "PCInsight"
