"""Read and edit the instance-lifecycle policy.

Every logged-in user can read the effective policy (the frontend uses it to
explain the auto-stop / auto-delete times per instance); only administrators
with the Admin Settings permission can change it. The policy is stored as the
``lifecycle`` section of ``settings.yaml`` and read by the reaper on each run.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from theme_boost_union_test_envs.cross_cutting.logger import log
from theme_boost_union_test_envs.domain import lifecycle

from ..security import require_settings_admin

router = APIRouter(prefix="/api/lifecycle", tags=["lifecycle"])


class LifecyclePolicyUpdate(BaseModel):
    auto_stop_enabled: bool
    max_runtime_minutes: int = Field(ge=1, le=60 * 24 * 365)
    # "HH:MM" in UTC, or empty to disable the daily stop.
    daily_stop_time: str = Field(default="", pattern=r"^$|^([01]\d|2[0-3]):[0-5]\d$")
    auto_cleanup_enabled: bool
    stopped_retention_days: int = Field(ge=1, le=3650)
    cleanup_empty_infrastructures: bool


@router.get("")
def get_lifecycle_policy() -> dict[str, Any]:
    return lifecycle.policy_summary(lifecycle.load_policy())


@router.put("")
def put_lifecycle_policy(
    payload: LifecyclePolicyUpdate,
    user: dict[str, Any] = Depends(require_settings_admin),
) -> dict[str, Any]:
    policy = lifecycle.LifecyclePolicy(**payload.model_dump())
    lifecycle.save_policy(policy)
    log().info("lifecycle policy updated by {}: {}", user.get("email", "?"), payload.model_dump())
    return lifecycle.policy_summary(policy)
