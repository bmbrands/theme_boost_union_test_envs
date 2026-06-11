"""Persistent user store backed by ``<working_dir>/users.yaml``.

Stores user accounts and bcrypt password hashes for the web UI's
authentication. The file is written atomically under a process lock; password
hashes are never returned to the API layer in user dicts (see ``public_dict``).

Security notes:
- Passwords are hashed with bcrypt (per-hash random salt). Plaintext is never
  stored or logged.
- ``session_version`` is embedded in issued session cookies; bumping it (e.g.
  on password change) invalidates all previously issued sessions for the user.
"""

from __future__ import annotations

import os
import secrets
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import bcrypt
import yaml

from .configuration import config
from .roles import DEFAULT_ROLE_ID, expand_roles, valid_role_ids

_lock = threading.RLock()

# Default single-tenant organisation surfaced to the frontend (which models
# users -> account). We keep one implicit org rather than full multi-tenancy.
DEFAULT_ACCOUNT = {
    "id": "account-default",
    "name": "Boost Union",
    "domain": "localhost",
    "createdAt": "2024-01-01",
    "isActive": True,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(plaintext: str) -> str:
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plaintext: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            plaintext.encode("utf-8"), password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


class UserStore:
    """Thread-safe CRUD over ``users.yaml``."""

    def _path(self) -> Path:
        return config().working_dir / "users.yaml"

    def _load(self) -> list[dict[str, Any]]:
        path = self._path()
        if not path.exists():
            return []
        with open(path, "r") as f:
            data = yaml.safe_load(f) or {}
        return list(data.get("users", []))

    def _save(self, users: list[dict[str, Any]]) -> None:
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".yaml.tmp")
        with open(tmp, "w") as f:
            yaml.safe_dump({"users": users}, f, sort_keys=False)
        os.replace(tmp, path)

    # ---- queries -------------------------------------------------------

    def list_users(self) -> list[dict[str, Any]]:
        with _lock:
            return self._load()

    def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        with _lock:
            for user in self._load():
                if user.get("id") == user_id:
                    return user
        return None

    def get_by_email(self, email: str) -> dict[str, Any] | None:
        normalized = email.strip().lower()
        with _lock:
            for user in self._load():
                if user.get("email", "").lower() == normalized:
                    return user
        return None

    def count(self) -> int:
        with _lock:
            return len(self._load())

    def count_active_admins(self, exclude_id: str | None = None) -> int:
        with _lock:
            return sum(
                1
                for u in self._load()
                if u.get("is_active", True)
                and "admin" in u.get("roles", [])
                and u.get("id") != exclude_id
            )

    # ---- mutations -----------------------------------------------------

    def create_user(
        self,
        *,
        email: str,
        first_name: str,
        last_name: str,
        password: str,
        roles: list[str] | None = None,
        is_active: bool = True,
        must_change_password: bool = False,
        avatar: str | None = None,
    ) -> dict[str, Any]:
        roles = self._sanitize_roles(roles)
        with _lock:
            users = self._load()
            if any(u.get("email", "").lower() == email.strip().lower() for u in users):
                raise ValueError(f"A user with email '{email}' already exists")
            user = {
                "id": f"user-{uuid.uuid4().hex[:12]}",
                "email": email.strip(),
                "first_name": first_name.strip(),
                "last_name": last_name.strip(),
                "password_hash": hash_password(password),
                "roles": roles,
                "is_active": is_active,
                "must_change_password": must_change_password,
                "session_version": 1,
                "avatar": avatar,
                "created_at": _now(),
                "last_login_at": None,
            }
            users.append(user)
            self._save(users)
            return user

    def update_user(self, user_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {
            "email",
            "first_name",
            "last_name",
            "roles",
            "is_active",
            "avatar",
        }
        with _lock:
            users = self._load()
            target = next((u for u in users if u.get("id") == user_id), None)
            if target is None:
                raise KeyError(user_id)
            if "roles" in changes and changes["roles"] is not None:
                changes["roles"] = self._sanitize_roles(changes["roles"])
            if "email" in changes and changes["email"]:
                new_email = changes["email"].strip()
                if any(
                    u.get("id") != user_id
                    and u.get("email", "").lower() == new_email.lower()
                    for u in users
                ):
                    raise ValueError(f"A user with email '{new_email}' already exists")
                changes["email"] = new_email
            for key, value in changes.items():
                if key in allowed and value is not None:
                    target[key] = value
            self._save(users)
            return target

    def set_password(
        self, user_id: str, new_password: str, *, must_change: bool = False
    ) -> dict[str, Any]:
        with _lock:
            users = self._load()
            target = next((u for u in users if u.get("id") == user_id), None)
            if target is None:
                raise KeyError(user_id)
            target["password_hash"] = hash_password(new_password)
            target["must_change_password"] = must_change
            # Invalidate existing sessions issued before the password change.
            target["session_version"] = int(target.get("session_version", 1)) + 1
            self._save(users)
            return target

    def touch_login(self, user_id: str) -> None:
        with _lock:
            users = self._load()
            target = next((u for u in users if u.get("id") == user_id), None)
            if target is None:
                return
            target["last_login_at"] = _now()
            self._save(users)

    def delete_user(self, user_id: str) -> None:
        with _lock:
            users = self._load()
            remaining = [u for u in users if u.get("id") != user_id]
            if len(remaining) == len(users):
                raise KeyError(user_id)
            self._save(remaining)

    # ---- bootstrap -----------------------------------------------------

    def ensure_seed_admin(self) -> None:
        """Create the first admin account if the store is empty.

        Reads ``BOOTSTRAP_ADMIN_EMAIL`` / ``BOOTSTRAP_ADMIN_PASSWORD`` from the
        environment. If no password is provided a random one is generated and
        logged once; in both cases the admin must change the password on first
        login.
        """
        from .logger import log

        with _lock:
            if self._load():
                return

        email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "admin@localhost").strip()
        password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "").strip()
        generated = False
        if not password:
            password = secrets.token_urlsafe(12)
            generated = True

        self.create_user(
            email=email,
            first_name="Admin",
            last_name="User",
            password=password,
            roles=["admin"],
            is_active=True,
            must_change_password=True,
        )

        if generated:
            log().warning(
                "Seeded initial admin '{}' with a generated password: {}  "
                "(you must change it on first login)",
                email,
                password,
            )
        else:
            log().info(
                "Seeded initial admin '{}' from BOOTSTRAP_ADMIN_PASSWORD "
                "(must be changed on first login)",
                email,
            )

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def _sanitize_roles(roles: list[str] | None) -> list[str]:
        if not roles:
            return [DEFAULT_ROLE_ID]
        valid = valid_role_ids()
        cleaned = [r for r in roles if r in valid]
        return cleaned or [DEFAULT_ROLE_ID]


_store: UserStore | None = None


def user_store() -> UserStore:
    global _store
    if _store is None:
        _store = UserStore()
    return _store


def to_public_user(user: dict[str, Any]) -> dict[str, Any]:
    """Convert a stored user record into the API/frontend representation.

    Never includes the password hash. Expands role ids into full role objects
    and attaches the default organisation so the frontend ``User`` shape is
    satisfied.
    """
    return {
        "id": user.get("id", ""),
        "email": user.get("email", ""),
        "firstName": user.get("first_name", ""),
        "lastName": user.get("last_name", ""),
        "avatar": user.get("avatar"),
        "accountId": DEFAULT_ACCOUNT["id"],
        "account": DEFAULT_ACCOUNT,
        "roles": expand_roles(user.get("roles", [])),
        "isActive": user.get("is_active", True),
        "mustChangePassword": user.get("must_change_password", False),
        "createdAt": user.get("created_at") or _now(),
        "lastLoginAt": user.get("last_login_at") or user.get("created_at") or _now(),
    }
