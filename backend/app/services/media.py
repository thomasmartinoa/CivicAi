import os
import uuid
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import UploadFile

from app.config import settings


class MediaService:
    def __init__(self):
        self.upload_dir = Path(settings.upload_dir)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    async def save_file(self, file: UploadFile, complaint_id: str) -> dict:
        ext = Path(file.filename).suffix if file.filename else ""
        filename = f"{complaint_id}_{uuid.uuid4().hex[:8]}{ext}"
        file_path = self.upload_dir / filename

        async with aiofiles.open(file_path, "wb") as f:
            content = await file.read()
            await f.write(content)

        media_type = self._detect_media_type(ext)
        # Use forward slashes for URL compatibility
        relative_path = f"uploads/{filename}"
        return {
            "file_path": relative_path,
            "media_type": media_type,
            "original_filename": file.filename,
        }

    async def speech_to_text(self, file_path: str) -> str:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        with open(file_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1", file=audio_file,
            )
        return transcript.text

    def _detect_media_type(self, ext: str) -> str:
        ext = ext.lower()
        if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            return "image"
        elif ext in (".mp4", ".avi", ".mov", ".webm"):
            return "video"
        elif ext in (".mp3", ".wav", ".ogg", ".m4a"):
            return "voice"
        return "unknown"


media_service = MediaService()
