from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class WorkOrderResponse(BaseModel):
    id: str
    complaint_id: str
    contractor_id: Optional[str] = None
    officer_id: Optional[str] = None
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
    contractor_id: Optional[str] = None
