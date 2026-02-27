from app.agents.base import BaseAgent, PipelineContext
from app.services.llm import llm_service

CONFIDENCE_THRESHOLD = 0.7


class ClassificationAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="ClassificationAgent")

    async def process(self, context: PipelineContext) -> PipelineContext:
        description = context.data.get("description", "")
        media_text = " ".join(context.data.get("media_texts", []))

        try:
            result = await llm_service.classify_complaint(description, media_text)
            context.classification = result
            context.data["category"] = result.get("category", "UNKNOWN")
            context.data["subcategory"] = result.get("subcategory", "")
            context.data["classification_confidence"] = result.get("confidence", 0.0)

            if result.get("confidence", 0) < CONFIDENCE_THRESHOLD:
                context.data["needs_human_review"] = True
                self.log(f"Low confidence ({result.get('confidence')}), flagged for human review")

            context.status = "classified"
            self.log(f"Classified as {result.get('category')} / {result.get('subcategory')}")

        except Exception as e:
            context.errors.append(f"Classification failed: {str(e)}")
            self.log(f"Classification failed: {e}")

        return context
