from pathlib import Path

import pytest

from app.services import media as media_module
from app.services.media import (
    MAX_UPLOAD_BYTES, MediaTooLarge, MediaTypeNotAllowed, store_upload,
)


@pytest.fixture(autouse=True)
def upload_root(tmp_path, monkeypatch):
    """Redirect storage into tmp_path.

    The real UPLOAD_ROOT resolves to backend/uploads, inside the repository, so
    writing there would litter the working tree — and a failing test would leave
    the files behind. store_upload reads the module global at call time, so
    patching it is enough.
    """
    monkeypatch.setattr(media_module, "UPLOAD_ROOT", tmp_path)
    return tmp_path


def test_a_stored_file_lands_under_the_upload_root(upload_root):
    stored = store_upload(b"fake-jpeg-bytes", "photo.jpg")
    assert (upload_root / Path(stored.file_path).name).exists()


def test_the_stored_name_is_generated_not_client_supplied(upload_root):
    """A client filename must never become a path component. Phase 1b's vision
    adapter contains against traversal, but that must not be the only defence."""
    stored = store_upload(b"x", "../../etc/passwd.jpg")
    assert "etc" not in stored.file_path
    assert ".." not in stored.file_path
    assert stored.original_filename == "../../etc/passwd.jpg"
    assert list(upload_root.iterdir()), "nothing was written"


def test_the_stored_path_is_relative_and_prefixed(upload_root):
    stored = store_upload(b"x", "photo.jpg")
    assert stored.file_path.startswith("uploads/")
    assert not Path(stored.file_path).is_absolute()


@pytest.mark.parametrize("extension,expected", [
    ("jpg", "image"), ("jpeg", "image"), ("png", "image"), ("webp", "image"),
    ("mp3", "voice"), ("wav", "voice"), ("m4a", "voice"), ("ogg", "voice"),
])
def test_extension_determines_media_type(upload_root, extension, expected):
    assert store_upload(b"x", f"f.{extension}").media_type == expected


def test_a_disallowed_type_is_rejected_before_anything_is_written(upload_root):
    with pytest.raises(MediaTypeNotAllowed, match="exe"):
        store_upload(b"MZ", "payload.exe")
    assert list(upload_root.iterdir()) == [], "a rejected upload still wrote something"


def test_an_extensionless_upload_is_rejected(upload_root):
    with pytest.raises(MediaTypeNotAllowed):
        store_upload(b"x", "noextension")
    assert list(upload_root.iterdir()) == []


def test_an_oversized_upload_is_rejected_before_anything_is_written(upload_root):
    with pytest.raises(MediaTooLarge):
        store_upload(b"x" * (MAX_UPLOAD_BYTES + 1), "big.jpg")
    assert list(upload_root.iterdir()) == []


def test_two_uploads_of_the_same_name_do_not_collide(upload_root):
    a = store_upload(b"one", "photo.jpg")
    b = store_upload(b"two", "photo.jpg")
    assert a.file_path != b.file_path
    assert len(list(upload_root.iterdir())) == 2
