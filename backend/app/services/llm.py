import json
from typing import Optional

from app.config import settings

INFRASTRUCTURE_CATEGORIES = [
    "ROADS", "ELECTRICITY", "WATER", "SANITATION", "PUBLIC_SPACES",
    "EDUCATION", "HEALTH", "FLOODING", "FIRE_HAZARD", "CONSTRUCTION",
    "STRAY_ANIMALS", "SEWAGE",
]

# Keyword-based fallback — no API key required
_KEYWORD_MAP: list[tuple[str, list[str]]] = [
    ("ROADS", ["road", "pothole", "street", "highway", "pavement", "footpath", "divider", "crack", "tar", "asphalt", "traffic"]),
    ("ELECTRICITY", ["electricity", "electric", "power", "light", "streetlight", "wire", "transformer", "outage", "voltage", "bulb", "pole"]),
    ("WATER", ["water", "pipe", "supply", "leakage", "leak", "contamination", "drinking", "tap", "borewell", "drainage"]),
    ("SEWAGE", ["sewage", "sewer", "manhole", "drain overflow", "septic", "gutter", "blockage", "overflow"]),
    ("SANITATION", ["garbage", "waste", "trash", "dustbin", "bin", "litter", "sanitation", "cleaning", "sweep"]),
    ("FLOODING", ["flood", "waterlog", "waterlogging", "inundation", "drain", "stagnant water", "rain water"]),
    ("FIRE_HAZARD", ["fire", "gas leak", "smoke", "burning", "spark", "hazard", "flammable", "explosion"]),
    ("HEALTH", ["hospital", "ambulance", "clinic", "health", "medical", "medicine", "patient", "doctor"]),
    ("PUBLIC_SPACES", ["park", "tree", "garden", "bench", "playground", "footpath", "public", "fallen tree"]),
    ("EDUCATION", ["school", "college", "education", "classroom", "student", "toilet", "restroom", "building"]),
    ("CONSTRUCTION", ["construction", "illegal", "excavation", "digging", "building", "demolish", "encroach"]),
    ("STRAY_ANIMALS", ["dog", "stray", "animal", "cattle", "cow", "buffalo", "horse", "bite", "aggressive"]),
]

_RISK_DEFAULTS: dict[str, tuple[int, str]] = {
    "FIRE_HAZARD": (88, "critical"),
    "FLOODING": (80, "critical"),
    "ELECTRICITY": (75, "high"),
    "SEWAGE": (70, "high"),
    "WATER": (65, "high"),
    "HEALTH": (65, "high"),
    "ROADS": (60, "high"),
    "STRAY_ANIMALS": (55, "medium"),
    "CONSTRUCTION": (50, "medium"),
    "SANITATION": (45, "medium"),
    "EDUCATION": (40, "medium"),
    "PUBLIC_SPACES": (35, "low"),
}


def _keyword_classify(description: str) -> dict:
    text = description.lower()
    best_cat, best_score = "ROADS", 0
    for category, keywords in _KEYWORD_MAP:
        score = sum(1 for kw in keywords if kw in text)
        if score > best_score:
            best_score, best_cat = score, category
    confidence = min(0.5 + best_score * 0.1, 0.9) if best_score > 0 else 0.4
    return {"category": best_cat, "subcategory": best_cat.replace("_", " ").title(),
            "confidence": confidence, "reasoning": "Keyword fallback"}


def _keyword_risk(category: str) -> dict:
    score, level = _RISK_DEFAULTS.get(category, (50, "medium"))
    return {"priority_score": score, "risk_level": level, "reasoning": "Default risk by category"}


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM response text."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
        raise


def _has_api_key(provider: str) -> bool:
    if provider == "gemini":
        return bool(settings.gemini_api_key)
    elif provider == "anthropic":
        return bool(settings.anthropic_api_key)
    elif provider == "openai":
        return bool(settings.openai_api_key)
    return False


class LLMService:
    def __init__(self, provider: Optional[str] = None):
        self.provider = provider or settings.llm_provider

    async def classify_complaint(self, description: str, media_text: str = "") -> dict:
        if not _has_api_key(self.provider):
            return _keyword_classify(description + " " + media_text)
        prompt = self.build_classification_prompt(description, media_text)
        system = "You are an infrastructure complaint classifier. Respond with JSON only."
        try:
            return await self._call(prompt, system)
        except Exception:
            return _keyword_classify(description + " " + media_text)

    async def analyze_image(self, image_path: str) -> str:
        """Analyze an image and return a text description of infrastructure issues visible."""
        import base64
        try:
            with open(image_path, "rb") as f:
                raw_bytes = f.read()
            ext = image_path.lower().split(".")[-1]
            mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                        "gif": "image/gif", "webp": "image/webp"}
            mime = mime_map.get(ext, "image/jpeg")
            image_b64 = base64.b64encode(raw_bytes).decode("utf-8")

            if self.provider == "gemini":
                return await self._analyze_image_gemini(raw_bytes, mime)
            elif self.provider == "anthropic":
                return await self._analyze_image_anthropic(image_b64, mime)
            else:
                return await self._analyze_image_openai(image_b64, mime)
        except Exception as e:
            return f"[Image analysis failed: {e}]"

    async def _analyze_image_gemini(self, raw_bytes: bytes, mime: str) -> str:
        import asyncio
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.gemini_api_key)
        prompt = "Describe any infrastructure problems visible in this image. Be specific about damage, hazards, or issues that would require government action. If no infrastructure issues, say 'No infrastructure issues visible'."

        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash-lite",
            contents=[
                types.Part.from_bytes(data=raw_bytes, mime_type=mime),
                prompt,
            ],
        )
        return response.text or ""

    async def _analyze_image_anthropic(self, image_data: str, mime: str) -> str:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": image_data}},
                {"type": "text", "text": "Describe any infrastructure problems visible in this image."},
            ]}],
        )
        return response.content[0].text

    async def _analyze_image_openai(self, image_data: str, mime: str) -> str:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_data}"}},
                {"type": "text", "text": "Describe any infrastructure problems visible in this image."},
            ]}],
            max_tokens=512,
        )
        return response.choices[0].message.content or ""

    async def validate_complaint(self, description: str) -> dict:
        if not _has_api_key(self.provider):
            is_valid = len(description.strip()) >= 10
            return {"is_valid": is_valid, "what_happened": description, "where": "",
                    "when": "", "severity_keywords": [], "rejection_reason": None if is_valid else "Too short"}
        prompt = f"""Analyze this complaint and determine:
1. Is this an infrastructure-related complaint? (true/false)
2. Extract: what_happened, where, when (if mentioned), severity_keywords
3. If not infrastructure-related, explain why.

Complaint: "{description}"

Respond in JSON: {{"is_valid": bool, "what_happened": str, "where": str, "when": str, "severity_keywords": [str], "rejection_reason": str|null}}"""
        system = "You are an infrastructure complaint validator. Respond with JSON only."
        try:
            return await self._call(prompt, system)
        except Exception:
            is_valid = len(description.strip()) >= 10
            return {"is_valid": is_valid, "what_happened": description, "where": "",
                    "when": "", "severity_keywords": [], "rejection_reason": None if is_valid else "Too short"}

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
        system = "You are an infrastructure risk assessor. Respond with JSON only."
        if not _has_api_key(self.provider):
            return _keyword_risk(category)
        try:
            return await self._call(prompt, system)
        except Exception:
            return _keyword_risk(category)

    async def generate_email_draft(self, complaint_data: dict) -> str:
        """Generate a formal email draft to the concerned department about a complaint."""
        tracking_id = complaint_data.get("tracking_id", "N/A")
        category = complaint_data.get("category", "General")
        department = complaint_data.get("department_name", "Concerned Department")
        description = complaint_data.get("description", "")
        risk_level = complaint_data.get("risk_level", "medium")
        priority_score = complaint_data.get("priority_score", "N/A")
        address = complaint_data.get("address", "Not specified")
        ward = complaint_data.get("ward", "")
        district = complaint_data.get("district", "")
        state = complaint_data.get("state", "")
        citizen_name = complaint_data.get("citizen_name", "A citizen")
        sla_deadline = complaint_data.get("sla_deadline", "")

        location_parts = [p for p in [address, ward, district, state] if p]
        location_str = ", ".join(location_parts) if location_parts else "Not specified"

        if _has_api_key(self.provider):
            prompt = f"""Draft a formal government email to the {department} regarding an infrastructure complaint.

Complaint Details:
- Tracking ID: {tracking_id}
- Category: {category}
- Risk Level: {risk_level} (Priority Score: {priority_score}/100)
- Description: {description}
- Location: {location_str}
- Reported by: {citizen_name}
- SLA Deadline: {sla_deadline or 'Not set'}

Write a professional, concise email that:
1. Has a clear subject line
2. States the issue and its urgency
3. Provides the location and details
4. Requests immediate action based on risk level
5. Mentions the SLA deadline if available

Return ONLY the email text, no JSON wrapping. Include Subject:, To:, and Body sections."""

            try:
                if self.provider == "gemini":
                    import asyncio
                    from google import genai
                    client = genai.Client(api_key=settings.gemini_api_key)
                    response = await asyncio.to_thread(
                        client.models.generate_content,
                        model="gemini-2.5-flash-lite",
                        contents=prompt,
                    )
                    return response.text or self._fallback_email(complaint_data)
                elif self.provider == "anthropic":
                    import anthropic
                    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
                    response = await client.messages.create(
                        model="claude-sonnet-4-20250514", max_tokens=1024,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    return response.content[0].text
                else:
                    from openai import AsyncOpenAI
                    client = AsyncOpenAI(api_key=settings.openai_api_key)
                    response = await client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[{"role": "user", "content": prompt}],
                    )
                    return response.choices[0].message.content or self._fallback_email(complaint_data)
            except Exception:
                return self._fallback_email(complaint_data)
        else:
            return self._fallback_email(complaint_data)

    def _fallback_email(self, data: dict) -> str:
        tracking_id = data.get("tracking_id", "N/A")
        category = data.get("category", "General")
        department = data.get("department_name", "Concerned Department")
        description = data.get("description", "")
        risk_level = data.get("risk_level", "medium")
        address = data.get("address", "Not specified")
        district = data.get("district", "")
        state = data.get("state", "")
        citizen_name = data.get("citizen_name", "A citizen")
        sla_deadline = data.get("sla_deadline", "")

        location_parts = [p for p in [address, district, state] if p]
        location_str = ", ".join(location_parts) if location_parts else "Not specified"

        urgency = "URGENT: " if risk_level in ("critical", "high") else ""

        return f"""Subject: {urgency}Infrastructure Complaint [{tracking_id}] - {category}

To: {department}

Dear Sir/Madam,

This is to bring to your attention an infrastructure complaint that has been registered on the CivicAI platform and requires your department's immediate attention.

Complaint Reference: {tracking_id}
Category: {category}
Risk Level: {risk_level.upper()}
{f"SLA Deadline: {sla_deadline}" if sla_deadline else ""}

Issue Description:
{description}

Location: {location_str}

Reported By: {citizen_name}

We request your department to kindly look into this matter and take necessary action at the earliest. {f"Given the {risk_level} risk level, this matter requires priority attention." if risk_level in ("critical", "high") else ""}

Please update the status of this complaint on the CivicAI platform once action has been initiated.

Regards,
CivicAI - Infrastructure Resolution System"""

    def build_classification_prompt(self, description: str, media_text: str = "") -> str:
        categories_str = ", ".join(INFRASTRUCTURE_CATEGORIES)
        return f"""Classify this infrastructure complaint into one of these categories: {categories_str}

Complaint: "{description}"
Additional media context: "{media_text}"

Respond in JSON: {{"category": str, "subcategory": str, "confidence": float (0-1), "reasoning": str}}"""

    async def _call(self, prompt: str, system: str = "") -> dict:
        if not _has_api_key(self.provider):
            raise RuntimeError(f"No API key configured for provider '{self.provider}'")
        if self.provider == "gemini":
            return await self._call_gemini(prompt, system)
        elif self.provider == "anthropic":
            return await self._call_anthropic(prompt, system)
        else:
            return await self._call_openai(prompt, system)

    async def _call_gemini(self, prompt: str, system: str = "") -> dict:
        import asyncio
        from google import genai

        client = genai.Client(api_key=settings.gemini_api_key)

        full_prompt = f"{system}\n\n{prompt}" if system else prompt

        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash-lite",
            contents=full_prompt,
        )
        return _extract_json(response.text)

    async def _call_anthropic(self, prompt: str, system: str = "") -> dict:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return _extract_json(response.content[0].text)

    async def _call_openai(self, prompt: str, system: str = "") -> dict:
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
