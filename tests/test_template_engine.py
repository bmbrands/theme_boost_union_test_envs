"""Tests for the per-environment docker customisation (local.yml rendering)."""

from __future__ import annotations

import importlib
import types
from pathlib import Path

import pytest
import yaml

# The package re-exports a `template_engine()` function under the module's
# name, so import the module itself explicitly.
te_mod = importlib.import_module("theme_boost_union_test_envs.cross_cutting.template_engine")
TemplateEngine = te_mod.TemplateEngine

INI_MOUNT = "./php-moodle.ini:/usr/local/etc/php/conf.d/zz-boost-union-envs.ini:ro"


def _render(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, proxied: bool, version: str) -> dict:
    monkeypatch.setattr(te_mod, "config", lambda: types.SimpleNamespace(is_proxied=proxied))
    env_dir = tmp_path / "demo" / "moodles" / version
    env_dir.mkdir(parents=True)
    # A stale copy as seeded into .moodle-docker by an old `init`: it lacks the
    # $REPLACE_PROXY_OVERRIDES placeholder and must not be used as the source.
    (env_dir / "local.yml").write_text(
        'version: "2"\nservices:\n  webserver:\n    volumes:\n'
        '      - "$REPLACE_PLUGIN_SOURCE_PATH:/var/www/html/$REPLACE_PLUGIN_INSTALL_DIR:cached"\n'
    )
    TemplateEngine().docker_customisation(env_dir, tmp_path / "demo", "theme/boost_union", version)
    assert "zend.exception_ignore_args = On" in (env_dir / "php-moodle.ini").read_text()
    return yaml.safe_load((env_dir / "local.yml").read_text())["services"]["webserver"]


def test_local_environment_mounts_php_ini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    webserver = _render(tmp_path, monkeypatch, proxied=False, version="5.3.0")
    assert webserver["volumes"][0].endswith(":/var/www/html/public/theme/boost_union:cached")
    assert INI_MOUNT in webserver["volumes"]
    assert "environment" not in webserver


def test_proxied_environment_mounts_php_ini_and_proxy_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    webserver = _render(tmp_path, monkeypatch, proxied=True, version="4.5.7")
    assert webserver["volumes"][0].endswith(":/var/www/html/theme/boost_union:cached")
    assert INI_MOUNT in webserver["volumes"]
    assert any("moodle-prefix.conf" in v for v in webserver["volumes"])
    assert webserver["environment"] == {"MOODLE_DOCKER_WEB_PORT": ""}
