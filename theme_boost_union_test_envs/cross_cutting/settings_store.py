"""Shared access to ``<working_dir>/settings.yaml``.

The file holds a single ``values`` mapping. Sections such as ``lifecycle`` and
``email`` are owned by their own API routes; this module lets each of them read
and replace only its own section, serialised by a process-wide lock and written
atomically so a crash never leaves a half-written file.
"""

from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path
from typing import Any

import yaml

from .configuration import config

_lock = threading.RLock()


def settings_path() -> Path:
    return config().working_dir / "settings.yaml"


def load_values(path: Path | None = None) -> dict[str, Any]:
    """Return the ``values`` mapping (empty when the file does not exist)."""
    path = path or settings_path()
    if not path.exists():
        return {}
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}
    values = data.get("values", {}) if isinstance(data, dict) else {}
    return dict(values) if isinstance(values, dict) else {}


def save_values(values: dict[str, Any], path: Path | None = None) -> None:
    """Atomically replace the whole ``values`` mapping."""
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".yaml")
        try:
            with os.fdopen(fd, "w") as f:
                yaml.safe_dump({"values": values}, f, sort_keys=False)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


def get_section(name: str, path: Path | None = None) -> dict[str, Any]:
    section = load_values(path).get(name)
    return dict(section) if isinstance(section, dict) else {}


def set_section(name: str, section: dict[str, Any], path: Path | None = None) -> None:
    """Replace one section, keeping every other value untouched."""
    with _lock:
        values = load_values(path)
        values[name] = section
        save_values(values, path)
