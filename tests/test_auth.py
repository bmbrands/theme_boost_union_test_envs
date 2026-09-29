"""End-to-end tests for the authentication + user-management API.

Uses an isolated temporary working directory so the real ``example_pwd`` store
is never touched, and exercises the full session-cookie flow via FastAPI's
TestClient.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from theme_boost_union_test_envs.cross_cutting import user_store as user_store_mod
from theme_boost_union_test_envs.ui.api import security as security_mod
from theme_boost_union_test_envs.ui.api.routes import auth as auth_mod
from theme_boost_union_test_envs.ui.api.routes import infrastructures as infra_mod


class _FakeConfig:
    def __init__(self, working_dir: Path) -> None:
        self.working_dir = working_dir


class _FakeYamlParser:
    """Stand-in for the infrastructure yaml parser: no environments on disk."""

    def load_testbed_info(self) -> dict:
        return {}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    fake = _FakeConfig(tmp_path)
    # Point the user store, the session security, and the infrastructures route
    # at the temp dir so nothing touches the real working directory.
    monkeypatch.setattr(user_store_mod, "config", lambda: fake)
    monkeypatch.setattr(security_mod, "config", lambda: fake)
    monkeypatch.setattr(infra_mod, "config", lambda: fake)
    # Keep the protected-endpoint smoke test hermetic: no real testbed reads.
    monkeypatch.setattr(infra_mod, "yaml_parser", lambda: _FakeYamlParser())

    # Reset cached singletons + throttle so they pick up the patched config.
    monkeypatch.setattr(user_store_mod, "_store", None)
    monkeypatch.setattr(security_mod, "_serializer", None)
    monkeypatch.setattr(auth_mod, "_failures", {})

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@localhost")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "changeme123")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)

    # Import here so create_app sees the patched config + env.
    from theme_boost_union_test_envs.ui.api.server import create_app

    return TestClient(create_app())


def _login(client: TestClient, password: str = "changeme123") -> None:
    resp = client.post(
        "/api/auth/login",
        json={"email": "admin@localhost", "password": password},
    )
    assert resp.status_code == 200, resp.text


def _promote_admin(client: TestClient) -> None:
    """Log in as the seeded admin and clear the forced password change."""
    _login(client)
    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "changeme123", "new_password": "NewPass123!"},
    )
    assert resp.status_code == 200, resp.text


# ---- authentication flows ----------------------------------------------


def test_unauthenticated_requests_are_rejected(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/infrastructures").status_code == 401
    assert client.get("/api/users").status_code == 401


def test_login_failure(client: TestClient) -> None:
    resp = client.post(
        "/api/auth/login",
        json={"email": "admin@localhost", "password": "wrong"},
    )
    assert resp.status_code == 401
    # No session cookie should be set on a failed login.
    assert security_mod.COOKIE_NAME not in resp.cookies


def test_unknown_email_is_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/auth/login",
        json={"email": "nobody@nowhere.test", "password": "whatever12"},
    )
    assert resp.status_code == 401


def test_brute_force_throttle(client: TestClient) -> None:
    for _ in range(5):
        client.post(
            "/api/auth/login",
            json={"email": "admin@localhost", "password": "wrong"},
        )
    # 6th attempt within the window is throttled, even with correct password.
    resp = client.post(
        "/api/auth/login",
        json={"email": "admin@localhost", "password": "changeme123"},
    )
    assert resp.status_code == 429


def test_forced_password_change_gating(client: TestClient) -> None:
    _login(client)
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["mustChangePassword"] is True

    # Protected endpoints are blocked until the password is changed.
    assert client.get("/api/infrastructures").status_code == 403
    assert client.get("/api/users").status_code == 403

    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "changeme123", "new_password": "NewPass123!"},
    )
    assert resp.status_code == 200
    assert resp.json()["mustChangePassword"] is False

    # Now access is granted.
    assert client.get("/api/infrastructures").status_code == 200
    assert client.get("/api/users").status_code == 200
    assert client.get("/api/users/roles").status_code == 200


def test_change_password_rejects_wrong_current(client: TestClient) -> None:
    _login(client)
    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "nope-wrong", "new_password": "NewPass123!"},
    )
    assert resp.status_code == 400


def test_change_password_rejects_too_short(client: TestClient) -> None:
    _login(client)
    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "changeme123", "new_password": "short"},
    )
    assert resp.status_code == 422


def test_logout_clears_session(client: TestClient) -> None:
    _promote_admin(client)
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_password_change_invalidates_old_sessions(client: TestClient) -> None:
    # An independent client keeps the pre-change cookie; after another change
    # bumps session_version, its old cookie must be rejected.
    _promote_admin(client)
    # Snapshot the current (valid) cookie.
    old_cookies = dict(client.cookies)
    assert client.get("/api/auth/me").status_code == 200

    # Change the password again; the client's cookie is refreshed automatically.
    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "NewPass123!", "new_password": "ThirdPass123!"},
    )
    assert resp.status_code == 200

    # A fresh client carrying only the stale cookie is rejected.
    stale = TestClient(client.app)
    stale.cookies.update(old_cookies)
    assert stale.get("/api/auth/me").status_code == 401


# ---- user management ----------------------------------------------------


def test_user_management_requires_admin(client: TestClient) -> None:
    _promote_admin(client)
    # Create a plain tester.
    resp = client.post(
        "/api/users",
        json={
            "email": "tester@example.org",
            "first_name": "Tess",
            "last_name": "Ter",
            "password": "TesterPass1",
            "roles": ["tester"],
        },
    )
    assert resp.status_code == 201, resp.text

    # Sign in as the tester (clearing their forced password change).
    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"email": "tester@example.org", "password": "TesterPass1"},
    )
    assert login.status_code == 200
    client.post(
        "/api/auth/change-password",
        json={"current_password": "TesterPass1", "new_password": "TesterPass2!"},
    )

    # Tester must not reach any user-management endpoint.
    assert client.get("/api/users").status_code == 403
    assert client.get("/api/users/roles").status_code == 403


def test_create_user_validation(client: TestClient) -> None:
    _promote_admin(client)

    # Duplicate email -> 409.
    base = {
        "email": "dup@example.org",
        "first_name": "D",
        "last_name": "U",
        "password": "DupPass1234",
    }
    assert client.post("/api/users", json=base).status_code == 201
    assert client.post("/api/users", json=base).status_code == 409

    # Weak password -> 422.
    weak = {
        "email": "weak@example.org",
        "first_name": "W",
        "last_name": "K",
        "password": "short",
    }
    assert client.post("/api/users", json=weak).status_code == 422


def test_update_and_password_reset(client: TestClient) -> None:
    _promote_admin(client)
    created = client.post(
        "/api/users",
        json={
            "email": "u@example.org",
            "first_name": "U",
            "last_name": "Ser",
            "password": "InitPass123",
            "roles": ["tester"],
        },
    ).json()
    uid = created["id"]

    # Update profile.
    resp = client.patch(f"/api/users/{uid}", json={"first_name": "Updated"})
    assert resp.status_code == 200
    assert resp.json()["firstName"] == "Updated"

    # Admin password reset forces a change on next login.
    resp = client.patch(f"/api/users/{uid}", json={"password": "ResetPass123"})
    assert resp.status_code == 200

    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"email": "u@example.org", "password": "ResetPass123"},
    )
    assert login.status_code == 200
    assert login.json()["mustChangePassword"] is True


def test_update_unknown_user_is_404(client: TestClient) -> None:
    _promote_admin(client)
    assert client.patch("/api/users/does-not-exist", json={"first_name": "X"}).status_code == 404


def test_delete_user(client: TestClient) -> None:
    _promote_admin(client)
    created = client.post(
        "/api/users",
        json={
            "email": "gone@example.org",
            "first_name": "G",
            "last_name": "One",
            "password": "GonePass123",
        },
    ).json()
    uid = created["id"]
    assert client.delete(f"/api/users/{uid}").status_code == 204
    listing = client.get("/api/users").json()["users"]
    assert all(u["id"] != uid for u in listing)
    assert client.delete("/api/users/does-not-exist").status_code == 404


def test_last_admin_and_self_protection(client: TestClient) -> None:
    _promote_admin(client)
    me = client.get("/api/auth/me").json()

    # Cannot demote the last remaining admin.
    assert client.patch(f"/api/users/{me['id']}", json={"roles": ["tester"]}).status_code == 400
    # Cannot deactivate self.
    assert client.patch(f"/api/users/{me['id']}", json={"is_active": False}).status_code == 400
    # Cannot delete self.
    assert client.delete(f"/api/users/{me['id']}").status_code == 400
