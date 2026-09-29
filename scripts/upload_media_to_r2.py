"""Upload catalog images and GIFs to the private R2 media/ prefix.

Run once before deploying the R2-backed /media route, then repeat whenever
the media files change. Objects are compared by byte length and SHA-256
metadata so a rerun uploads only changed files.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

MEDIA_PREFIX = "media/"
CACHE_CONTROL = "public, max-age=31536000"
MEDIA_DIRECTORIES = {"images": {".jpg", ".jpeg"}, "videos": {".gif"}}
MISSING_OBJECT_CODES = {"404", "NoSuchKey", "NotFound"}


@dataclass(frozen=True)
class MediaUpload:
    source_path: Path
    object_key: str
    content_type: str
    sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_object(client: Any, bucket: str, key: str) -> dict[str, Any] | None:
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        response = getattr(exc, "response", {})
        code = str(response.get("Error", {}).get("Code", ""))
        if code in MISSING_OBJECT_CODES:
            return None
        raise


def _catalog_media_files(data_dir: Path) -> list[MediaUpload]:
    """Build upload descriptions after validating both source directories."""
    return [
        media_file
        for directory, extensions in MEDIA_DIRECTORIES.items()
        for media_file in _directory_media_files(data_dir, directory, extensions)
    ]


def _directory_media_files(data_dir: Path, directory: str, extensions: set[str]) -> list[MediaUpload]:
    source_dir = data_dir / directory
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Required media directory is missing: {source_dir}")

    files = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        if not path.resolve().is_relative_to(source_dir.resolve()):
            raise ValueError(f"Media file resolves outside its source directory: {path}")
        if path.suffix.lower() not in extensions:
            raise ValueError(f"Unsupported file in {source_dir}: {path.name}")
        content_type = "image/gif" if directory == "videos" else "image/jpeg"
        relative_path = path.relative_to(data_dir).as_posix()
        files.append(MediaUpload(path, f"{MEDIA_PREFIX}{relative_path}", content_type, _sha256(path)))
    if not files:
        raise FileNotFoundError(f"No catalog media files found under {source_dir}.")
    return files


def _changed_media_files(data_dir: Path, client: Any, bucket: str) -> tuple[list[MediaUpload], int]:
    """Return changed objects and the count whose size and SHA-256 match."""
    files = _catalog_media_files(data_dir)
    skipped = 0
    changed_files: list[MediaUpload] = []
    for media_file in files:
        existing = _existing_object(client, bucket, media_file.object_key)
        if (
            existing is not None
            and int(existing.get("ContentLength", -1)) == media_file.source_path.stat().st_size
            and existing.get("Metadata", {}).get("sha256") == media_file.sha256
        ):
            skipped += 1
            continue
        changed_files.append(media_file)
    return changed_files, skipped


def plan_media_upload(data_dir: Path, client: Any, bucket: str) -> tuple[int, int]:
    """List changed files without uploading and return planned/skipped counts."""
    changed_files, skipped = _changed_media_files(data_dir, client, bucket)
    for media_file in changed_files:
        print(f"Would upload: {media_file.object_key}")
    return len(changed_files), skipped


def upload_media(data_dir: Path, client: Any, bucket: str) -> tuple[int, int]:
    """Upload changed files and return uploaded/skipped counts."""
    changed_files, skipped = _changed_media_files(data_dir, client, bucket)
    for media_file in changed_files:
        client.upload_file(
            str(media_file.source_path),
            bucket,
            media_file.object_key,
            ExtraArgs={
                "ContentType": media_file.content_type,
                "CacheControl": CACHE_CONTROL,
                "Metadata": {"sha256": media_file.sha256},
            },
        )
        print(f"Uploaded: {media_file.object_key}")

    return len(changed_files), skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload catalog images and GIFs to private Cloudflare R2.")
    parser.add_argument("--dry-run", action="store_true", help="list changed objects without uploading them")
    parser.add_argument("--data-dir", type=Path, default=BASE_DIR / "data", help="catalog data directory")
    args = parser.parse_args()

    from database.offsite_backup import create_r2_client_from_environment

    connection = create_r2_client_from_environment()
    if connection is None:
        parser.error("set R2_ENDPOINT, R2_BUCKET, R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY")
    client, bucket = connection
    if args.dry_run:
        object_count, skipped = plan_media_upload(args.data_dir, client, bucket)
        action = "would upload"
    else:
        object_count, skipped = upload_media(args.data_dir, client, bucket)
        action = "uploaded"
    print(f"Media sync complete: {action} {object_count}, unchanged {skipped}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
