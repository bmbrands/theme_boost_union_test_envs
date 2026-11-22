"""Tests for the data protection declaration (sanitizer and API)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from theme_boost_union_test_envs.cross_cutting import settings_store as store_mod
from theme_boost_union_test_envs.domain.privacy import sanitize_html

from .test_admin_settings import _login_tester, _settings
from .test_auth import _FakeConfig, _promote_admin
from .test_auth import client as auth_client  # noqa: F401 - pytest fixture


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("<h2>Title</h2><p>Text <strong>bold</strong> <em>it</em> <u>u</u></p>",
         "<h2>Title</h2><p>Text <strong>bold</strong> <em>it</em> <u>u</u></p>"),
        ("<b>b</b><i>i</i><div>block</div><h1>big</h1><h4>small</h4>",
         "<strong>b</strong><em>i</em><p>block</p><h2>big</h2><h3>small</h3>"),
        ("<ul><li>one</li><li>two</li></ul><ol><li>x</li></ol>",
         "<ul><li>one</li><li>two</li></ul><ol><li>x</li></ol>"),
        ("line<br>next<br/>", "line<br>next<br>"),
        # Scripts, styles and their content disappear.
        ("<p>ok</p><script>alert(1)</script><style>p{}</style>", "<p>ok</p>"),
        # Unknown tags are removed, their text is kept.
        ("<span style='color:red'>red</span><table><tr><td>cell</td></tr></table>", "redcell"),
        # Attributes other than a safe href are dropped.
        ('<p class="x" onclick="evil()">p</p>', "<p>p</p>"),
        ('<a href="https://example.org" onclick="x">site</a>',
         '<a href="https://example.org" target="_blank" rel="noopener noreferrer">site</a>'),
        ('<a href="mailto:dpo@example.org">mail</a>', '<a href="mailto:dpo@example.org">mail</a>'),
        # Dangerous or protocol-relative links lose the link but keep the text.
        ('<a href="javascript:alert(1)">x</a>', "x"),
        ('<a href="//evil.example">x</a>', "x"),
        ("<p>unclosed <strong>bold", "<p>unclosed <strong>bold</strong></p>"),
        ("1 < 2 &amp; 3 > 2", "1 &lt; 2 &amp; 3 &gt; 2"),
        # Editor output with a list inside a paragraph becomes valid HTML.
        ("<p>Intro</p><p><ul><li>a</li></ul></p>", "<p>Intro</p><ul><li>a</li></ul>"),
        ("<p></p><p><br></p><p>kept</p>", "<p>kept</p>"),
    ],
)
def test_sanitize_html(raw: str, expected: str) -> None:
    assert sanitize_html(raw) == expected


@pytest.fixture()
def client(
    auth_client: TestClient,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    monkeypatch.setattr(store_mod, "config", lambda: _FakeConfig(tmp_path))
    return auth_client


def test_privacy_page_is_public_and_empty_by_default(client: TestClient) -> None:
    resp = client.get("/api/privacy")  # not logged in
    assert resp.status_code == 200
    assert resp.json()["html"] == ""


def test_admin_saves_sanitized_declaration(client: TestClient, tmp_path: Path) -> None:
    _promote_admin(client)
    resp = client.put("/api/privacy", json={"html": "<h2>Privacy</h2><p>We store <b>nothing</b>.</p><script>x</script>"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["html"] == "<h2>Privacy</h2><p>We store <strong>nothing</strong>.</p>"
    assert body["updated_at"] and body["updated_by"]
    assert _settings(tmp_path)["privacy"]["html"] == body["html"]

    client.post("/api/auth/logout")
    assert client.get("/api/privacy").json()["html"] == body["html"]


def test_tester_cannot_change_declaration(client: TestClient) -> None:
    _promote_admin(client)
    _login_tester(client)
    assert client.put("/api/privacy", json={"html": "<p>x</p>"}).status_code == 403


def test_anonymous_cannot_change_declaration(client: TestClient) -> None:
    assert client.put("/api/privacy", json={"html": "<p>x</p>"}).status_code == 401


def test_generic_settings_put_keeps_declaration(client: TestClient, tmp_path: Path) -> None:
    _promote_admin(client)
    client.put("/api/privacy", json={"html": "<p>kept</p>"})
    client.put("/api/settings", json={"values": {"privacy": {"html": "<script>x</script>"}}})
    assert _settings(tmp_path)["privacy"]["html"] == "<p>kept</p>"
