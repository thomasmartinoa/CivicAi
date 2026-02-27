from app.agents.base import BaseAgent, PipelineContext
from app.services.llm import llm_service


class RiskAssessorAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="RiskAssessorAgent")

    async def process(self, context: PipelineContext, db=None) -> PipelineContext:
        description = context.data.get("description", "")
        category = context.data.get("category", "UNKNOWN")
        media_text = " ".join(context.data.get("media_texts", []))

        try:
            result = await llm_service.assess_risk(description, category, media_text)
            context.risk_assessment = result
            context.data["priority_score"] = result.get("priority_score", 50)
            context.data["risk_level"] = result.get("risk_level", "medium")
            context.status = "prioritized"
            self.log(f"Risk: {result.get('risk_level')} | Score: {result.get('priority_score')}")
        except Exception as e:
            context.data["priority_score"] = self._default_score(category)
            context.data["risk_level"] = self._score_to_level(context.data["priority_score"])
            context.status = "prioritized"
            self.log(f"LLM risk assessment failed, using defaults: {e}")

        return context

    def _default_score(self, category: str) -> int:
        defaults = {
            "FIRE_HAZARD": 85, "FLOODING": 80, "ELECTRICITY": 75, "SEWAGE": 70,
            "WATER": 65, "ROADS": 60, "HEALTH": 60, "STRAY_ANIMALS": 55,
            "CONSTRUCTION": 50, "SANITATION": 45, "PUBLIC_SPACES": 35, "EDUCATION": 40,
        }
        return defaults.get(category, 50)

    def _score_to_level(self, score: int) -> str:
        if score >= 76: return "critical"
        if score >= 51: return "high"
        if score >= 26: return "medium"
        return "low"
