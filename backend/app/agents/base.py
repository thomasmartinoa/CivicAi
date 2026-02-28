from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PipelineContext:
    complaint_id: str
    tenant_id: Optional[str] = None
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    status: str = "submitted"
    raw_input: dict = field(default_factory=dict)
    structured_complaint: dict = field(default_factory=dict)
    classification: dict = field(default_factory=dict)
    risk_assessment: dict = field(default_factory=dict)
    routing: dict = field(default_factory=dict)
    work_order: dict = field(default_factory=dict)


class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def process(self, context: PipelineContext, db=None) -> PipelineContext:
        pass

    def log(self, message: str):
        print(f"[{self.name}] {message}")
