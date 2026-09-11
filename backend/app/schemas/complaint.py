from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
