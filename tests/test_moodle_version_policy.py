"""Tests for the administrator-set minimum Moodle version."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from theme_boost_union_test_envs.cross_cutting import settings_store as store_mod
from theme_boost_union_test_envs.domain import moodle_version_policy as policy
from theme_boost_union_test_envs.ui.api.routes import moodle as moodle_mod

from .test_admin_settings import _login_tester, _settings
from .test_auth import _FakeConfig, _promote_admin
from .test_auth import client as auth_client  # noqa: F401 - pytest fixture

VERSIONS = ["5.3.0", "5.1.2", "4.5.7", "4.4.1", "4.1.20"]


@pytest.fixture()
def client(
    auth_client: TestClient,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    monkeypatch.setattr(store_mod, "config", lambda: _FakeConfig(tmp_path))
    fake = []
    for v in VERSIONS:
        major, minor, patch = (int(x) for x in v.split("."))
        fake.append(moodle_mod.MoodleVersion(version=v, tag=f"v{v}", major=major, minor=minor, patch=patch))
    monkeypatch.setattr(moodle_mod, "_fetch_moodle_versions", lambda: fake)
    monkeypatch.setattr(moodle_mod, "_CACHE", {})
    return auth_client


@pytest.mark.parametrize(
    "version,minimum,allowed",
    [("4.5.0", "4.5", True), ("4.5.7", "4.5", True), ("4.4.1", "4.5", False),
     ("5.0.0", "4.5.7", True), ("4.5.6", "4.5.7", False), ("3.11.0", "", True)],
)
def test_is_allowed(version: str, minimum: str, allowed: bool) -> None:
    assert policy.is_allowed(version, minimum) is allowed


def test_versions_unfiltered_without_minimum(client: TestClient) -> None:
    _promote_admin(client)
    body = client.get("/api/moodle/versions").json()
    assert [v["version"] for v in body["versions"]] == VERSIONS
    assert body["minimum_version"] == ""


def test_admin_sets_minimum_and_list_is_filtered(client: TestClient, tmp_path: Path) -> None:
    _promote_admin(client)
    resp = client.put("/api/moodle/policy", json={"minimum_version": "4.5"})
    assert resp.status_code == 200, resp.text
    assert _settings(tmp_path)["moodle_versions"] == {"minimum_version": "4.5"}

    body = client.get("/api/moodle/versions").json()
    assert [v["version"] for v in body["versions"]] == ["5.3.0", "5.1.2", "4.5.7"]
    assert body["minimum_version"] == "4.5"
    assert client.get("/api/moodle/policy").json() == {"minimum_version": "4.5"}

    # Clearing the minimum shows everything again.
    client.put("/api/moodle/policy", json={"minimum_version": ""})
    assert len(client.get("/api/moodle/versions").json()["versions"]) == len(VERSIONS)


@pytest.mark.parametrize("bad", ["4", "4.x", "latest", "4.5;id", "v4.5"])
def test_invalid_minimum_is_rejected(client: TestClient, bad: str) -> None:
    _promote_admin(client)
    assert client.put("/api/moodle/policy", json={"minimum_version": bad}).status_code == 422


def test_tester_can_read_but_not_change_minimum(client: TestClient) -> None:
    _promote_admin(client)
    client.put("/api/moodle/policy", json={"minimum_version": "4.5"})
    _login_tester(client)
    assert client.get("/api/moodle/policy").json() == {"minimum_version": "4.5"}
    assert client.put("/api/moodle/policy", json={"minimum_version": ""}).status_code == 403


def test_creating_environment_below_minimum_is_rejected(client: TestClient) -> None:
    _promote_admin(client)
    client.put("/api/moodle/policy", json={"minimum_version": "4.5"})
    resp = client.post(
        "/api/infrastructures",
        json={
            "name": "too-old",
            "plugin": "boost_union",
            "git_ref_type": "branch",
            "git_ref": "main",
            "moodle_versions": ["5.1.2", "4.4.1"],
        },
    )
    assert resp.status_code == 400
    assert "4.4.1" in resp.json()["detail"] and "4.5" in resp.json()["detail"]


def test_generic_settings_put_keeps_minimum(client: TestClient, tmp_path: Path) -> None:
    _promote_admin(client)
    client.put("/api/moodle/policy", json={"minimum_version": "4.5"})
    client.put("/api/settings", json={"values": {"moodle_versions": {"minimum_version": ""}}})
    assert _settings(tmp_path)["moodle_versions"] == {"minimum_version": "4.5"}
