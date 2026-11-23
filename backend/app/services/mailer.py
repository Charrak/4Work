import logging
import smtplib
from email.message import EmailMessage

from ..config import settings

log = logging.getLogger("dienstplan.mail")


def send_mail(to: str, subject: str, body: str) -> bool:
    """Sendet per SMTP. Ohne SMTP-Konfiguration wird der Inhalt ins Server-Log geschrieben."""
    if not settings.smtp_host:
        log.warning("SMTP nicht konfiguriert. Mail an %s: %s | %s", to, subject, body)
        return False
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
            s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
        return True
    except Exception:
        log.exception("E-Mail-Versand fehlgeschlagen")
        return False
