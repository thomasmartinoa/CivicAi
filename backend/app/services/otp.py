import random
import string
from datetime import datetime, timezone, timedelta

from app.config import settings

_otp_store: dict[str, dict] = {}


class OTPService:
    def generate_otp(self, email: str) -> str:
        otp = "".join(random.choices(string.digits, k=6))
        _otp_store[email] = {
            "otp": otp,
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=settings.otp_expire_minutes),
        }
        return otp

    def verify_otp(self, email: str, otp: str) -> bool:
        stored = _otp_store.get(email)
        if not stored: return False
        if datetime.now(timezone.utc) > stored["expires_at"]:
            del _otp_store[email]
            return False
        if stored["otp"] != otp: return False
        del _otp_store[email]
        return True


otp_service = OTPService()
