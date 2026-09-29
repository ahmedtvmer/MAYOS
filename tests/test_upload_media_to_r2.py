"""Hermetic tests for the one-off, repeatable R2 catalog media upload."""

from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from scripts.upload_media_to_r2 import CACHE_CONTROL, plan_media_upload, upload_media


class MissingObject(ClientError):
    def __init__(self):
        super().__init__({"Error": {"Code": "404", "Message": "missing"}}, "HeadObject")


class FakeS3Client:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, dict]] = {}
        self.uploads: list[tuple[str, str, dict]] = []

    def head_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise MissingObject()
        body, extra = self.objects[Key]
        return {"ContentLength": len(body), "Metadata": extra["Metadata"]}

    def upload_file(self, filename, bucket, key, *, ExtraArgs):
        body = Path(filename).read_bytes()
        self.objects[key] = (body, ExtraArgs)
        self.uploads.append((bucket, key, ExtraArgs))


def _media_tree(root: Path) -> Path:
    (root / "images" / "nested").mkdir(parents=True)
    (root / "videos").mkdir()
    (root / "images" / "nested" / "still.jpg").write_bytes(b"jpeg-image")
    (root / "videos" / "motion.gif").write_bytes(b"gif-image")
    return root


def test_upload_media_preserves_paths_content_types_and_is_idempotent(tmp_path):
    data_dir = _media_tree(tmp_path / "data")
    client = FakeS3Client()

    assert upload_media(data_dir, client, "private-bucket") == (2, 0)

    assert set(client.objects) == {
        "media/images/nested/still.jpg",
        "media/videos/motion.gif",
    }
    assert client.objects["media/images/nested/still.jpg"][1]["ContentType"] == "image/jpeg"
    assert client.objects["media/videos/motion.gif"][1]["ContentType"] == "image/gif"
    assert all(extra["CacheControl"] == CACHE_CONTROL for _, _, extra in client.uploads)
    assert all(len(extra["Metadata"]["sha256"]) == 64 for _, _, extra in client.uploads)

    assert upload_media(data_dir, client, "private-bucket") == (0, 2)
    assert len(client.uploads) == 2


def test_upload_media_replaces_same_size_object_when_sha256_changes(tmp_path):
    data_dir = _media_tree(tmp_path / "data")
    client = FakeS3Client()
    upload_media(data_dir, client, "private-bucket")
    original = client.objects["media/images/nested/still.jpg"][0]
    changed = b"jpeg-IMAGE"
    assert len(changed) == len(original)
    (data_dir / "images" / "nested" / "still.jpg").write_bytes(changed)

    uploaded, skipped = upload_media(data_dir, client, "private-bucket")

    assert (uploaded, skipped) == (1, 1)
    assert client.objects["media/images/nested/still.jpg"][0] == changed


def test_upload_media_dry_run_does_not_upload(tmp_path):
    data_dir = _media_tree(tmp_path / "data")
    client = FakeS3Client()

    assert plan_media_upload(data_dir, client, "private-bucket") == (2, 0)
    assert client.objects == {}
    assert client.uploads == []


def test_upload_media_refuses_a_partial_source_tree_before_uploading(tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "images").mkdir(parents=True)
    (data_dir / "images" / "still.jpg").write_bytes(b"jpeg-image")
    client = FakeS3Client()

    with pytest.raises(FileNotFoundError, match="videos"):
        upload_media(data_dir, client, "private-bucket")

    assert client.uploads == []
