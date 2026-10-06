"""Email notifications (work package 5): settings, templates and rendering.

Settings live in the ``email`` section of ``settings.yaml``::

    email:
      smtp: {host, port, security, username, password, from_address, from_name}
      portal_url: ""              # link to the frontend; derived from config if empty
      timezone: Europe/Berlin     # how dates are shown in emails
      deletion_warning:
        enabled: false
        hours_before: 24
        subject: "..."            # Jinja2 template, see TEMPLATE_VARIABLES
        body: "..."

Templates are rendered in a sandbox with strict undefined variables, so a typo
in a placeholder is reported when the template is saved rather than silently
producing an empty value in a real email.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from ..cross_cutting.mailer import SmtpSettings

DEFAULT_SUBJECT = (
    "Your Moodle test instance {{ environment }} (Moodle {{ moodle_version }}) "
    "will be deleted on {{ deletion_date }}"
)

DEFAULT_BODY = """Hello {{ user_name }},

Your Moodle test instance "{{ environment }}" (Moodle {{ moodle_version }}) has been stopped since {{ stopped_since }}.
It will be deleted automatically on {{ deletion_date }}, including all of its data.

Do you still need it? Start it again before then in the Moodle Provisioner:
{{ portal_url }}

Starting the instance resets the deletion timer. Instances are deleted after
they have been stopped for {{ retention_days }} day(s).

--
Moodle Provisioner ({{ server_name }})
"""

# name -> (description, sample value used for previews and test emails)
TEMPLATE_VARIABLES: dict[str, tuple[str, str]] = {
    "user_name": ("Full name of the environment's owner", "Jane Doe"),
    "user_email": ("Email address of the owner", "jane.doe@example.org"),
    "environment": ("Environment (infrastructure) name", "my-feature-test"),
    "moodle_version": ("Moodle version of the instance", "5.0.2"),
    "instance_url": ("URL of the Moodle instance", "https://provisioner.example.org/my-feature-test/5.0.2/"),
    "portal_url": ("URL of the Moodle Provisioner frontend", "https://provisioner.example.org"),
    "server_name": ("Host name of the provisioner server", "provisioner.example.org"),
    "deletion_date": ("When the instance will be deleted", "8 Oct 2026, 14:30 CEST"),
    "stopped_since": ("When the instance was stopped", "7 Oct 2026, 14:30 CEST"),
    "retention_days": ("Days a stopped instance is kept", "1"),
    "hours_before": ("Hours before deletion this warning is sent", "24"),
}


@dataclass
class DeletionWarningSettings:
    enabled: bool = False
    hours_before: int = 24
    subject: str = DEFAULT_SUBJECT
    body: str = DEFAULT_BODY


@dataclass
class EmailSettings:
    smtp: SmtpSettings = field(default_factory=SmtpSettings)
    portal_url: str = ""
    timezone: str = "Europe/Berlin"
    deletion_warning: DeletionWarningSettings = field(
        default_factory=DeletionWarningSettings
    )

    def warning_active(self) -> bool:
        return self.deletion_warning.enabled and self.smtp.is_configured()


def _pick(cls: type, raw: Any) -> Any:
    """Build dataclass ``cls`` from a dict, ignoring unknown/mistyped keys."""
    obj = cls()
    if isinstance(raw, dict):
        for key, default in asdict(obj).items():
            if key in raw and isinstance(raw[key], type(default)):
                setattr(obj, key, raw[key])
    return obj


def settings_from_dict(raw: dict[str, Any] | None) -> EmailSettings:
    raw = raw if isinstance(raw, dict) else {}
    settings = _pick(EmailSettings, {k: v for k, v in raw.items() if k in ("portal_url", "timezone")})
    settings.smtp = _pick(SmtpSettings, raw.get("smtp"))
    settings.deletion_warning = _pick(DeletionWarningSettings, raw.get("deletion_warning"))
    return settings


def load_settings() -> EmailSettings:
    from ..cross_cutting import settings_store

    return settings_from_dict(settings_store.get_section("email"))


def save_settings(settings: EmailSettings) -> None:
    from ..cross_cutting import settings_store

    settings_store.set_section("email", asdict(settings))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_env = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)


class TemplateRenderError(ValueError):
    pass


def render(template: str, context: dict[str, Any]) -> str:
    try:
        return _env.from_string(template).render(**context)
    except TemplateError as exc:
        raise TemplateRenderError(str(exc)) from exc


def sample_context() -> dict[str, str]:
    return {name: sample for name, (_, sample) in TEMPLATE_VARIABLES.items()}


def validate_templates(subject: str, body: str) -> None:
    """Raise :class:`TemplateRenderError` if either template does not render."""
    ctx = sample_context()
    render(subject, ctx)
    render(body, ctx)


def render_deletion_warning(
    settings: EmailSettings, context: dict[str, Any]
) -> tuple[str, str]:
    """Return ``(subject, body)``; the subject is collapsed to a single line."""
    subject = " ".join(render(settings.deletion_warning.subject, context).split())
    body = render(settings.deletion_warning.body, context)
    return subject, body


# ---------------------------------------------------------------------------
# Context for a real instance
# ---------------------------------------------------------------------------


def _zone(name: str) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def format_date(value: datetime | None, tz_name: str) -> str:
    """Format a naive-UTC datetime for humans in ``tz_name``."""
    if value is None:
        return ""
    local = value.replace(tzinfo=timezone.utc).astimezone(_zone(tz_name))
    return f"{local.day} {local:%b %Y, %H:%M} {local.tzname()}"


def default_portal_url() -> str:
    from ..cross_cutting import config

    cfg = config()
    return f"{cfg.scheme}://{cfg.base_url}" if cfg.is_proxied else f"http://{cfg.base_url}"


def deletion_context(
    settings: EmailSettings,
    *,
    infrastructure: str,
    infra: dict[str, Any],
    version: str,
    moodle: dict[str, Any],
    deletion_at: datetime,
    stopped_at: datetime | None,
    retention_days: int,
    portal_url: str,
) -> dict[str, str]:
    owner = infra.get("created_by") if isinstance(infra.get("created_by"), dict) else {}
    portal = (settings.portal_url or portal_url).rstrip("/")
    server_name = portal.split("://", 1)[-1].split("/", 1)[0]
    return {
        "user_name": str(owner.get("name") or owner.get("email") or "there"),
        "user_email": str(owner.get("email") or ""),
        "environment": infrastructure,
        "moodle_version": version,
        "instance_url": str(moodle.get("url") or ""),
        "portal_url": portal,
        "server_name": server_name,
        "deletion_date": format_date(deletion_at, settings.timezone),
        "stopped_since": format_date(stopped_at, settings.timezone),
        "retention_days": str(retention_days),
        "hours_before": str(settings.deletion_warning.hours_before),
    }


def warn_before(settings: EmailSettings) -> timedelta | None:
    """How long before deletion to warn, or None when warnings are off."""
    if not settings.warning_active():
        return None
    return timedelta(hours=max(0, settings.deletion_warning.hours_before))


# ---------------------------------------------------------------------------
# Reaper integration
# ---------------------------------------------------------------------------


def make_deletion_notifier(
    settings: EmailSettings,
    testbed_info: dict[str, Any],
    retention_days: int,
    parser: Any,
    *,
    portal_url: str = "",
    send: Any = None,
    logger: Any = None,
) -> Any:
    """Return a callable for :func:`lifecycle.execute`'s ``notifier``.

    It emails the environment's owner about the upcoming deletion and records
    the deadline on the moodle record (``lifecycle.WARNING_SENT_KEY``) so the
    same stop cycle is not warned about again. Instances without a known
    owner email are logged and marked as handled.
    """
    from ..cross_cutting.mailer import send_mail
    from . import lifecycle

    send = send or send_mail

    def _mark(action: Any) -> None:
        name, version = action.infrastructure, action.version
        parser.merge_into_testbed_info(
            name,
            {name: {"moodles": {version: {lifecycle.WARNING_SENT_KEY: lifecycle.deadline_key(action.deadline)}}}},
            False,
        )

    def notify(action: Any) -> None:
        infra = testbed_info[action.infrastructure]
        moodle = infra["moodles"][action.version]
        context = deletion_context(
            settings,
            infrastructure=action.infrastructure,
            infra=infra,
            version=str(action.version),
            moodle=moodle,
            deletion_at=action.deadline,
            stopped_at=lifecycle._first_ts(moodle.get("stopped_at"), infra.get("last_modified_at")),
            retention_days=retention_days,
            portal_url=portal_url,
        )
        to = context["user_email"]
        if not to:
            if logger is not None:
                logger(f"no owner email for {action.infrastructure}/{action.version}; warning skipped")
            _mark(action)
            return
        subject, body = render_deletion_warning(settings, context)
        send(settings.smtp, to, subject, body)
        _mark(action)
        if logger is not None:
            logger(f"deletion warning sent to {to} for {action.infrastructure}/{action.version}")

    return notify
