from app.agents.base import BaseAgent, PipelineContext
from app.agents.pipeline import ComplaintPipeline
from app.agents.intake import IntakeAgent
from app.agents.validator import ValidationAgent
from app.agents.classifier import ClassificationAgent
from app.agents.risk_assessor import RiskAssessorAgent
from app.agents.router import RoutingAgent
from app.agents.work_order import WorkOrderAgent
from app.agents.tracker import TrackingAgent


def create_pipeline() -> ComplaintPipeline:
    pipeline = ComplaintPipeline()
    pipeline.add_agent(IntakeAgent())
    pipeline.add_agent(ValidationAgent())
    pipeline.add_agent(ClassificationAgent())
    pipeline.add_agent(RiskAssessorAgent())
    pipeline.add_agent(RoutingAgent())
    pipeline.add_agent(WorkOrderAgent())
    pipeline.add_agent(TrackingAgent())
    return pipeline
