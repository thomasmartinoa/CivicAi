import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import settings


class EmailService:
    async def send_email(self, to: str, subject: str, body: str) -> bool:
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
            return True
        except Exception as e:
            print(f"Email send failed: {e}")
            return False

    async def send_otp(self, email: str, otp: str) -> bool:
        return await self.send_email(
            to=email,
            subject="CivicAI - Your Verification Code",
            body=f"<h2>Your verification code is: <strong>{otp}</strong></h2><p>This code expires in {settings.otp_expire_minutes} minutes.</p>",
        )

    async def send_complaint_confirmation(self, email: str, tracking_id: str) -> bool:
        return await self.send_email(
            to=email,
            subject=f"CivicAI - Complaint Registered ({tracking_id})",
            body=f"<h2>Your complaint has been registered</h2><p>Tracking ID: <strong>{tracking_id}</strong></p><p>Use this ID to track your complaint status.</p>",
        )

    async def send_status_update(self, email: str, tracking_id: str, status: str) -> bool:
        return await self.send_email(
            to=email,
            subject=f"CivicAI - Complaint Update ({tracking_id})",
            body=f"<h2>Complaint Status Update</h2><p>Your complaint <strong>{tracking_id}</strong> status has been updated to: <strong>{status}</strong></p>",
        )


email_service = EmailService()
