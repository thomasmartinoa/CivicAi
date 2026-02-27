import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from app.config import settings


class EmailService:
    async def send_email(self, to: str, subject: str, body: str,
                         notification_type: str = "general",
                         complaint_id: Optional[str] = None,
                         db=None) -> bool:
        sent = False
        try:
            msg = MIMEMultipart()
            msg["From"] = "CivicAI <noreply@civicai.gov>"
            msg["To"] = to
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "html"))

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
            sent = True
        except Exception as e:
            print(f"Email send failed: {e}")

        # Always log notification to DB audit trail
        if db is not None:
            try:
                from app.models.notification import Notification
                notif = Notification(
                    complaint_id=complaint_id,
                    recipient_email=to,
                    notification_type=notification_type,
                    message=subject,
                    is_sent=sent,
                    sent_at=datetime.now(timezone.utc) if sent else None,
                )
                db.add(notif)
                db.commit()
            except Exception as e:
                print(f"Notification log failed: {e}")

        return sent

    async def send_otp(self, email: str, otp: str, db=None) -> bool:
        return await self.send_email(
            to=email,
            subject="CivicAI - Your Verification Code",
            body=f"<h2>Your verification code is: <strong>{otp}</strong></h2><p>This code expires in {settings.otp_expire_minutes} minutes.</p>",
            notification_type="otp",
            db=db,
        )

    async def send_complaint_confirmation(self, email: str, tracking_id: str,
                                          complaint_id: Optional[str] = None, db=None) -> bool:
        return await self.send_email(
            to=email,
            subject=f"CivicAI - Complaint Registered ({tracking_id})",
            body=f"<h2>Your complaint has been registered</h2><p>Tracking ID: <strong>{tracking_id}</strong></p><p>Use this ID to track your complaint status.</p>",
            notification_type="confirmation",
            complaint_id=complaint_id,
            db=db,
        )

    async def send_status_update(self, email: str, tracking_id: str, status: str,
                                 complaint_id: Optional[str] = None, db=None) -> bool:
        return await self.send_email(
            to=email,
            subject=f"CivicAI - Complaint Update ({tracking_id})",
            body=f"<h2>Complaint Status Update</h2><p>Your complaint <strong>{tracking_id}</strong> status has been updated to: <strong>{status}</strong></p>",
            notification_type="status_update",
            complaint_id=complaint_id,
            db=db,
        )


email_service = EmailService()
