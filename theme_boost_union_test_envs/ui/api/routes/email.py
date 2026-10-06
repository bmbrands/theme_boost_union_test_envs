"""Email (SMTP + notification template) settings for administrators.

The SMTP password is write-only: responses only say whether one is stored,
and sending ``password: null`` keeps the stored one.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from theme_boost_union_test_envs.cross_cutting.logger import log
from theme_boost_union_test_envs.cross_cutting.mailer import (
    MailError,
    SmtpSettings,
    send_mail,
)
from theme_boost_union_test_envs.domain import notifications

from ..security import require_settings_admin

router = APIRouter(
    prefix="/api/email",
    tags=["email"],
    dependencies=[Depends(require_settings_admin)],
)

_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class SmtpIn(BaseModel):
    host: str = Field(default="", max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    security: Literal["none", "starttls", "ssl"] = "starttls"
    username: str = Field(default="", max_length=255)
    # None keeps the stored password; "" clears it.
    password: str | None = None
    from_address: str = Field(default="", pattern=r"^$|" + _EMAIL_PATTERN)
    from_name: str = Field(default="Moodle Provisioner", max_length=255)


class DeletionWarningIn(BaseModel):
    enabled: bool = False
    hours_before: int = Field(default=24, ge=0, le=24 * 30)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=20000)


class EmailSettingsIn(BaseModel):
    smtp: SmtpIn
    portal_url: str = Field(default="", pattern=r"^$|^https?://\S+$")
    timezone: str = "Europe/Berlin"
    deletion_warning: DeletionWarningIn

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone {value!r}") from exc
        return value


class TestEmailIn(BaseModel):
    to: str = Field(pattern=_EMAIL_PATTERN)
    settings: EmailSettingsIn


class PreviewIn(BaseModel):
    subject: str
    body: str


def _response(settings: notifications.EmailSettings) -> dict[str, Any]:
    smtp = asdict(settings.smtp)
    smtp.pop("timeout_seconds", None)
    password_set = bool(smtp.pop("password"))
    return {
        "smtp": {**smtp, "password_set": password_set},
        "portal_url": settings.portal_url,
        "timezone": settings.timezone,
        "deletion_warning": asdict(settings.deletion_warning),
        # Helpers for the admin UI.
        "default_portal_url": _default_portal_url(),
        "variables": [
            {"name": name, "description": desc, "example": example}
            for name, (desc, example) in notifications.TEMPLATE_VARIABLES.items()
        ],
        "defaults": {
            "subject": notifications.DEFAULT_SUBJECT,
            "body": notifications.DEFAULT_BODY,
        },
    }


def _default_portal_url() -> str:
    try:
        return notifications.default_portal_url()
    except Exception:  # noqa: BLE001 - config may be unavailable in odd setups
        return ""


def _to_settings(
    payload: EmailSettingsIn, stored: notifications.EmailSettings
) -> notifications.EmailSettings:
    smtp_in = payload.smtp.model_dump()
    password = smtp_in.pop("password")
    smtp = SmtpSettings(
        **smtp_in,
        password=stored.smtp.password if password is None else password,
    )
    return notifications.EmailSettings(
        smtp=smtp,
        portal_url=payload.portal_url,
        timezone=payload.timezone,
        deletion_warning=notifications.DeletionWarningSettings(
            **payload.deletion_warning.model_dump()
        ),
    )


def _validate_templates(subject: str, body: str) -> None:
    try:
        notifications.validate_templates(subject, body)
    except notifications.TemplateRenderError as exc:
        raise HTTPException(status_code=422, detail=f"Template error: {exc}") from exc


@router.get("")
def get_email_settings() -> dict[str, Any]:
    return _response(notifications.load_settings())


@router.put("")
def put_email_settings(
    payload: EmailSettingsIn,
    user: dict[str, Any] = Depends(require_settings_admin),
) -> dict[str, Any]:
    _validate_templates(payload.deletion_warning.subject, payload.deletion_warning.body)
    settings = _to_settings(payload, notifications.load_settings())
    notifications.save_settings(settings)
    log().info(
        "email settings updated by {} (smtp host {!r}, warnings {})",
        user.get("email", "?"),
        settings.smtp.host,
        "on" if settings.deletion_warning.enabled else "off",
    )
    return _response(settings)


@router.post("/preview")
def preview(payload: PreviewIn) -> dict[str, str]:
    _validate_templates(payload.subject, payload.body)
    settings = notifications.EmailSettings(
        deletion_warning=notifications.DeletionWarningSettings(
            subject=payload.subject, body=payload.body
        )
    )
    subject, body = notifications.render_deletion_warning(
        settings, notifications.sample_context()
    )
    return {"subject": subject, "body": body}


@router.post("/test")
def send_test_email(payload: TestEmailIn) -> dict[str, Any]:
    """Send the deletion warning, filled with sample data, using the form's
    (possibly unsaved) settings."""
    warning = payload.settings.deletion_warning
    _validate_templates(warning.subject, warning.body)
    settings = _to_settings(payload.settings, notifications.load_settings())
    # Sample instance data, but the real links so the admin can check them.
    portal = (settings.portal_url or _default_portal_url() or "").rstrip("/")
    context = {**notifications.sample_context(), "user_email": payload.to}
    if portal:
        context["portal_url"] = portal
        context["server_name"] = portal.split("://", 1)[-1].split("/", 1)[0]
    subject, body = notifications.render_deletion_warning(settings, context)
    try:
        send_mail(settings.smtp, payload.to, f"[Test] {subject}", body)
    except MailError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "message": f"Test email sent to {payload.to}"}
