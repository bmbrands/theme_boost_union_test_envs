"""Persist admin settings to ``<working_dir>/settings.yaml``.

Generic key/value overrides. Sections that have their own dedicated routes
(``lifecycle``, ``email``) are preserved on write so this endpoint can never
wipe them; edit those through ``/api/lifecycle`` and ``/api/email``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from theme_boost_union_test_envs.cross_cutting import settings_store

from ..security import require_settings_admin

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Sections owned by dedicated routes; never read or written here.
_OWNED_SECTIONS = ("lifecycle", "email")


class SettingsResponse(BaseModel):
    values: dict[str, Any]


class SettingsUpdate(BaseModel):
    values: dict[str, Any]


def _public(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if k not in _OWNED_SECTIONS}


@router.get("", response_model=SettingsResponse)
def get_settings() -> SettingsResponse:
    return SettingsResponse(values=_public(settings_store.load_values()))


@router.put("", response_model=SettingsResponse)
def put_settings(
    payload: SettingsUpdate,
    _: dict[str, Any] = Depends(require_settings_admin),
) -> SettingsResponse:
    with settings_store._lock:
        current = settings_store.load_values()
        values = _public(payload.values)
        for key in _OWNED_SECTIONS:
            if key in current:
                values[key] = current[key]
        try:
            settings_store.save_values(values)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
    return SettingsResponse(values=_public(values))
