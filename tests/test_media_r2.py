"""Private R2 serving and local development fallback for catalog media."""

import io
from pathlib import Path

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc.routers import media


class MissingObject(ClientError):
    def __init__(self):
        super().__init__({"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "GetObject")


class FakeS3Client:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.body: io.BytesIO | None = None
        self.error: Exception | None = None

    def get_object(self, *, Bucket, Key):
        self.calls.append((Bucket, Key))
        if self.error is not None:
            raise self.error
        self.body = io.BytesIO(b"fake-image-bytes")
        return {"Body": self.body, "ContentLength": 16}


@pytest.fixture(autouse=True)
def clear_media_r2_cache():
    media._configured_r2_connection.cache_clear()
    yield
    media._configured_r2_connection.cache_clear()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(media.router)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_media_route_streams_private_r2_object_with_cache_headers(monkeypatch, client):
    s3 = FakeS3Client()
    monkeypatch.setattr(media, "create_r2_client_from_environment", lambda: (s3, "private-bucket"))

    response = client.get("/media/images/nested/demo.jpg")

    assert response.status_code == 200
    assert response.content == b"fake-image-bytes"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == media.MEDIA_CACHE_CONTROL
    assert response.headers["x-content-type-options"] == "nosniff"
    assert s3.calls == [("private-bucket", "media/images/nested/demo.jpg")]
    assert s3.body is not None and s3.body.closed


def test_media_route_uses_gif_content_type_and_rejects_non_media_keys(monkeypatch, client):
    s3 = FakeS3Client()
    monkeypatch.setattr(media, "create_r2_client_from_environment", lambda: (s3, "private-bucket"))

    response = client.get("/media/videos/demo.gif")
    rejected = client.get("/media/daily/20260929/catalog.db")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/gif"
    assert rejected.status_code == 404
    assert s3.calls == [("private-bucket", "media/videos/demo.gif")]


def test_media_route_returns_404_without_local_fallback_for_missing_r2_object(monkeypatch, client, tmp_path: Path):
    s3 = FakeS3Client()
    s3.error = MissingObject()
    local_data = tmp_path / "data"
    (local_data / "images").mkdir(parents=True)
    (local_data / "images" / "missing.jpg").write_bytes(b"local-copy")
    monkeypatch.setattr(media, "SEARCH_DIRS", (local_data,))
    monkeypatch.setattr(media, "create_r2_client_from_environment", lambda: (s3, "private-bucket"))

    response = client.get("/media/images/missing.jpg")

    assert response.status_code == 404
    assert response.json() == {"detail": "Media not found."}


def test_media_route_returns_503_for_r2_errors_without_leaking_details(monkeypatch, client):
    s3 = FakeS3Client()
    s3.error = BotoCoreError()
    monkeypatch.setattr(media, "create_r2_client_from_environment", lambda: (s3, "private-bucket"))

    response = client.get("/media/images/temporary.jpg")

    assert response.status_code == 503
    assert response.json() == {"detail": "Media is temporarily unavailable."}


def test_media_route_uses_local_file_when_r2_is_not_configured(monkeypatch, client, tmp_path: Path):
    local_data = tmp_path / "data"
    (local_data / "images").mkdir(parents=True)
    (local_data / "images" / "demo.jpg").write_bytes(b"local-image")
    monkeypatch.setattr(media, "SEARCH_DIRS", (local_data,))
    monkeypatch.setattr(media, "create_r2_client_from_environment", lambda: None)

    response = client.get("/media/images/demo.jpg")

    assert response.status_code == 200
    assert response.content == b"local-image"
    assert response.headers["cache-control"] == media.MEDIA_CACHE_CONTROL
