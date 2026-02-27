from typing import Optional

from app.config import settings

INFRASTRUCTURE_CATEGORIES = [
    "ROADS", "ELECTRICITY", "WATER", "SANITATION", "PUBLIC_SPACES",
    "EDUCATION", "HEALTH", "FLOODING", "FIRE_HAZARD", "CONSTRUCTION",
    "STRAY_ANIMALS", "SEWAGE",
]


class LLMService:
    def __init__(self, provider: Optional[str] = None):
        self.provider = provider or settings.llm_provider

    async def classify_complaint(self, description: str, media_text: str = "") -> dict:
        prompt = self.build_classification_prompt(description, media_text)
        if self.provider == "anthropic":
            return await self._call_anthropic(prompt, system="You are an infrastructure complaint classifier. Respond with JSON only.")
        else:
            return await self._call_openai(prompt, system="You are an infrastructure complaint classifier. Respond with JSON only.")

    async def validate_complaint(self, description: str) -> dict:
        prompt = f"""Analyze this complaint and determine:
1. Is this an infrastructure-related complaint? (true/false)
2. Extract: what_happened, where, when (if mentioned), severity_keywords
3. If not infrastructure-related, explain why.

Complaint: "{description}"

Respond in JSON: {{"is_valid": bool, "what_happened": str, "where": str, "when": str, "severity_keywords": [str], "rejection_reason": str|null}}"""

        if self.provider == "anthropic":
            return await self._call_anthropic(prompt, system="You are an infrastructure complaint validator. Respond with JSON only.")
        else:
            return await self._call_openai(prompt, system="You are an infrastructure complaint validator. Respond with JSON only.")

    async def assess_risk(self, description: str, category: str, media_text: str = "") -> dict:
        prompt = f"""Assess the risk and priority of this infrastructure complaint:

Category: {category}
Description: "{description}"
Additional media context: "{media_text}"

Score on these factors (each 0-25, total 0-100):
1. Category severity (life-threatening categories score higher)
2. Population impact (how many people affected)
3. Safety risk (immediate danger level)
4. Urgency (time-sensitive nature)

Determine risk_level: critical (76-100), high (51-75), medium (26-50), low (0-25)

Respond in JSON: {{"priority_score": int, "risk_level": str, "category_severity": int, "population_impact": int, "safety_risk": int, "urgency": int, "reasoning": str}}"""

        if self.provider == "anthropic":
            return await self._call_anthropic(prompt, system="You are an infrastructure risk assessor. Respond with JSON only.")
        else:
            return await self._call_openai(prompt, system="You are an infrastructure risk assessor. Respond with JSON only.")

    def build_classification_prompt(self, description: str, media_text: str = "") -> str:
        categories_str = ", ".join(INFRASTRUCTURE_CATEGORIES)
        return f"""Classify this infrastructure complaint into one of these categories: {categories_str}

Complaint: "{description}"
Additional media context: "{media_text}"

Respond in JSON: {{"category": str, "subcategory": str, "confidence": float (0-1), "reasoning": str}}"""

    async def _call_anthropic(self, prompt: str, system: str = "") -> dict:
        import json
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(text[start:end])
            raise

    async def _call_openai(self, prompt: str, system: str = "") -> dict:
        import json
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)


llm_service = LLMService()
