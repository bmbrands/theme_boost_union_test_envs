"""Session security for the web API: signed HTTP-only cookie sessions.

Design (chosen for "secure but simple"):
- Sessions are stateless signed tokens carried in an HTTP-only cookie, so the
  token is never readable by JavaScript (mitigates XSS token theft).
- The token payload is ``{"uid": <user id>, "sv": <session_version>}`` signed
  with ``itsdangerous``. The signature + a max-age guarantee integrity and
  expiry. Embedding ``session_version`` lets a password change invalidate all
  previously issued sessions (the stored version is bumped on change).
- The signing secret comes from ``SESSION_SECRET`` (env) or a persisted random
  file ``<working_dir>/.session_secret`` so sessions survive reloads/restarts.

FastAPI dependencies exposed:
- ``current_user``      -> valid session required (401 otherwise)
- ``active_user``       -> valid session AND password not pending change (403)
- ``require_admin``     -> active user with ``system:admin`` permission (403)
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from theme_boost_union_test_envs.cross_cutting.configuration import config
from theme_boost_union_test_envs.cross_cutting.roles import role_has_permission
from theme_boost_union_test_envs.cross_cutting.user_store import user_store

COOKIE_NAME = "mp_session"
# Session lifetime in seconds (8 hours).
SESSION_MAX_AGE = 8 * 60 * 60
_SALT = "mp-session-v1"

_serializer: URLSafeTimedSerializer | None = None


def _load_secret() -> str:
    """Return the signing secret, generating + persisting one if needed."""
    env_secret = os.environ.get("SESSION_SECRET", "").strip()
    if env_secret:
        return env_secret

    secret_path = config().working_dir / ".session_secret"
    if secret_path.exists():
        return secret_path.read_text().strip()

    secret = os.urandom(32).hex()
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text(secret)
    # Restrict to owner read/write only.
    try:
        secret_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return secret


def _get_serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        _serializer = URLSafeTimedSerializer(_load_secret(), salt=_SALT)
    return _serializer


def create_session_token(user: dict[str, Any]) -> str:
    payload = {"uid": user["id"], "sv": int(user.get("session_version", 1))}
    return _get_serializer().dumps(payload)


def _decode_token(token: str) -> dict[str, Any] | None:
    try:
        return _get_serializer().loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        # Secure is enabled in production via SESSION_COOKIE_SECURE=1. On
        # localhost (http) it must stay off or the browser drops the cookie.
        secure=os.environ.get("SESSION_COOKIE_SECURE", "").lower() in ("1", "true", "yes"),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


def current_user(request: Request) -> dict[str, Any]:
    """Resolve the authenticated user from the session cookie.

    Raises 401 if there is no valid session, the user no longer exists/active,
    or the session was invalidated (session_version mismatch).
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise _unauthorized()
    payload = _decode_token(token)
    if not payload:
        raise _unauthorized()

    user = user_store().get_by_id(payload.get("uid", ""))
    if user is None or not user.get("is_active", True):
        raise _unauthorized()
    if int(user.get("session_version", 1)) != int(payload.get("sv", -1)):
        raise _unauthorized()
    return user


def active_user(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """A logged-in user who is not pending a forced password change."""
    if user.get("must_change_password", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required",
        )
    return user


def require_admin(user: dict[str, Any] = Depends(active_user)) -> dict[str, Any]:
    """An active user with the ``system:admin`` permission."""
    if not role_has_permission(user.get("roles", []), "system", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required",
        )
    return user
