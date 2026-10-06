"""Send plain-text email through the configured SMTP server."""

from __future__ import annotations

import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

SECURITY_NONE = "none"
SECURITY_STARTTLS = "starttls"
SECURITY_SSL = "ssl"
SECURITY_MODES = (SECURITY_NONE, SECURITY_STARTTLS, SECURITY_SSL)


@dataclass
class SmtpSettings:
    host: str = ""
    port: int = 587
    security: str = SECURITY_STARTTLS  # none | starttls | ssl
    username: str = ""
    password: str = ""
    from_address: str = ""
    from_name: str = "Moodle Provisioner"
    timeout_seconds: int = 15

    def is_configured(self) -> bool:
        return bool(self.host and self.from_address)


class MailError(Exception):
    """Sending failed; the message is safe to show to an administrator."""


def build_message(smtp: SmtpSettings, to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((smtp.from_name, smtp.from_address))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    domain = smtp.from_address.rpartition("@")[2] or None
    msg["Message-ID"] = make_msgid(domain=domain)
    msg.set_content(body)
    return msg


def send_mail(smtp: SmtpSettings, to: str, subject: str, body: str) -> None:
    """Send one plain-text email. Raises :class:`MailError` on any failure."""
    if not smtp.is_configured():
        raise MailError("SMTP server and sender address must be configured")
    if smtp.security not in SECURITY_MODES:
        raise MailError(f"Unknown SMTP security mode {smtp.security!r}")

    msg = build_message(smtp, to, subject, body)
    context = ssl.create_default_context()
    # Pass our own EHLO name: smtplib otherwise calls socket.getfqdn(), which
    # can block for a long time on hosts with slow reverse DNS.
    local_hostname = socket.gethostname() or "localhost"
    try:
        if smtp.security == SECURITY_SSL:
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                smtp.host,
                smtp.port,
                local_hostname=local_hostname,
                timeout=smtp.timeout_seconds,
                context=context,
            )
        else:
            client = smtplib.SMTP(
                smtp.host,
                smtp.port,
                local_hostname=local_hostname,
                timeout=smtp.timeout_seconds,
            )
        with client:
            if smtp.security == SECURITY_STARTTLS:
                client.starttls(context=context)
            if smtp.username:
                client.login(smtp.username, smtp.password)
            client.send_message(msg)
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise MailError(f"{type(exc).__name__}: {exc}") from exc
