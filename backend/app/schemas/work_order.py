import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class WorkOrderResponse(BaseModel):
    id: uuid.UUID
    complaint_id: uuid.UUID
    contractor_id: Optional[uuid.UUID] = None
    officer_id: Optional[uuid.UUID] = None
    status: str
    sla_deadline: Optional[datetime] = None
    estimated_cost: Optional[float] = None
    materials: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkOrderUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    contractor_id: Optional[uuid.UUID] = None
