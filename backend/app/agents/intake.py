from app.agents.base import BaseAgent, PipelineContext
from app.services.media import media_service
from app.services.geocoding import geocoding_service
from app.services.llm import llm_service


class IntakeAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="IntakeAgent")

    async def process(self, context: PipelineContext, db=None) -> PipelineContext:
        raw = context.raw_input
        description = raw.get("description", "")
        media_texts = []

        for media in raw.get("media_files", []):
            if media.get("media_type") == "voice":
                try:
                    text = await media_service.speech_to_text(media["file_path"])
                    media_texts.append(text)
                    media["extracted_text"] = text
                    self.log(f"Voice transcribed: {len(text)} chars")
                except Exception as e:
                    self.log(f"Speech-to-text failed: {e}")

            elif media.get("media_type") == "image":
                try:
                    text = await llm_service.analyze_image(media["file_path"])
                    if text and "No infrastructure issues" not in text:
                        media_texts.append(f"[Image analysis: {text}]")
                        media["extracted_text"] = text
                        self.log(f"Image analyzed: {text[:80]}...")
                except Exception as e:
                    self.log(f"Image analysis failed: {e}")

        full_description = description
        if media_texts:
            full_description += "\n\nVoice transcription: " + " ".join(media_texts)

        location_data = {}
        lat = raw.get("latitude")
        lon = raw.get("longitude")
        if lat and lon:
            location_data = await geocoding_service.reverse_geocode(lat, lon)

        context.data["description"] = full_description
        context.data["citizen_email"] = raw.get("citizen_email", "")
        context.data["citizen_phone"] = raw.get("citizen_phone", "")
        context.data["citizen_name"] = raw.get("citizen_name", "")
        context.data["latitude"] = lat
        context.data["longitude"] = lon
        context.data["address"] = raw.get("address") or location_data.get("address", "")
        context.data["ward"] = location_data.get("ward", "")
        context.data["block"] = location_data.get("block", "")
        context.data["district"] = location_data.get("district", "")
        context.data["state"] = location_data.get("state", "")
        context.data["media_files"] = raw.get("media_files", [])
        context.data["media_texts"] = media_texts
        context.data["intake_complete"] = True
        context.status = "intake_complete"
        self.log(f"Intake complete. Description length: {len(full_description)}")
        return context
