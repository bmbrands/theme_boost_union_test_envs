"""End-to-end tests for the authentication + user-management API.

Uses an isolated temporary working directory so the real ``example_pwd`` store
is never touched, and exercises the full session-cookie flow via FastAPI's
TestClient.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from theme_boost_union_test_envs.cross_cutting import user_store as user_store_mod
from theme_boost_union_test_envs.ui.api import security as security_mod


class _FakeConfig:
    def __init__(self, working_dir: Path) -> None:
        self.working_dir = working_dir


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    fake = _FakeConfig(tmp_path)
    # Point both the user store and the session security at the temp dir.
    monkeypatch.setattr(user_store_mod, "config", lambda: fake)
    monkeypatch.setattr(security_mod, "config", lambda: fake)
    # Reset cached singletons so they pick up the patched config.
    monkeypatch.setattr(user_store_mod, "_store", None)
    monkeypatch.setattr(security_mod, "_serializer", None)

    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@localhost")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "changeme123")

    # Import here so create_app sees the patched config + env.
    from theme_boost_union_test_envs.ui.api.server import create_app

    return TestClient(create_app())


def _login(client: TestClient, password: str = "changeme123") -> None:
    resp = client.post(
        "/api/auth/login",
        json={"email": "admin@localhost", "password": password},
    )
    assert resp.status_code == 200, resp.text


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


def test_user_crud_and_last_admin_protection(client: TestClient) -> None:
    _login(client)
    client.post(
        "/api/auth/change-password",
        json={"current_password": "changeme123", "new_password": "NewPass123!"},
    )

    # Create a tester.
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
    assert resp.json()["email"] == "tester@example.org"

    # Cannot demote the last remaining admin.
    me = client.get("/api/auth/me").json()
    resp = client.patch(f"/api/users/{me['id']}", json={"roles": ["tester"]})
    assert resp.status_code == 400

    # Cannot delete yourself.
    resp = client.delete(f"/api/users/{me['id']}")
    assert resp.status_code == 400


def test_logout_clears_session(client: TestClient) -> None:
    _login(client)
    client.post(
        "/api/auth/change-password",
        json={"current_password": "changeme123", "new_password": "NewPass123!"},
    )
    assert client.get("/api/auth/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401
