"""Persistent audit log backed by ``<working_dir>/audit.yaml``.

The frontend records user activity (environment create/delete, container
start/stop, login, password copy, …) by POSTing entries here. Entries are
append-only; the endpoint trims the file to the most recent N records so the
YAML does not grow unbounded.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from theme_boost_union_test_envs.cross_cutting import config

router = APIRouter(prefix="/api/audit", tags=["audit"])


# Keep at most this many records on disk. Older ones get dropped.
MAX_ENTRIES = 2000

_write_lock = threading.Lock()


class AuditEntry(BaseModel):
    id: str
    timestamp: str
    user_id: str
    user_name: str
    user_email: str
    action: str
    resource: str
    resource_id: str | None = None
    resource_name: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    ip_address: str | None = None
    user_agent: str | None = None
    severity: Literal["low", "medium", "high", "critical"] = "medium"


class CreateAuditEntry(BaseModel):
    user_id: str
    user_name: str
    user_email: str
    action: str
    resource: str
    resource_id: str | None = None
    resource_name: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    ip_address: str | None = None
    user_agent: str | None = None
    severity: Literal["low", "medium", "high", "critical"] = "medium"


class AuditListResponse(BaseModel):
    entries: list[AuditEntry]


def _audit_path() -> Path:
    return config().working_dir / "audit.yaml"


def _load() -> list[dict]:
    path = _audit_path()
    if not path.exists():
        return []
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}
    return list(data.get("entries", []))


def _save(entries: list[dict]) -> None:
    path = _audit_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Trim to the most recent MAX_ENTRIES to keep the file bounded.
    trimmed = entries[-MAX_ENTRIES:]
    with open(path, "w") as f:
        yaml.safe_dump({"entries": trimmed}, f, sort_keys=False)


@router.get("", response_model=AuditListResponse)
def list_entries(
    limit: int = Query(500, ge=1, le=MAX_ENTRIES),
) -> AuditListResponse:
    """Return the most recent ``limit`` audit entries, newest first."""
    entries = _load()
    # Newest first.
    entries_sorted = sorted(entries, key=lambda e: e.get("timestamp", ""), reverse=True)
    return AuditListResponse(
        entries=[AuditEntry(**e) for e in entries_sorted[:limit]]
    )


@router.post("", response_model=AuditEntry, status_code=201)
def create_entry(payload: CreateAuditEntry) -> AuditEntry:
    entry = AuditEntry(
        id=f"audit-{uuid.uuid4().hex[:12]}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        **payload.model_dump(),
    )
    with _write_lock:
        entries = _load()
        entries.append(entry.model_dump())
        _save(entries)
    return entry


@router.delete("", status_code=204)
def clear_entries() -> None:
    """Wipe the audit log. Use with care."""
    with _write_lock:
        try:
            _save([])
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(e)) from e
