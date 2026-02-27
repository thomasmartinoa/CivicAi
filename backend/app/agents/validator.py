from app.agents.base import BaseAgent, PipelineContext
from app.services.llm import llm_service


class ValidationAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="ValidationAgent")

    async def process(self, context: PipelineContext, db=None) -> PipelineContext:
        description = context.data.get("description", "")

        if not description or len(description.strip()) < 10:
            context.errors.append("Description too short or missing")
            context.status = "rejected"
            return context

        if not context.data.get("address") and not (context.data.get("latitude") and context.data.get("longitude")):
            context.errors.append("Location information missing")
            context.status = "rejected"
            return context

        try:
            result = await llm_service.validate_complaint(description)
            context.structured_complaint = result

            if not result.get("is_valid", False):
                context.errors.append(f"Not an infrastructure complaint: {result.get('rejection_reason', 'unknown')}")
                context.status = "rejected"
                return context

            context.data["what_happened"] = result.get("what_happened", "")
            context.data["severity_keywords"] = result.get("severity_keywords", [])
            context.status = "validated"
            self.log("Complaint validated as infrastructure-related")

        except Exception as e:
            self.log(f"LLM validation failed, proceeding with basic validation: {e}")
            context.status = "validated"

        return context
