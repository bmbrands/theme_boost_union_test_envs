"""API tests for the admin-editable settings sections (lifecycle, settings).

Reuses the hermetic auth client from ``test_auth`` and additionally points the
settings store at the temporary working directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from theme_boost_union_test_envs.cross_cutting import settings_store as store_mod

from .test_auth import _FakeConfig, _promote_admin
from .test_auth import client as auth_client  # noqa: F401 - pytest fixture


@pytest.fixture()
def client(
    auth_client: TestClient,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    monkeypatch.setattr(store_mod, "config", lambda: _FakeConfig(tmp_path))
    return auth_client


def _settings(tmp_path: Path) -> dict:
    return yaml.safe_load((tmp_path / "settings.yaml").read_text())["values"]


VALID_POLICY = {
    "auto_stop_enabled": True,
    "max_runtime_minutes": 90,
    "daily_stop_time": "18:30",
    "auto_cleanup_enabled": True,
    "stopped_retention_days": 3,
    "cleanup_empty_infrastructures": False,
}


def _login_tester(client: TestClient) -> None:
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
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"email": "tester@example.org", "password": "TesterPass1"},
    )
    client.post(
        "/api/auth/change-password",
        json={"current_password": "TesterPass1", "new_password": "TesterPass2!"},
    )


def test_lifecycle_defaults_when_unconfigured(client: TestClient) -> None:
    _promote_admin(client)
    body = client.get("/api/lifecycle").json()
    assert body["auto_stop_enabled"] is False
    assert body["auto_cleanup_enabled"] is False


def test_admin_updates_lifecycle_policy(client: TestClient, tmp_path: Path) -> None:
    _promote_admin(client)
    resp = client.put("/api/lifecycle", json=VALID_POLICY)
    assert resp.status_code == 200, resp.text
    assert resp.json() == VALID_POLICY
    assert client.get("/api/lifecycle").json() == VALID_POLICY
    assert _settings(tmp_path)["lifecycle"] == VALID_POLICY


@pytest.mark.parametrize(
    "field,value",
    [
        ("daily_stop_time", "25:00"),
        ("daily_stop_time", "7:00"),
        ("max_runtime_minutes", 0),
        ("stopped_retention_days", 0),
    ],
)
def test_lifecycle_validation(client: TestClient, field: str, value: object) -> None:
    _promote_admin(client)
    resp = client.put("/api/lifecycle", json={**VALID_POLICY, field: value})
    assert resp.status_code == 422


def test_empty_daily_stop_time_is_allowed(client: TestClient) -> None:
    _promote_admin(client)
    resp = client.put("/api/lifecycle", json={**VALID_POLICY, "daily_stop_time": ""})
    assert resp.status_code == 200, resp.text


def test_tester_can_read_but_not_change_lifecycle(client: TestClient) -> None:
    _promote_admin(client)
    _login_tester(client)
    assert client.get("/api/lifecycle").status_code == 200
    assert client.put("/api/lifecycle", json=VALID_POLICY).status_code == 403
    assert client.put("/api/settings", json={"values": {}}).status_code == 403


def test_generic_settings_put_preserves_owned_sections(
    client: TestClient, tmp_path: Path
) -> None:
    _promote_admin(client)
    client.put("/api/lifecycle", json=VALID_POLICY)
    resp = client.put(
        "/api/settings",
        json={"values": {"log_retention_days": 30, "lifecycle": {"auto_stop_enabled": False}}},
    )
    assert resp.status_code == 200, resp.text
    assert "lifecycle" not in resp.json()["values"]
    stored = _settings(tmp_path)
    assert stored["log_retention_days"] == 30
    assert stored["lifecycle"] == VALID_POLICY
