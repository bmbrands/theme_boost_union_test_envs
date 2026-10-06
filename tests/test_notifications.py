"""Tests for deletion warning emails (work package 5).

Planning and rendering are pure; the notifier and SMTP client are exercised
with fakes, and the admin API with the hermetic client from ``test_auth``.
No real mail is sent.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from theme_boost_union_test_envs.cross_cutting import mailer
from theme_boost_union_test_envs.cross_cutting import settings_store as store_mod
from theme_boost_union_test_envs.domain import notifications
from theme_boost_union_test_envs.domain.lifecycle import (
    WARNING_SENT_KEY,
    Action,
    LifecyclePolicy,
    deadline_key,
    execute,
    plan_actions,
)
from theme_boost_union_test_envs.ui.api.routes import email as email_mod

from .test_auth import _FakeConfig, _promote_admin
from .test_auth import client as auth_client  # noqa: F401 - pytest fixture

NOW = datetime(2026, 1, 10, 12, 0, 0)
POLICY = LifecyclePolicy(
    auto_cleanup_enabled=True, stopped_retention_days=3, cleanup_empty_infrastructures=False
)
WARN = timedelta(hours=24)


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _testbed(**moodle_extra) -> dict:
    return {
        "demo": {
            "created_at": _ts(NOW - timedelta(days=30)),
            "last_modified_at": _ts(NOW - timedelta(days=30)),
            "created_by": {"id": "u1", "name": "Jane Doe", "email": "jane@example.org"},
            "moodles": {
                "5.0.0": {
                    "status": "STOPPED",
                    "url": "https://host/demo/5.0.0/",
                    **moodle_extra,
                }
            },
        }
    }


# ---- planning -----------------------------------------------------------


def test_notify_when_deletion_within_warning_window() -> None:
    stopped = NOW - timedelta(days=2, hours=1)  # deletion in 23h
    actions = plan_actions(_testbed(stopped_at=_ts(stopped)), POLICY, NOW, WARN)
    assert [(a.kind, a.version) for a in actions] == [("notify", "5.0.0")]
    assert actions[0].deadline == stopped + timedelta(days=3)


def test_no_notify_before_warning_window() -> None:
    stopped = NOW - timedelta(days=1)  # deletion in 48h
    assert plan_actions(_testbed(stopped_at=_ts(stopped)), POLICY, NOW, WARN) == []


def test_no_notify_when_already_warned_for_this_deadline() -> None:
    stopped = NOW - timedelta(days=2, hours=1)
    deadline = stopped + timedelta(days=3)
    tb = _testbed(stopped_at=_ts(stopped), **{WARNING_SENT_KEY: deadline_key(deadline)})
    assert plan_actions(tb, POLICY, NOW, WARN) == []


def test_new_stop_cycle_is_warned_again() -> None:
    stopped = NOW - timedelta(days=2, hours=1)
    tb = _testbed(stopped_at=_ts(stopped), **{WARNING_SENT_KEY: "2025-01-01T00:00:00Z"})
    assert [a.kind for a in plan_actions(tb, POLICY, NOW, WARN)] == ["notify"]


def test_no_notify_without_warn_window() -> None:
    stopped = NOW - timedelta(days=2, hours=1)
    assert plan_actions(_testbed(stopped_at=_ts(stopped)), POLICY, NOW) == []


def test_destroy_not_notify_once_deadline_passed() -> None:
    stopped = NOW - timedelta(days=4)
    actions = plan_actions(_testbed(stopped_at=_ts(stopped)), POLICY, NOW, WARN)
    assert [a.kind for a in actions] == ["destroy"]


# ---- rendering ----------------------------------------------------------


def test_default_templates_render_with_sample_data() -> None:
    notifications.validate_templates(notifications.DEFAULT_SUBJECT, notifications.DEFAULT_BODY)


def test_unknown_variable_is_rejected() -> None:
    with pytest.raises(notifications.TemplateRenderError):
        notifications.validate_templates("Hi {{ usr_name }}", "body")


def test_format_date_uses_configured_timezone() -> None:
    assert notifications.format_date(datetime(2026, 7, 1, 12, 0), "Europe/Berlin") == "1 Jul 2026, 14:00 CEST"
    assert notifications.format_date(datetime(2026, 7, 1, 12, 0), "Not/AZone").endswith("UTC")


# ---- notifier -----------------------------------------------------------


class _FakeParser:
    def __init__(self) -> None:
        self.merged: list[dict] = []

    def merge_into_testbed_info(self, name, data, should_change_modified_date=True):
        assert should_change_modified_date is False
        self.merged.append(data)


def _email_settings() -> notifications.EmailSettings:
    s = notifications.EmailSettings()
    s.smtp.host, s.smtp.from_address = "smtp.example.org", "noreply@example.org"
    s.deletion_warning.enabled = True
    return s


def test_notifier_emails_owner_and_marks_deadline() -> None:
    stopped = NOW - timedelta(days=2, hours=1)
    tb = _testbed(stopped_at=_ts(stopped))
    sent: list[tuple] = []
    parser = _FakeParser()
    notify = notifications.make_deletion_notifier(
        _email_settings(), tb, 3, parser,
        portal_url="https://portal.example.org",
        send=lambda smtp, to, subject, body: sent.append((to, subject, body)),
    )
    actions = plan_actions(tb, POLICY, NOW, WARN)
    summary = execute(actions, core=None, notifier=notify)

    assert summary.notified == 1 and summary.failures == 0
    to, subject, body = sent[0]
    assert to == "jane@example.org"
    assert "demo" in subject and "5.0.0" in subject
    assert "Hello Jane Doe" in body and "https://portal.example.org" in body
    marker = parser.merged[0]["demo"]["moodles"]["5.0.0"][WARNING_SENT_KEY]
    assert marker == deadline_key(actions[0].deadline)


def test_notifier_skips_and_marks_when_owner_unknown() -> None:
    tb = _testbed(stopped_at=_ts(NOW - timedelta(days=2, hours=1)))
    del tb["demo"]["created_by"]
    parser = _FakeParser()
    sent: list = []
    notify = notifications.make_deletion_notifier(
        _email_settings(), tb, 3, parser, send=lambda *a: sent.append(a)
    )
    notify(Action("notify", "demo", "5.0.0", deadline=NOW))
    assert sent == [] and len(parser.merged) == 1


def test_dry_run_does_not_notify() -> None:
    called: list = []
    summary = execute(
        [Action("notify", "demo", "5.0.0", deadline=NOW)],
        core=None,
        dry_run=True,
        notifier=called.append,
    )
    assert called == [] and summary.notified == 0


# ---- SMTP client --------------------------------------------------------


class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, **kwargs) -> None:
        self.host, self.port, self.calls = host, port, []
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg):
        self.calls.append(("send", msg["To"], msg["Subject"]))


def test_send_mail_uses_starttls_and_login(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeSMTP.instances = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)
    smtp = mailer.SmtpSettings(
        host="smtp.example.org", port=587, username="u", password="p",
        from_address="noreply@example.org",
    )
    mailer.send_mail(smtp, "jane@example.org", "Subject", "Body")
    calls = _FakeSMTP.instances[0].calls
    assert calls == ["starttls", ("login", "u", "p"), ("send", "jane@example.org", "Subject")]


def test_send_mail_requires_configuration() -> None:
    with pytest.raises(mailer.MailError):
        mailer.send_mail(mailer.SmtpSettings(), "jane@example.org", "s", "b")


# ---- admin API ----------------------------------------------------------


@pytest.fixture()
def client(
    auth_client: TestClient,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    monkeypatch.setattr(store_mod, "config", lambda: _FakeConfig(tmp_path))
    monkeypatch.setattr(email_mod, "_default_portal_url", lambda: "https://portal.example.org")
    return auth_client


def _payload(**smtp) -> dict:
    return {
        "smtp": {
            "host": "smtp.example.org",
            "port": 587,
            "security": "starttls",
            "username": "mailer",
            "password": None,
            "from_address": "noreply@example.org",
            "from_name": "Provisioner",
            **smtp,
        },
        "portal_url": "",
        "timezone": "Europe/Berlin",
        "deletion_warning": {
            "enabled": True,
            "hours_before": 24,
            "subject": notifications.DEFAULT_SUBJECT,
            "body": notifications.DEFAULT_BODY,
        },
    }


def test_email_settings_password_is_write_only(client: TestClient) -> None:
    _promote_admin(client)
    resp = client.put("/api/email", json=_payload(password="s3cret"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["smtp"]["password_set"] is True
    assert "password" not in body["smtp"]

    # Saving again with password=null keeps the stored one.
    client.put("/api/email", json=_payload(password=None))
    assert notifications.load_settings().smtp.password == "s3cret"
    assert client.get("/api/email").json()["smtp"]["password_set"] is True


def test_email_settings_reject_bad_template_and_timezone(client: TestClient) -> None:
    _promote_admin(client)
    bad = _payload()
    bad["deletion_warning"]["body"] = "Hi {{ nope }}"
    resp = client.put("/api/email", json=bad)
    assert resp.status_code == 422 and "nope" in resp.text

    bad = _payload()
    bad["timezone"] = "Mars/Olympus"
    assert client.put("/api/email", json=bad).status_code == 422


def test_send_test_email_uses_form_values_and_stored_password(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _promote_admin(client)
    client.put("/api/email", json=_payload(password="s3cret"))
    sent: list = []
    monkeypatch.setattr(email_mod, "send_mail", lambda smtp, to, s, b: sent.append((smtp, to, s, b)))

    resp = client.post(
        "/api/email/test",
        json={"to": "admin@example.org", "settings": _payload(host="other.example.org")},
    )
    assert resp.status_code == 200, resp.text
    smtp, to, subject, body = sent[0]
    assert smtp.host == "other.example.org" and smtp.password == "s3cret"
    assert to == "admin@example.org" and subject.startswith("[Test] ")
    assert "Jane Doe" in body


def test_send_test_email_reports_smtp_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _promote_admin(client)

    def boom(*_a):
        raise mailer.MailError("SMTPAuthenticationError: bad credentials")

    monkeypatch.setattr(email_mod, "send_mail", boom)
    resp = client.post("/api/email/test", json={"to": "a@example.org", "settings": _payload()})
    assert resp.status_code == 502 and "bad credentials" in resp.text


def test_preview_renders_sample_data(client: TestClient) -> None:
    _promote_admin(client)
    resp = client.post("/api/email/preview", json={"subject": "Bye {{ environment }}", "body": "{{ deletion_date }}"})
    assert resp.json() == {"subject": "Bye my-feature-test", "body": "8 Oct 2026, 14:30 CEST"}


def test_email_settings_require_admin(client: TestClient) -> None:
    assert client.get("/api/email").status_code == 401
