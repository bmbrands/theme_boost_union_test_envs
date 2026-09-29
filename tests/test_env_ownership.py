"""Tests for environment ownership stored inside ``infrastructure.yaml``.

The creator is recorded on the infrastructure record itself (same level as
``created_at`` / ``git_ref``); the contained moodles are implicitly owned by
that user. These tests exercise the parser write path in isolation (temp
working dir) plus the API helper that turns a stored owner into a response
model.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest
import yaml

from theme_boost_union_test_envs.cross_cutting import infrastructure_parser as parser_mod
from theme_boost_union_test_envs.entities import GitReference, GitReferenceType
from theme_boost_union_test_envs.ui.api.routes.infrastructures import _owner_model


@pytest.fixture()
def parser(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> parser_mod.InfrastructureYAMLParser:
    infra_yaml = tmp_path / "infrastructure.yaml"
    infra_yaml.write_text("")  # load_testbed_info opens the file for reading
    fake = types.SimpleNamespace(infra_yaml=infra_yaml)
    monkeypatch.setattr(parser_mod, "config", lambda: fake)
    return parser_mod.InfrastructureYAMLParser()


def _read(parser: parser_mod.InfrastructureYAMLParser) -> dict:
    with open(parser.yaml, "r") as f:
        return yaml.safe_load(f) or {}


def test_new_infrastructure_persists_created_by(parser) -> None:
    owner = {"id": "user-1", "name": "Tess Ter", "email": "tester@example.org"}
    parser.new_infrastructure(
        "demo-infra",
        "boost_union",
        GitReference("main", GitReferenceType.BRANCH),
        owner,
    )

    entry = _read(parser)["demo-infra"]
    # created_by sits at the same level as the other infra metadata.
    assert entry["created_by"] == owner
    for key in ("created_at", "git_ref", "plugin", "moodles"):
        assert key in entry


def test_new_infrastructure_omits_created_by_when_none(parser) -> None:
    parser.new_infrastructure(
        "cli-infra",
        "boost_union",
        GitReference("main", GitReferenceType.BRANCH),
    )
    entry = _read(parser)["cli-infra"]
    assert "created_by" not in entry


def test_owner_model_from_stored_dict() -> None:
    model = _owner_model({"id": "user-1", "name": "Tess Ter", "email": "t@e.org"})
    assert model is not None
    assert model.id == "user-1" and model.name == "Tess Ter" and model.email == "t@e.org"


def test_owner_model_tolerates_missing_owner() -> None:
    assert _owner_model(None) is None
    assert _owner_model({}) is None
    assert _owner_model("not-a-dict") is None  # type: ignore[arg-type]
