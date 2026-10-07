"""Security tests: input validation and API permissions.

Names, versions and git references reach file paths, sourced ``.env`` files
and shell command lines, so they must be rejected before use. Audit/log and
plugin-catalog endpoints must be enforced by the API, not only hidden in the UI.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from theme_boost_union_test_envs.core import BoostUnionTestEnvCore
from theme_boost_union_test_envs.cross_cutting import settings_store as store_mod
from theme_boost_union_test_envs.domain.validation import (
    InvalidInputError,
    validate_git_ref,
    validate_infrastructure_name,
    validate_moodle_version,
)
from theme_boost_union_test_envs.exceptions import InfrastructureDoesNotExistYetError
from theme_boost_union_test_envs.ui.api.routes import audit as audit_mod

from .test_admin_settings import _login_tester
from .test_auth import _FakeConfig, _promote_admin
from .test_auth import client as auth_client  # noqa: F401 - pytest fixture

# ---- validation ---------------------------------------------------------


@pytest.mark.parametrize("name", ["boost-union-2", "test_tuesday", "BU-aktuell-yw", "4.5-r2", "a"])
def test_valid_names(name: str) -> None:
    assert validate_infrastructure_name(name) == name


@pytest.mark.parametrize(
    "name",
    ["", "..", "a..b", "../etc", "a/b", "-rf", ".hidden", "x$(id)", "x`id`", 'a"b', "a b", "a;b", "a" * 64],
)
def test_invalid_names(name: str) -> None:
    with pytest.raises(InvalidInputError):
        validate_infrastructure_name(name)


@pytest.mark.parametrize("version", ["4.5", "5.0.2", "5.1.10"])
def test_valid_versions(version: str) -> None:
    assert validate_moodle_version(version) == version


@pytest.mark.parametrize("version", ["", "5", "5.x", "5.0.2;id", "../5.0", "v5.0.2", "5.0.2 "])
def test_invalid_versions(version: str) -> None:
    with pytest.raises(InvalidInputError):
        validate_moodle_version(version)


@pytest.mark.parametrize(
    "kind,ref",
    [("branch", "MOODLE_501_STABLE"), ("branch", "feature/x-1"), ("tag", "v4.5-r29"),
     ("commit", "a1b2c3d"), ("pr", "42"), ("pr", 7)],
)
def test_valid_refs(kind: str, ref: object) -> None:
    validate_git_ref(kind, ref)


@pytest.mark.parametrize(
    "kind,ref",
    [("branch", "--upload-pack=touch /tmp/x"), ("branch", "a..b"), ("branch", "a b"),
     ("tag", "v1;id"), ("commit", "xyz"), ("commit", "a1b2"), ("pr", "0"), ("pr", "1;2"),
     ("other", "main")],
)
def test_invalid_refs(kind: str, ref: object) -> None:
    with pytest.raises(InvalidInputError):
        validate_git_ref(kind, ref)


# ---- core only acts on recorded environments ------------------------------


class _Parser:
    def load_testbed_info(self) -> dict:
        return {"known": {"moodles": {"5.0.2": {"status": "STOPPED"}}}}


def test_core_rejects_unknown_environment_and_version() -> None:
    core = BoostUnionTestEnvCore(yaml_parser=_Parser(), template_engine=None)
    core._require_known("known", "5.0.2")
    with pytest.raises(InfrastructureDoesNotExistYetError):
        core._require_known("..")
    with pytest.raises(InfrastructureDoesNotExistYetError):
        core._require_known("known", "../../x")


# ---- API ------------------------------------------------------------------


@pytest.fixture()
def client(
    auth_client: TestClient,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    fake = _FakeConfig(tmp_path)
    monkeypatch.setattr(store_mod, "config", lambda: fake)
    monkeypatch.setattr(audit_mod, "config", lambda: fake)
    return auth_client


def _create(client: TestClient, **overrides) -> int:
    payload = {
        "name": "ok-name",
        "plugin": "boost_union",
        "git_ref_type": "branch",
        "git_ref": "main",
        "moodle_versions": ["5.0.2"],
        **overrides,
    }
    return client.post("/api/infrastructures", json=payload).status_code


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": "x$(touch /tmp/pwned)"},
        {"name": ".."},
        {"moodle_versions": ["5.0.2\"; id; \""]},
        {"git_ref": "--upload-pack=touch /tmp/pwned"},
        {"git_ref_type": "pr", "git_ref": "PR#abc"},
    ],
)
def test_create_rejects_unsafe_input(client: TestClient, overrides: dict) -> None:
    _promote_admin(client)
    assert _create(client, **overrides) == 400


def test_tester_cannot_read_or_wipe_audit_and_logs(client: TestClient) -> None:
    _promote_admin(client)
    _login_tester(client)
    assert client.get("/api/audit").status_code == 403
    assert client.delete("/api/audit").status_code == 403
    assert client.get("/api/logs").status_code == 403
    assert client.delete("/api/logs").status_code == 403


def test_tester_cannot_change_plugin_catalog(client: TestClient) -> None:
    _promote_admin(client)
    _login_tester(client)
    plugin = {
        "name": "evil",
        "displayName": "Evil",
        "repositoryUrl": "https://github.com/evil/evil",
        "installationPath": "local/evil",
        "type": "other",
        "isActive": True,
    }
    assert client.post("/api/plugins", json=plugin).status_code == 403
    assert client.patch("/api/plugins/any", json={"isActive": False}).status_code == 403
    assert client.delete("/api/plugins/any").status_code == 403


def test_audit_entry_is_attributed_to_the_session_user(client: TestClient) -> None:
    _promote_admin(client)
    _login_tester(client)
    resp = client.post(
        "/api/audit",
        json={
            "user_id": "user-admin",
            "user_name": "Somebody Else",
            "user_email": "boss@example.org",
            "action": "delete",
            "resource": "environment",
        },
    )
    assert resp.status_code == 201, resp.text
    entry = resp.json()
    assert entry["user_email"] == "tester@example.org"
    assert entry["user_name"] == "Tess Ter"
    assert entry["user_id"] != "user-admin"
