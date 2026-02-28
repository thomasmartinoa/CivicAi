from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class MediaInfo(BaseModel):
    file_path: str
    media_type: str
    original_filename: Optional[str] = None

    class Config:
        from_attributes = True


class ComplaintCreate(BaseModel):
    description: str
    citizen_email: str
    citizen_phone: Optional[str] = None
    citizen_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None


class ComplaintResponse(BaseModel):
    id: str
    tracking_id: str
    status: str
    description: str
    citizen_email: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    priority_score: Optional[int] = None
    risk_level: Optional[str] = None
    address: Optional[str] = None
    ward: Optional[str] = None
    district: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    media: list[MediaInfo] = []
    satisfaction_rating: Optional[int] = None
    verified_fixed: Optional[bool] = None
    reopen_count: int = 0

    class Config:
        from_attributes = True


class ComplaintListResponse(BaseModel):
    complaints: list[ComplaintResponse]
    total: int


class ComplaintTrackResponse(BaseModel):
    id: str
    tracking_id: str
    status: str
    description: str
    citizen_email: str
    category: Optional[str] = None
    subcategory: Optional[str] = None
    priority_score: Optional[int] = None
    risk_level: Optional[str] = None
    address: Optional[str] = None
    ward: Optional[str] = None
    district: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    created_at: datetime
    updated_at: datetime
    media: list[MediaInfo] = []
    satisfaction_rating: Optional[int] = None
    verified_fixed: Optional[bool] = None
    reopen_count: int = 0

    class Config:
        from_attributes = True


class OTPRequest(BaseModel):
    email: str


class OTPVerify(BaseModel):
    email: str
    otp: str
