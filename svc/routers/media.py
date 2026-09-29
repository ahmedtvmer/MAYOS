"""Catalog demo media. Public: assets are generic, not per-player data."""

import mimetypes
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException, status
from botocore.exceptions import BotoCoreError, ClientError
from fastapi.responses import FileResponse, StreamingResponse

from database.offsite_backup import create_r2_client_from_environment

router = APIRouter(prefix="/media", tags=["media"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SEARCH_DIRS = (BASE_DIR / "data", BASE_DIR / "dataset")
R2_MEDIA_PREFIX = "media/"
MEDIA_CACHE_CONTROL = "public, max-age=31536000"
R2_MEDIA_PATHS = {"images": {".jpg", ".jpeg"}, "videos": {".gif"}}


@lru_cache(maxsize=1)
def _configured_r2_connection() -> tuple[Any, str] | None:
    """Reuse the R2 client while the process environment is stable."""
    return create_r2_client_from_environment()


def _allowed_r2_media(name: str) -> bool:
    parts = Path(name).parts
    return (
        len(parts) >= 2
        and parts[0] in R2_MEDIA_PATHS
        and Path(parts[-1]).suffix.lower() in R2_MEDIA_PATHS[parts[0]]
    )


def _stream_body(streaming_body: Any) -> Iterator[bytes]:
    try:
        while chunk := streaming_body.read(64 * 1024):
            yield chunk
    finally:
        streaming_body.close()


def _missing_object(exc: ClientError) -> bool:
    response = getattr(exc, "response", {})
    code = str(response.get("Error", {}).get("Code", ""))
    return code in {"404", "NoSuchKey", "NotFound"}


def _get_r2_media_object(name: str, client: Any, bucket: str) -> dict[str, Any]:
    try:
        return client.get_object(Bucket=bucket, Key=f"{R2_MEDIA_PREFIX}{name}")
    except ClientError as exc:
        if _missing_object(exc):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found.") from None
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Media is temporarily unavailable.") from None
    except BotoCoreError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Media is temporarily unavailable.") from None


def _r2_media_response(name: str, client: Any, bucket: str) -> StreamingResponse:
    if not _allowed_r2_media(name):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found.")
    remote_object = _get_r2_media_object(name, client, bucket)
    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    headers = {
        "Cache-Control": MEDIA_CACHE_CONTROL,
        "X-Content-Type-Options": "nosniff",
    }
    if remote_object.get("ContentLength") is not None:
        headers["Content-Length"] = str(remote_object["ContentLength"])
    return StreamingResponse(_stream_body(remote_object["Body"]), media_type=content_type, headers=headers)


def _local_media_response(name: str) -> FileResponse:
    for directory in SEARCH_DIRS:
        candidate = directory / name
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file() and directory in resolved.parents:
            return FileResponse(resolved, headers={"Cache-Control": MEDIA_CACHE_CONTROL})
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found.")


@router.get("/{name:path}")
def get_media(name: str):
    if not name or name.startswith(("http://", "https://", "/")) or ".." in Path(name).parts:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found.")

    connection = _configured_r2_connection()
    if connection is not None:
        client, bucket = connection
        return _r2_media_response(name, client, bucket)
    return _local_media_response(name)
