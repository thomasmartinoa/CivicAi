import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models.complaint import Complaint
from app.db.models.core import Tenant
from app.db.models.workflow import Notification
from app.services.notify import notify_citizen
from app.services.seed import seed_database


def _complaint(db_session):
    seed_database(db_session)
    complaint = Complaint(
        tracking_id="CIV-NOTIFY01", tenant_id=db_session.query(Tenant).one().id,
        citizen_email="a@b.com", description="x" * 40,
    )
    db_session.add(complaint)
    db_session.commit()
    return complaint


def test_a_notification_is_recorded_even_when_sending_fails(db_session, monkeypatch):
    """v1 logged every attempt with an is_sent flag and that was right — a failed
    send must still leave evidence."""
    complaint = _complaint(db_session)
    monkeypatch.setattr("app.services.notify._send_email",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("smtp down")))

    notify_citizen(tracking_id=complaint.tracking_id, complaint_id=complaint.id,
                   category="ROADS", status="assigned", recipient="a@b.com",
                   session_factory=lambda: db_session)

    record = db_session.query(Notification).one()
    assert record.is_sent is False
    assert record.sent_at is None


def test_a_successful_send_is_recorded_as_sent(db_session, monkeypatch):
    complaint = _complaint(db_session)
    monkeypatch.setattr("app.services.notify._send_email", lambda *a, **k: None)

    notify_citizen(tracking_id=complaint.tracking_id, complaint_id=complaint.id,
                   category="ROADS", status="assigned", recipient="a@b.com",
                   session_factory=lambda: db_session)

    record = db_session.query(Notification).one()
    assert record.is_sent is True
    assert record.sent_at is not None


def test_the_same_notification_twice_records_once(db_session, monkeypatch):
    """notifications.dedupe_key is unique — Phase 0 added it because v1 re-sent
    SLA warnings every five minutes."""
    complaint = _complaint(db_session)
    monkeypatch.setattr("app.services.notify._send_email", lambda *a, **k: None)
    for _ in range(2):
        notify_citizen(tracking_id=complaint.tracking_id, complaint_id=complaint.id,
                       category="ROADS", status="assigned", recipient="a@b.com",
                       session_factory=lambda: db_session)
    assert db_session.query(Notification).count() == 1


def test_a_non_dedupe_integrity_error_propagates(db_session, monkeypatch):
    """A foreign key or other constraint failure must not be mistaken for a
    dedupe collision and silently swallowed. Only dedupe_key violations are
    expected and safe to ignore."""
    complaint = _complaint(db_session)
    monkeypatch.setattr("app.services.notify._send_email", lambda *a, **k: None)

    # Pass a non-existent complaint_id to trigger a foreign key violation
    # (foreign keys are enforced in tests via PRAGMA foreign_keys=ON)
    with pytest.raises(IntegrityError):
        notify_citizen(tracking_id="CIV-FAKE", complaint_id="nonexistent_id",
                       category="ROADS", status="assigned", recipient="a@b.com",
                       session_factory=lambda: db_session)


def test_starttls_not_called_on_loopback(monkeypatch):
    """Development relay on localhost:1025 (MailHog) doesn't support TLS.
    Credentials sent over loopback are safe from network eavesdropping."""
    from app.services.notify import _send_email

    call_log = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host
            self.port = port

        def starttls(self, context=None):
            call_log.append("starttls")

        def login(self, user, password):
            call_log.append("login")

        def send_message(self, msg):
            call_log.append("send_message")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("app.services.notify.smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("app.config.settings.smtp_host", "localhost")
    monkeypatch.setattr("app.config.settings.smtp_port", 1025)
    monkeypatch.setattr("app.config.settings.smtp_user", "user")
    monkeypatch.setattr("app.config.settings.smtp_password", "pass")

    _send_email("test@example.com", "subject", "body")

    # starttls should NOT be called for localhost
    assert "starttls" not in call_log
    assert call_log == ["login", "send_message"]


def test_starttls_called_before_login_on_remote_host(monkeypatch):
    """Remote SMTP hosts must negotiate TLS before credentials are sent."""
    from app.services.notify import _send_email

    call_log = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host
            self.port = port

        def starttls(self, context=None):
            call_log.append("starttls")

        def login(self, user, password):
            call_log.append("login")

        def send_message(self, msg):
            call_log.append("send_message")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("app.services.notify.smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("app.config.settings.smtp_host", "smtp.example.com")
    monkeypatch.setattr("app.config.settings.smtp_port", 587)
    monkeypatch.setattr("app.config.settings.smtp_user", "user")
    monkeypatch.setattr("app.config.settings.smtp_password", "pass")

    _send_email("test@example.com", "subject", "body")

    # starttls must be called before login
    assert call_log == ["starttls", "login", "send_message"]
