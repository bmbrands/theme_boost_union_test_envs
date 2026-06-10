"""Expose the in-memory server log buffer to the frontend.

Lets the UI display the same output a developer would see in the terminal
running uvicorn (application logs plus uvicorn's own logging).
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from theme_boost_union_test_envs.cross_cutting.log_buffer import (
    clear_logs,
    get_logs,
)

router = APIRouter(prefix="/api/logs", tags=["logs"])


class LogLine(BaseModel):
    id: int
    timestamp: str
    level: str
    message: str
    source: str


class LogResponse(BaseModel):
    lines: list[LogLine]


@router.get("", response_model=LogResponse)
def list_logs(
    limit: int = Query(1000, ge=1, le=2000),
    after_id: int | None = Query(None, ge=0),
) -> LogResponse:
    """Return buffered server log lines, oldest first.

    Pass ``after_id`` (the highest id seen so far) to fetch only new lines.
    """
    return LogResponse(
        lines=[LogLine(**line) for line in get_logs(limit=limit, after_id=after_id)]
    )


@router.delete("", status_code=204)
def clear() -> None:
    """Wipe the in-memory log buffer."""
    clear_logs()
