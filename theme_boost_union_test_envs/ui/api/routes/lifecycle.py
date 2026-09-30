"""Expose the effective instance-lifecycle policy (read-only).

The frontend uses this to explain the auto-stop / auto-delete times shown per
instance. The policy itself is edited in ``settings.yaml`` (``lifecycle`` block).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from theme_boost_union_test_envs.domain import lifecycle

router = APIRouter(prefix="/api/lifecycle", tags=["lifecycle"])


@router.get("")
def get_lifecycle_policy() -> dict[str, Any]:
    return lifecycle.policy_summary(lifecycle.load_policy())
