#!/usr/bin/env python3
"""
Tests for photo upload endpoints:
  POST /api/generate      — upload photo + name + text → card
  POST /api/upload-library — upload photo to library
  GET  /api/library       — list library photos
  POST /api/delete-library — delete photo from library
  POST /api/rename-library — rename photo in library

Uses FastAPI TestClient with mocked CardGenerator to avoid Playwright.
"""

import io
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# We need to mock heavy imports BEFORE importing web_app, because web_app
# eagerly creates a CardGenerator at module level and imports telegram, etc.
# ---------------------------------------------------------------------------

# Create a tiny valid JPEG in memory for test uploads
def _make_test_jpeg(width=100, height=100) -> bytes:
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)
    return buf.read()


def _make_test_png(width=100, height=100) -> bytes:
    img = Image.new("RGB", (width, height), color=(0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path, monkeypatch):
    """Redirect PHOTOS, CARDS, UPLOADS to temp directories so tests are isolated."""
    photos = tmp_path / "photos"
    cards = tmp_path / "cards"
    uploads = tmp_path / "uploads"
    photos.mkdir()
    cards.mkdir()
    uploads.mkdir()

    import web_app
    monkeypatch.setattr(web_app, "PHOTOS", photos)
    monkeypatch.setattr(web_app, "CARDS", cards)
    monkeypatch.setattr(web_app, "UPLOADS", uploads)

    # Clear history between tests
    web_app.history.clear()

    yield {"photos": photos, "cards": cards, "uploads": uploads}


@pytest.fixture(autouse=True)
def mock_generator(monkeypatch):
    """Mock CardGenerator.generate to just create a dummy JPEG file."""
    import web_app

    def fake_generate(self, photo_path, name, text, output_path):
        # Write a tiny valid JPEG to output_path so the endpoint succeeds
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(_make_test_jpeg(50, 50))
        return output_path

    monkeypatch.setattr(web_app.generator, "generate", fake_generate.__get__(web_app.generator))
    yield


@pytest.fixture(autouse=True)
def mock_git(monkeypatch):
    """Mock _git_commit_and_push so tests don't touch git."""
    import web_app
    monkeypatch.setattr(web_app, "_git_commit_and_push", lambda *a, **kw: False)
    yield


@pytest.fixture()
def client():
    """FastAPI TestClient."""
    from fastapi.testclient import TestClient
    import web_app
    return TestClient(web_app.app, raise_server_exceptions=False)


# ===========================================================================
# POST /api/generate — photo upload
# ===========================================================================
class TestApiGenerate:
    """Tests for POST /api/generate with photo upload."""

    def test_generate_with_uploaded_photo(self, client, isolated_dirs):
        """Photo upload saves to photos/ and returns a card URL."""
        jpeg_bytes = _make_test_jpeg()
        resp = client.post(
            "/api/generate",
            data={"name": "Test Person", "text": "Some news text"},
            files={"photo": ("portrait.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "card_url" in body
        assert body["card_url"].startswith("/cards/")
        assert body["card_url"].endswith("_card.jpg")

        # Photo should be saved in the photos/ library folder
        saved = list(isolated_dirs["photos"].iterdir())
        assert len(saved) == 1
        assert saved[0].name.startswith("Test_Person")

    def test_generate_photo_persists_in_library(self, client, isolated_dirs):
        """After /api/generate, the uploaded photo should appear in /api/library."""
        jpeg_bytes = _make_test_jpeg()
        client.post(
            "/api/generate",
            data={"name": "LibCheck", "text": "Text"},
            files={"photo": ("face.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
        )
        lib_resp = client.get("/api/library")
        assert lib_resp.status_code == 200
        photos = lib_resp.json()
        names = [p["name"] for p in photos]
        assert any("LibCheck" in n for n in names)

    def test_generate_with_library_photo(self, client, isolated_dirs):
        """Using lib_photo parameter with an existing library image."""
        # Pre-place a photo in the library
        lib_img = isolated_dirs["photos"] / "existing.jpg"
        lib_img.write_bytes(_make_test_jpeg())

        resp = client.post(
            "/api/generate",
            data={
                "name": "Lib User",
                "text": "News from library",
                "lib_photo": "/photos/existing.jpg",
            },
        )
        assert resp.status_code == 200
        assert "card_url" in resp.json()

    def test_generate_with_missing_library_photo(self, client):
        """Using lib_photo that doesn't exist returns 400."""
        resp = client.post(
            "/api/generate",
            data={
                "name": "Nobody",
                "text": "Text",
                "lib_photo": "/photos/nonexistent.jpg",
            },
        )
        assert resp.status_code == 400
        assert "not found" in resp.json()["error"].lower()

    def test_generate_no_photo_returns_400(self, client):
        """Neither photo upload nor lib_photo → 400."""
        resp = client.post(
            "/api/generate",
            data={"name": "Nophoto", "text": "Text"},
        )
        assert resp.status_code == 400
        assert "no photo" in resp.json()["error"].lower()

    def test_generate_duplicate_name_gets_suffix(self, client, isolated_dirs):
        """Uploading two photos with the same name should not overwrite."""
        jpeg1 = _make_test_jpeg(80, 80)
        jpeg2 = _make_test_jpeg(90, 90)

        client.post(
            "/api/generate",
            data={"name": "Duplicate", "text": "First"},
            files={"photo": ("pic.jpg", io.BytesIO(jpeg1), "image/jpeg")},
        )
        client.post(
            "/api/generate",
            data={"name": "Duplicate", "text": "Second"},
            files={"photo": ("pic.jpg", io.BytesIO(jpeg2), "image/jpeg")},
        )

        saved = sorted(isolated_dirs["photos"].iterdir())
        assert len(saved) == 2
        names = [f.stem for f in saved]
        # First should be "Duplicate", second "Duplicate_1"
        assert "Duplicate" in names
        assert "Duplicate_1" in names

    def test_generate_special_chars_in_name(self, client, isolated_dirs):
        """Filesystem-unsafe chars in name are stripped."""
        jpeg_bytes = _make_test_jpeg()
        resp = client.post(
            "/api/generate",
            data={"name": 'He<llo>:W"orld', "text": "Text"},
            files={"photo": ("test.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
        )
        assert resp.status_code == 200
        saved = list(isolated_dirs["photos"].iterdir())
        assert len(saved) == 1
        # Unsafe chars should be removed
        assert "<" not in saved[0].name
        assert ">" not in saved[0].name
        assert ":" not in saved[0].name
        assert '"' not in saved[0].name

    def test_generate_georgian_name_preserved(self, client, isolated_dirs):
        """Georgian Unicode characters in name should be preserved."""
        jpeg_bytes = _make_test_jpeg()
        resp = client.post(
            "/api/generate",
            data={"name": "გიორგი", "text": "ტექსტი"},
            files={"photo": ("geo.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
        )
        assert resp.status_code == 200
        saved = list(isolated_dirs["photos"].iterdir())
        assert len(saved) == 1
        assert "გიორგი" in saved[0].name

    def test_generate_adds_to_history(self, client):
        """Successful generation should add an entry to history."""
        import web_app
        jpeg_bytes = _make_test_jpeg()
        client.post(
            "/api/generate",
            data={"name": "HistTest", "text": "Text"},
            files={"photo": ("h.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
        )
        resp = client.get("/api/history")
        assert resp.status_code == 200
        hist = resp.json()
        assert len(hist) == 1
        assert hist[0]["name"] == "HistTest"

    def test_generate_preserves_png_extension(self, client, isolated_dirs):
        """Uploading a .png should keep the .png extension."""
        png_bytes = _make_test_png()
        resp = client.post(
            "/api/generate",
            data={"name": "PngTest", "text": "Text"},
            files={"photo": ("image.png", io.BytesIO(png_bytes), "image/png")},
        )
        assert resp.status_code == 200
        saved = list(isolated_dirs["photos"].iterdir())
        assert len(saved) == 1
        assert saved[0].suffix == ".png"

    def test_generate_empty_name_uses_fallback(self, client, isolated_dirs):
        """Empty/whitespace-only name should use fallback person_<id>."""
        jpeg_bytes = _make_test_jpeg()
        resp = client.post(
            "/api/generate",
            data={"name": "   ", "text": "Text"},
            files={"photo": ("x.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
        )
        assert resp.status_code == 200
        saved = list(isolated_dirs["photos"].iterdir())
        assert len(saved) == 1
        assert saved[0].stem.startswith("person_")


# ===========================================================================
# POST /api/upload-library
# ===========================================================================
class TestApiUploadLibrary:
    """Tests for POST /api/upload-library."""

    def test_upload_to_library(self, client, isolated_dirs):
        """Basic upload saves file and returns metadata."""
        jpeg_bytes = _make_test_jpeg()
        resp = client.post(
            "/api/upload-library",
            files={"photo": ("myphoto.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["name"] == "myphoto"
        assert body["url"] == "/photos/myphoto.jpg"

        # File should exist on disk
        assert (isolated_dirs["photos"] / "myphoto.jpg").exists()

    def test_upload_duplicate_gets_suffix(self, client, isolated_dirs):
        """Uploading the same filename twice should auto-increment."""
        jpeg1 = _make_test_jpeg(80, 80)
        jpeg2 = _make_test_jpeg(90, 90)

        resp1 = client.post(
            "/api/upload-library",
            files={"photo": ("dup.jpg", io.BytesIO(jpeg1), "image/jpeg")},
        )
        resp2 = client.post(
            "/api/upload-library",
            files={"photo": ("dup.jpg", io.BytesIO(jpeg2), "image/jpeg")},
        )

        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["name"] == "dup"
        assert resp2.json()["name"] == "dup_1"

        saved = sorted(isolated_dirs["photos"].iterdir())
        assert len(saved) == 2

    def test_upload_spaces_replaced_with_underscores(self, client, isolated_dirs):
        """Spaces in filename are replaced with underscores."""
        jpeg_bytes = _make_test_jpeg()
        resp = client.post(
            "/api/upload-library",
            files={"photo": ("my photo.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
        )
        assert resp.status_code == 200
        assert " " not in resp.json()["url"]
        saved = list(isolated_dirs["photos"].iterdir())
        assert " " not in saved[0].name

    def test_upload_special_chars_stripped(self, client, isolated_dirs):
        """Filesystem-unsafe characters removed from filename."""
        jpeg_bytes = _make_test_jpeg()
        resp = client.post(
            "/api/upload-library",
            files={"photo": ('bad<>:"/|?*.jpg', io.BytesIO(jpeg_bytes), "image/jpeg")},
        )
        assert resp.status_code == 200
        saved = list(isolated_dirs["photos"].iterdir())
        assert len(saved) == 1
        for ch in '<>:"/\\|?*':
            assert ch not in saved[0].name

    def test_upload_png_preserved(self, client, isolated_dirs):
        """PNG files keep their extension."""
        png_bytes = _make_test_png()
        resp = client.post(
            "/api/upload-library",
            files={"photo": ("pic.png", io.BytesIO(png_bytes), "image/png")},
        )
        assert resp.status_code == 200
        assert resp.json()["url"].endswith(".png")

    def test_upload_georgian_filename(self, client, isolated_dirs):
        """Georgian Unicode in filename should be preserved."""
        jpeg_bytes = _make_test_jpeg()
        resp = client.post(
            "/api/upload-library",
            files={"photo": ("ფოტო.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "ფოტო" in body["name"]


# ===========================================================================
# GET /api/library
# ===========================================================================
class TestApiLibrary:
    """Tests for GET /api/library."""

    def test_library_empty(self, client, isolated_dirs):
        """Empty photos/ returns empty list."""
        resp = client.get("/api/library")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_library_lists_photos(self, client, isolated_dirs):
        """Pre-placed photos appear in library listing."""
        (isolated_dirs["photos"] / "alice.jpg").write_bytes(_make_test_jpeg())
        (isolated_dirs["photos"] / "bob.png").write_bytes(_make_test_png())

        resp = client.get("/api/library")
        assert resp.status_code == 200
        photos = resp.json()
        assert len(photos) == 2
        names = {p["name"] for p in photos}
        assert names == {"alice", "bob"}

    def test_library_sorted_by_name(self, client, isolated_dirs):
        """Library results are sorted alphabetically (case-insensitive)."""
        for name in ("Zara", "alice", "Bob"):
            (isolated_dirs["photos"] / f"{name}.jpg").write_bytes(_make_test_jpeg())

        resp = client.get("/api/library")
        photos = resp.json()
        names = [p["name"] for p in photos]
        assert names == ["alice", "Bob", "Zara"]

    def test_library_ignores_dotfiles(self, client, isolated_dirs):
        """Files starting with . should be excluded."""
        (isolated_dirs["photos"] / ".hidden.jpg").write_bytes(_make_test_jpeg())
        (isolated_dirs["photos"] / "visible.jpg").write_bytes(_make_test_jpeg())

        resp = client.get("/api/library")
        photos = resp.json()
        assert len(photos) == 1
        assert photos[0]["name"] == "visible"

    def test_library_includes_all_image_extensions(self, client, isolated_dirs):
        """jpg, jpeg, png, webp should all be listed."""
        for ext in ("jpg", "jpeg", "png", "webp"):
            (isolated_dirs["photos"] / f"img_{ext}.{ext}").write_bytes(_make_test_jpeg())

        resp = client.get("/api/library")
        photos = resp.json()
        assert len(photos) == 4

    def test_library_url_format(self, client, isolated_dirs):
        """Each photo entry has correct url format."""
        (isolated_dirs["photos"] / "test.jpg").write_bytes(_make_test_jpeg())

        resp = client.get("/api/library")
        photos = resp.json()
        assert photos[0]["url"] == "/photos/test.jpg"
        assert photos[0]["name"] == "test"

    def test_library_after_upload(self, client, isolated_dirs):
        """Photo uploaded via /api/upload-library shows up in /api/library."""
        jpeg_bytes = _make_test_jpeg()
        client.post(
            "/api/upload-library",
            files={"photo": ("newphoto.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
        )
        resp = client.get("/api/library")
        photos = resp.json()
        assert len(photos) == 1
        assert photos[0]["name"] == "newphoto"


# ===========================================================================
# POST /api/delete-library
# ===========================================================================
class TestApiDeleteLibrary:
    """Tests for POST /api/delete-library."""

    def test_delete_existing_photo(self, client, isolated_dirs):
        """Deleting an existing photo removes it from disk."""
        (isolated_dirs["photos"] / "todelete.jpg").write_bytes(_make_test_jpeg())

        resp = client.post("/api/delete-library", data={"photo_name": "todelete"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert not (isolated_dirs["photos"] / "todelete.jpg").exists()

    def test_delete_nonexistent_returns_404(self, client):
        """Deleting a photo that doesn't exist returns 404."""
        resp = client.post("/api/delete-library", data={"photo_name": "ghost"})
        assert resp.status_code == 404

    def test_delete_removes_from_library_listing(self, client, isolated_dirs):
        """After deletion, photo should not appear in /api/library."""
        (isolated_dirs["photos"] / "bye.jpg").write_bytes(_make_test_jpeg())

        # Verify it's listed
        lib = client.get("/api/library").json()
        assert any(p["name"] == "bye" for p in lib)

        # Delete
        client.post("/api/delete-library", data={"photo_name": "bye"})

        # Verify it's gone
        lib = client.get("/api/library").json()
        assert not any(p["name"] == "bye" for p in lib)


# ===========================================================================
# POST /api/rename-library
# ===========================================================================
class TestApiRenameLibrary:
    """Tests for POST /api/rename-library."""

    def test_rename_existing_photo(self, client, isolated_dirs):
        """Renaming a photo changes the file on disk."""
        (isolated_dirs["photos"] / "oldname.jpg").write_bytes(_make_test_jpeg())

        resp = client.post(
            "/api/rename-library",
            data={"old_name": "oldname", "new_name": "newname"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["name"] == "newname"
        assert body["url"] == "/photos/newname.jpg"

        assert not (isolated_dirs["photos"] / "oldname.jpg").exists()
        assert (isolated_dirs["photos"] / "newname.jpg").exists()

    def test_rename_nonexistent_returns_404(self, client):
        """Renaming a photo that doesn't exist returns 404."""
        resp = client.post(
            "/api/rename-library",
            data={"old_name": "nope", "new_name": "whatever"},
        )
        assert resp.status_code == 404

    def test_rename_to_empty_returns_400(self, client, isolated_dirs):
        """Renaming to an empty string returns 400."""
        (isolated_dirs["photos"] / "valid.jpg").write_bytes(_make_test_jpeg())
        resp = client.post(
            "/api/rename-library",
            data={"old_name": "valid", "new_name": "   "},
        )
        assert resp.status_code == 400

    def test_rename_duplicate_gets_suffix(self, client, isolated_dirs):
        """Renaming to an existing name should auto-increment."""
        (isolated_dirs["photos"] / "first.jpg").write_bytes(_make_test_jpeg())
        (isolated_dirs["photos"] / "target.jpg").write_bytes(_make_test_jpeg())

        resp = client.post(
            "/api/rename-library",
            data={"old_name": "first", "new_name": "target"},
        )
        assert resp.status_code == 200
        # Should become target_1 since target already exists
        assert resp.json()["name"] == "target_1"

    def test_rename_updates_library_listing(self, client, isolated_dirs):
        """After rename, new name should appear in /api/library."""
        (isolated_dirs["photos"] / "before.jpg").write_bytes(_make_test_jpeg())

        client.post(
            "/api/rename-library",
            data={"old_name": "before", "new_name": "after"},
        )

        lib = client.get("/api/library").json()
        names = [p["name"] for p in lib]
        assert "after" in names
        assert "before" not in names


# ===========================================================================
# GET /api/status
# ===========================================================================
class TestApiStatus:
    """Tests for GET /api/status."""

    def test_status_returns_ok(self, client):
        """Status endpoint returns expected fields."""
        resp = client.get("/api/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "telegram" in body
        assert "cards" in body


# ===========================================================================
# GET /api/history
# ===========================================================================
class TestApiHistory:
    """Tests for GET /api/history."""

    def test_history_initially_empty(self, client):
        """Fresh history is an empty list."""
        resp = client.get("/api/history")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_history_grows_with_generates(self, client):
        """Each successful /api/generate adds a history entry."""
        for i in range(3):
            jpeg_bytes = _make_test_jpeg()
            client.post(
                "/api/generate",
                data={"name": f"Person{i}", "text": "Text"},
                files={"photo": (f"p{i}.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
            )
        resp = client.get("/api/history")
        hist = resp.json()
        assert len(hist) == 3
        # Most recent first
        assert hist[0]["name"] == "Person2"
        assert hist[2]["name"] == "Person0"
