"""User management endpoints (admin only).

Provides CRUD over the user store plus the list of assignable roles. Guards
against foot-guns: you cannot delete/deactivate yourself or remove the last
remaining active administrator.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from theme_boost_union_test_envs.cross_cutting.roles import all_roles
from theme_boost_union_test_envs.cross_cutting.user_store import (
    to_public_user,
    user_store,
)
from ..security import require_admin
from .auth import MIN_PASSWORD_LENGTH

router = APIRouter(prefix="/api/users", tags=["users"])


class CreateUserRequest(BaseModel):
    email: str = Field(..., min_length=3)
    first_name: str = Field(..., min_length=1)
    last_name: str = Field(..., min_length=1)
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH)
    roles: list[str] = Field(default_factory=list)
    is_active: bool = True
    must_change_password: bool = True


class UpdateUserRequest(BaseModel):
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    roles: list[str] | None = None
    is_active: bool | None = None
    # Optional admin password reset; forces a change on next login.
    password: str | None = Field(default=None, min_length=MIN_PASSWORD_LENGTH)


@router.get("")
def list_users(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    return {"users": [to_public_user(u) for u in user_store().list_users()]}


@router.get("/roles")
def list_roles(_: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    return {"roles": all_roles()}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: CreateUserRequest, _: dict[str, Any] = Depends(require_admin)
) -> dict[str, Any]:
    try:
        user = user_store().create_user(
            email=payload.email,
            first_name=payload.first_name,
            last_name=payload.last_name,
            password=payload.password,
            roles=payload.roles,
            is_active=payload.is_active,
            must_change_password=payload.must_change_password,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    return to_public_user(user)


@router.patch("/{user_id}")
def update_user(
    user_id: str,
    payload: UpdateUserRequest,
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    store = user_store()
    target = store.get_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Prevent locking out the last admin or self-demotion/deactivation that
    # would remove the final administrator.
    removing_admin = (
        ("admin" in target.get("roles", []) and payload.roles is not None
         and "admin" not in payload.roles)
        or (payload.is_active is False)
    )
    if removing_admin and store.count_active_admins(exclude_id=user_id) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove the last active administrator",
        )
    if payload.is_active is False and user_id == admin["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account",
        )

    changes = payload.model_dump(exclude_none=True)
    password = changes.pop("password", None)
    try:
        if changes:
            store.update_user(user_id, **changes)
        if password:
            store.set_password(user_id, password, must_change=True)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e

    return to_public_user(store.get_by_id(user_id) or target)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: str, admin: dict[str, Any] = Depends(require_admin)
) -> None:
    store = user_store()
    target = store.get_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user_id == admin["id"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own account",
        )
    if "admin" in target.get("roles", []) and store.count_active_admins(exclude_id=user_id) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the last active administrator",
        )
    store.delete_user(user_id)
