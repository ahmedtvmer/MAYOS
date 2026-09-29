"""Private R2 serving and local development fallback for catalog media."""

import io
from datetime import UTC, datetime
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svc.routers import media


class MissingObject(ClientError):
    def __init__(self):
        super().__init__({"Error": {"Code": "NoSuchKey", "Message": "missing"}}, "HeadObject")


class FakeS3Client:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []
        self.body: io.BytesIO | None = None
        self.error: Exception | None = None

    def head_object(self, *, Bucket, Key):
        self.calls.append(("head", Bucket, Key))
        if self.error is not None:
            raise self.error
        return {
            "ContentLength": 16,
            "ETag": '"fixture-etag"',
            "LastModified": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        }

    def get_object(self, *, Bucket, Key):
        self.calls.append(("get", Bucket, Key))
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


def _configure_r2(monkeypatch, s3):
    captured = {}

    def fake_client(service, **kwargs):
        captured.update(kwargs)
        return s3

    monkeypatch.setattr(boto3, "client", fake_client)
    monkeypatch.setenv("R2_ENDPOINT", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("R2_BUCKET", "private-bucket")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret-key")
    return captured


@pytest.mark.parametrize(
    ("path", "content_type", "key"),
    [
        ("/media/images/nested/demo.jpg", "image/jpeg", "media/images/nested/demo.jpg"),
        ("/media/videos/demo.gif", "image/gif", "media/videos/demo.gif"),
    ],
)
def test_media_streams_private_r2_object_with_validators(monkeypatch, client, path, content_type, key):
    s3 = FakeS3Client()
    _configure_r2(monkeypatch, s3)

    response = client.get(path)

    assert response.status_code == 200
    assert response.content == b"fake-image-bytes"
    assert response.headers["content-type"] == content_type
    assert response.headers["cache-control"] == media.MEDIA_CACHE_CONTROL
    assert response.headers["etag"] == '"fixture-etag"'
    assert response.headers["last-modified"] == "Thu, 01 Jan 2026 12:00:00 GMT"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert s3.calls == [
        ("head", "private-bucket", key),
        ("get", "private-bucket", key),
    ]
    assert s3.body is not None and s3.body.closed


def test_conditional_requests_return_304_without_streaming_body(monkeypatch, client):
    s3 = FakeS3Client()
    _configure_r2(monkeypatch, s3)
    first = client.get("/media/images/demo.jpg")

    by_etag = client.get("/media/images/demo.jpg", headers={"If-None-Match": first.headers["etag"]})
    by_date = client.get(
        "/media/images/demo.jpg", headers={"If-Modified-Since": first.headers["last-modified"]}
    )

    assert first.status_code == 200
    assert by_etag.status_code == by_date.status_code == 304
    assert by_etag.content == by_date.content == b""
    assert by_etag.headers["etag"] == first.headers["etag"]
    assert by_etag.headers["cache-control"] == media.MEDIA_CACHE_CONTROL
    assert [operation for operation, _, _ in s3.calls] == ["head", "get", "head", "head"]


def test_media_requests_use_bounded_timeouts_and_one_retry(monkeypatch, client):
    captured = _configure_r2(monkeypatch, FakeS3Client())

    response = client.get("/media/images/demo.jpg")

    assert response.status_code == 200
    config = captured["config"]
    assert config.connect_timeout == 2
    assert config.read_timeout == 5
    assert config.retries == {"mode": "standard", "max_attempts": 1}


@pytest.mark.parametrize(
    "path",
    [
        "/media/images/%2e%2e/daily%2fcatalog.db",
        "/media/images%2f..%2fdaily%2fcatalog.db",
        "/media/images%5c..%5cdaily%5ccatalog.db",
        "/media/%2fdaily%2f20260929%2fcatalog.db",
        "/media/daily/20260929/catalog.db",
    ],
)
def test_unsafe_and_backup_paths_return_404_without_r2_calls(monkeypatch, client, path):
    s3 = FakeS3Client()
    _configure_r2(monkeypatch, s3)

    response = client.get(path)

    assert response.status_code == 404
    assert s3.calls == []


def test_media_route_returns_404_without_local_fallback_for_missing_r2_object(monkeypatch, client, tmp_path: Path):
    s3 = FakeS3Client()
    s3.error = MissingObject()
    local_data = tmp_path / "data"
    (local_data / "images").mkdir(parents=True)
    (local_data / "images" / "missing.jpg").write_bytes(b"local-copy")
    monkeypatch.setattr(media, "SEARCH_DIRS", (local_data,))
    _configure_r2(monkeypatch, s3)

    response = client.get("/media/images/missing.jpg")

    assert response.status_code == 404
    assert response.json() == {"detail": "Media not found."}
    assert s3.calls == [("head", "private-bucket", "media/images/missing.jpg")]


@pytest.mark.parametrize("provider_error", [BotoCoreError(), TimeoutError("provider timed out")])
def test_media_route_returns_generic_503_for_r2_errors(monkeypatch, client, provider_error):
    s3 = FakeS3Client()
    s3.error = provider_error
    _configure_r2(monkeypatch, s3)

    response = client.get("/media/images/temporary.jpg")

    assert response.status_code == 503
    assert response.json() == {"detail": "Media is temporarily unavailable."}


def test_media_route_uses_local_file_when_r2_is_not_configured(monkeypatch, client, tmp_path: Path):
    local_data = tmp_path / "data"
    (local_data / "images").mkdir(parents=True)
    (local_data / "images" / "demo.jpg").write_bytes(b"local-image")
    monkeypatch.setattr(media, "SEARCH_DIRS", (local_data,))
    for name in ("R2_ENDPOINT", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(name, raising=False)

    response = client.get("/media/images/demo.jpg")

    assert response.status_code == 200
    assert response.content == b"local-image"
    assert response.headers["cache-control"] == media.MEDIA_CACHE_CONTROL
