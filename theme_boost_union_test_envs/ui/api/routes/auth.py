"""Authentication endpoints: login, logout, current user, password change.

Sessions are issued as signed HTTP-only cookies (see ``..security``). A small
in-memory throttle slows down repeated failed logins per email+IP to blunt
brute-force attempts without external dependencies.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from theme_boost_union_test_envs.cross_cutting.user_store import (
    to_public_user,
    user_store,
    verify_password,
)
from ..security import (
    active_user,
    clear_session_cookie,
    create_session_token,
    current_user,
    set_session_cookie,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Minimum acceptable password length for changes/creation.
MIN_PASSWORD_LENGTH = 8

# ---- naive in-memory brute-force throttle -------------------------------
_MAX_FAILURES = 5
_LOCKOUT_SECONDS = 60
_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


def _throttle_key(email: str, request: Request) -> str:
    client = request.client.host if request.client else "unknown"
    return f"{email.lower()}|{client}"


def _is_locked(key: str) -> bool:
    now = time.time()
    with _failures_lock:
        attempts = [t for t in _failures.get(key, []) if now - t < _LOCKOUT_SECONDS]
        _failures[key] = attempts
        return len(attempts) >= _MAX_FAILURES


def _record_failure(key: str) -> None:
    with _failures_lock:
        _failures.setdefault(key, []).append(time.time())


def _clear_failures(key: str) -> None:
    with _failures_lock:
        _failures.pop(key, None)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=MIN_PASSWORD_LENGTH)


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    key = _throttle_key(payload.email, request)
    if _is_locked(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Please wait a minute and try again.",
        )

    store = user_store()
    user = store.get_by_email(payload.email)
    # Always run verify to reduce timing differences between unknown email and
    # wrong password. Uses a dummy hash when the user does not exist.
    password_hash = user.get("password_hash", "") if user else ""
    valid = verify_password(payload.password, password_hash)

    if not user or not valid or not user.get("is_active", True):
        _record_failure(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    _clear_failures(key)
    store.touch_login(user["id"])
    # Reload so the issued token + payload reflect the latest record.
    fresh = store.get_by_id(user["id"]) or user
    token = create_session_token(fresh)
    set_session_cookie(response, token)
    return to_public_user(fresh)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    clear_session_cookie(response)


@router.get("/me")
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return to_public_user(user)


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    # Note: uses current_user (not active_user) so a user who is *required* to
    # change their password can still reach this endpoint.
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    if not verify_password(payload.current_password, user.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from the current password",
        )

    store = user_store()
    updated = store.set_password(user["id"], payload.new_password, must_change=False)
    # set_password bumps session_version, invalidating the current cookie, so
    # re-issue a fresh session for a seamless experience.
    token = create_session_token(updated)
    set_session_cookie(response, token)
    return to_public_user(updated)
