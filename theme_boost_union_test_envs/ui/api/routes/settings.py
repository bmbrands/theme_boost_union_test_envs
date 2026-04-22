"""Persist admin settings to ``<working_dir>/settings.yaml``.

The frontend renders a hard-coded list of configuration items with default
values. This endpoint stores only the overrides the user has changed so that
the catalogue can be edited without redeploying the backend.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from theme_boost_union_test_envs.cross_cutting import config

router = APIRouter(prefix="/api/settings", tags=["settings"])

_write_lock = threading.Lock()


class SettingsResponse(BaseModel):
    values: dict[str, Any]


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


def _settings_path() -> Path:
    return config().working_dir / "settings.yaml"


def _load() -> dict[str, Any]:
    path = _settings_path()
    if not path.exists():
        return {}
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}
    return dict(data.get("values", {}))


def _save(values: dict[str, Any]) -> None:
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump({"values": values}, f, sort_keys=False)


@router.get("", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    return SettingsResponse(values=_load())


@router.put("", response_model=SettingsResponse)
def put_settings(payload: SettingsUpdate) -> SettingsResponse:
    with _write_lock:
        try:
            _save(payload.values)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
    return SettingsResponse(values=payload.values)
