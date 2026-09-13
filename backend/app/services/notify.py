"""Citizen notification, with an audit row for every attempt.

Two things carried forward deliberately. v1 logged every attempt with an
`is_sent` flag whether or not SMTP worked, which was right — a failed send must
leave evidence. And `notifications.dedupe_key` is unique because v1 re-sent SLA
warnings every five minutes for hours.
"""

import logging
import smtplib
from collections.abc import Callable
from email.message import EmailMessage

from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.base import utcnow
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


def _send_email(recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = "CivicAI <noreply@civicai.gov>"
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(message)


def notify_citizen(
    *,
    tracking_id: str,
    complaint_id: str,
    category: str | None,
    status: str,
    recipient: str,
    session_factory: Callable = SessionLocal,
) -> None:
    from app.db.models.workflow import Notification

    subject = f"CivicAI — your complaint {tracking_id}"
    body = (
        f"Your complaint {tracking_id} has been processed.\n\n"
        f"Category: {category or 'under review'}\n"
        f"Status: {status}\n"
    )

    sent = False
    try:
        _send_email(recipient, subject, body)
        sent = True
    except Exception:
        logger.warning("notification send failed for %s", tracking_id, exc_info=True)

    session = session_factory()
    try:
        session.add(Notification(
            complaint_id=complaint_id,
            recipient_email=recipient,
            notification_type="status_update",
            message=subject,
            is_sent=sent,
            sent_at=utcnow() if sent else None,
            dedupe_key=f"{complaint_id}:status_update:{status}",
        ))
        session.commit()
    except IntegrityError as exc:
        # Only the dedupe collision is expected here. Anything else is a real
        # constraint failure that must surface, not be mistaken for "already sent".
        if "dedupe_key" not in str(exc.orig):
            session.rollback()
            raise
        # dedupe_key is unique: this exact notification was already recorded.
        session.rollback()
    finally:
        session.close()
