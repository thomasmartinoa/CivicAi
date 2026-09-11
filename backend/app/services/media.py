"""Upload storage.

Files are stored under a generated name. A client-supplied filename is kept only
as a display label and never becomes a path component — the vision adapter in
`app/ai/graph/runner.py` also contains against traversal, but defence there must
not be the only defence.
"""

import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

UPLOAD_ROOT = Path(settings.upload_dir).resolve()
MAX_UPLOAD_BYTES = 8 * 1024 * 1024

# Extension -> media_type. An extension absent from this map is rejected before
# anything is written to disk.
ALLOWED_MEDIA: dict[str, str] = {
    "jpg": "image", "jpeg": "image", "png": "image", "webp": "image",
    "mp3": "voice", "wav": "voice", "m4a": "voice", "ogg": "voice",
}


class MediaTooLarge(ValueError):
    pass


class MediaTypeNotAllowed(ValueError):
    pass


@dataclass(frozen=True)
class StoredMedia:
    file_path: str
    media_type: str
    original_filename: str


def store_upload(data: bytes, original_filename: str) -> StoredMedia:
    """Validate, then write under a generated name. Rejects before writing."""
    extension = Path(original_filename).suffix.lstrip(".").lower()
    if extension not in ALLOWED_MEDIA:
        raise MediaTypeNotAllowed(
            f"{extension or original_filename!r} is not an accepted upload type; "
            f"accepted: {sorted(set(ALLOWED_MEDIA))}"
        )
    if len(data) > MAX_UPLOAD_BYTES:
        raise MediaTooLarge(f"{len(data)} bytes exceeds the {MAX_UPLOAD_BYTES} byte limit")

    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{extension}"
    (UPLOAD_ROOT / name).write_bytes(data)
    return StoredMedia(
        file_path=f"uploads/{name}",
        media_type=ALLOWED_MEDIA[extension],
        original_filename=original_filename,
    )
