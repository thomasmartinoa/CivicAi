from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class MessageResponse(BaseModel):
    message: str
