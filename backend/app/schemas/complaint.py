from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator


class ComplaintSubmitted(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tracking_id: str
    status: str


class MediaSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    file_path: str
    media_type: str
    original_filename: str | None = None


class ComplaintDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tracking_id: str
    status: str
    description: str
    terminal_reason: str | None = None
    category: str | None = None
    subcategory: str | None = None
    priority_score: int | None = None
    risk_level: str | None = None
    address: str | None = None
    ward: str | None = None
    district: str | None = None
    created_at: datetime
    updated_at: datetime
    media: list[MediaSummary] = []


class OtpRequest(BaseModel):
    email: str


class OtpRequested(BaseModel):
    """Deliberately contentless. The same message comes back whether the address has
    complaints, has none, or has asked too often — see the route's docstring."""

    message: str


class OtpVerification(BaseModel):
    """The v1-era frontend posts this field as `otp`; the rest of the codebase calls
    it a code. Both are accepted rather than renaming one of them, because changing
    the wire name would break the existing screen for no gain."""

    email: str
    code: str

    @model_validator(mode="before")
    @classmethod
    def _accept_otp_as_code(cls, data):
        """Map the frontend's `otp` onto `code`.

        A validator rather than a validation_alias: the alias form works but makes
        Pydantic emit an UnsupportedFieldAttributeWarning when FastAPI rebuilds the
        body model, and a suppressed warning whose cause is not understood is worse
        than three explicit lines.
        """
        if isinstance(data, dict) and "code" not in data and "otp" in data:
            data = {**data, "code": data["otp"]}
        return data


class VerifiedComplaints(BaseModel):
    email: str
    access_token: str
    """Proof of control of the address, for the follow-up call to /complaints/my.
    Without it that endpoint would have to trust an email in a query string."""
    token_type: str = "bearer"
    complaints: list[ComplaintDetail] = []
