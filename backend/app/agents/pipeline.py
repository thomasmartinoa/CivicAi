from typing import Optional
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent, PipelineContext


class ComplaintPipeline:
    def __init__(self):
        self.agents: list[BaseAgent] = []

    def add_agent(self, agent: BaseAgent):
        self.agents.append(agent)

    async def run(self, context: PipelineContext, db: Optional[Session] = None) -> PipelineContext:
        for agent in self.agents:
            try:
                agent.log(f"Processing complaint {context.complaint_id}")
                context = await agent.process(context, db)
                if context.errors:
                    agent.log(f"Errors: {context.errors}")
                    break
            except Exception as e:
                context.errors.append(f"{agent.name}: {str(e)}")
                agent.log(f"Failed: {e}")
                break
        return context
