"""Canonical role + permission definitions for the web UI's authorization.

Kept deliberately small and in sync with the frontend's ``types/user.ts``.
Roles are referenced by id when stored on a user; the API expands them into
full objects (id, name, description, permissions) in its responses so the
frontend's permission checks work without a second source of truth.
"""

from __future__ import annotations

from typing import Any

# Permission tuples: (id, name, resource, action)
_PERMISSIONS = {
    "env-read": ("env-read", "View Environments", "environments", "read"),
    "env-write": ("env-write", "Create/Edit Environments", "environments", "write"),
    "env-delete": ("env-delete", "Delete Environments", "environments", "delete"),
    "metrics-read": ("metrics-read", "View Host Metrics", "metrics", "read"),
    "admin-settings": ("admin-settings", "Admin Settings", "system", "admin"),
    "user-management": ("user-management", "User Management", "users", "admin"),
    "audit-log": ("audit-log", "View Audit Log", "audit", "read"),
}

# Role id -> (name, description, [permission ids])
_ROLES: dict[str, tuple[str, str, list[str]]] = {
    "tester": (
        "Tester",
        "Can create and manage test environments",
        ["env-read", "env-write", "env-delete"],
    ),
    "admin": (
        "Administrator",
        "Full system access including user and system management",
        [
            "env-read",
            "env-write",
            "env-delete",
            "metrics-read",
            "admin-settings",
            "user-management",
            "audit-log",
        ],
    ),
}

# The role assigned to a brand-new user when none is specified.
DEFAULT_ROLE_ID = "tester"


def valid_role_ids() -> set[str]:
    return set(_ROLES.keys())


def _permission_dict(permission_id: str) -> dict[str, str]:
    pid, name, resource, action = _PERMISSIONS[permission_id]
    return {"id": pid, "name": name, "resource": resource, "action": action}


def expand_role(role_id: str) -> dict[str, Any] | None:
    """Return the full role object for a role id, or None if unknown."""
    role = _ROLES.get(role_id)
    if role is None:
        return None
    name, description, permission_ids = role
    return {
        "id": role_id,
        "name": name,
        "description": description,
        "permissions": [_permission_dict(pid) for pid in permission_ids],
    }


def expand_roles(role_ids: list[str]) -> list[dict[str, Any]]:
    """Expand a list of role ids into full role objects, dropping unknown ids."""
    expanded = []
    for role_id in role_ids:
        role = expand_role(role_id)
        if role is not None:
            expanded.append(role)
    return expanded


def all_roles() -> list[dict[str, Any]]:
    return [expand_role(role_id) for role_id in _ROLES]  # type: ignore[misc]


def role_has_permission(role_ids: list[str], resource: str, action: str) -> bool:
    """True if any of the given roles grants ``resource:action``."""
    for role_id in role_ids:
        role = _ROLES.get(role_id)
        if role is None:
            continue
        for pid in role[2]:
            _, _, perm_resource, perm_action = _PERMISSIONS[pid]
            if perm_resource == resource and perm_action == action:
                return True
    return False
