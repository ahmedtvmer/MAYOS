"""Catalog demo media. Public: assets are generic, not per-player data."""

from datetime import UTC, datetime
from email.utils import format_datetime, parsedate_to_datetime
from functools import lru_cache
import logging
from pathlib import Path
import re
from typing import Any, Iterator, NoReturn

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import FileResponse, StreamingResponse
from service.messages import MessageMetadata
from svc.error_tracking import ReportedStreamAbort
from svc.errors import message_http_exception

from utils.r2 import (
    MEDIA_CACHE_CONTROL,
    MEDIA_CONTENT_TYPES,
    MEDIA_DIRECTORIES,
    MEDIA_PREFIX,
    MISSING_R2_OBJECT_CODES,
    create_r2_client_from_environment,
)

router = APIRouter(prefix="/media", tags=["media"])
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SEARCH_DIRS = (BASE_DIR / "data", BASE_DIR / "dataset")


@lru_cache(maxsize=1)
def _configured_r2_connection() -> tuple[Any, str] | None:
    """Reuse the media-specific client while the process environment is stable."""
    return create_r2_client_from_environment(connect_timeout=2, read_timeout=5, max_attempts=1)


def _allowed_media_path(name: str) -> bool:
    parts = Path(name).parts
    return (
        "\\" not in name
        and not Path(name).is_absolute()
        and ".." not in parts
        and len(parts) >= 2
        and parts[0] in MEDIA_DIRECTORIES
        and Path(parts[-1]).suffix.lower() in MEDIA_DIRECTORIES[parts[0]]
    )


def _stream_body(name: str, streaming_body: Any, expected_length: int | None) -> Iterator[bytes]:
    """Streams the R2 body; a body that ends early aborts the response (#799).

    The declared Content-Length is already sent, so a short body cannot end
    normally. One warning names the file and the byte counts, then the
    connection is aborted so the client does not keep a cut-off file.
    """
    sent = 0
    try:
        while True:
            try:
                chunk = streaming_body.read(64 * 1024)
            except (BotoCoreError, OSError, TimeoutError) as exc:
                _abort_short_stream(name, expected_length, sent, type(exc).__name__)
            if not chunk:
                break
            sent += len(chunk)
            yield chunk
        if expected_length is not None and sent < expected_length:
            _abort_short_stream(name, expected_length, sent, "body ended early")
    finally:
        streaming_body.close()


def _abort_short_stream(name: str, expected_length: int | None, sent: int, reason: str) -> NoReturn:
    logger.warning(
        "Media stream for %s ended after %d of %s bytes (%s).",
        name,
        sent,
        expected_length if expected_length is not None else "unknown",
        reason,
    )
    raise ReportedStreamAbort(name) from None


def _raise_provider_error(exc: Exception) -> None:
    if isinstance(exc, ClientError):
        error = exc.response.get("Error", {})
        if str(error.get("Code", "")) in MISSING_R2_OBJECT_CODES:
            raise message_http_exception(
                status.HTTP_404_NOT_FOUND,
                "Media not found.",
                MessageMetadata("media.not_found.v1"),
            ) from None
    raise message_http_exception(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Media is temporarily unavailable.",
        MessageMetadata("media.unavailable.v1"),
    ) from None


def _head_r2_media(name: str, client: Any, bucket: str) -> dict[str, Any]:
    try:
        return client.head_object(Bucket=bucket, Key=f"{MEDIA_PREFIX}{name}")
    except (BotoCoreError, ClientError, OSError, TimeoutError) as exc:
        _raise_provider_error(exc)


def _get_r2_media(name: str, client: Any, bucket: str) -> dict[str, Any]:
    try:
        return client.get_object(Bucket=bucket, Key=f"{MEDIA_PREFIX}{name}")
    except (BotoCoreError, ClientError, OSError, TimeoutError) as exc:
        _raise_provider_error(exc)


def _validator_headers(remote_object: dict[str, Any]) -> dict[str, str]:
    headers = {"Cache-Control": MEDIA_CACHE_CONTROL, "X-Content-Type-Options": "nosniff"}
    etag = remote_object.get("ETag")
    if not etag:
        sha256 = remote_object.get("Metadata", {}).get("sha256")
        if isinstance(sha256, str) and re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
            etag = f'"{sha256}"'
    if etag:
        headers["ETag"] = str(etag)
    last_modified = remote_object.get("LastModified")
    if isinstance(last_modified, datetime):
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=UTC)
        headers["Last-Modified"] = format_datetime(last_modified.astimezone(UTC), usegmt=True)
    if remote_object.get("ContentLength") is not None:
        headers["Content-Length"] = str(remote_object["ContentLength"])
    return headers


def _etag_matches(request_value: str, etag: str | None) -> bool:
    if etag is None:
        return False
    current = etag.removeprefix("W/")
    return any(
        candidate.strip() == "*" or candidate.strip().removeprefix("W/") == current
        for candidate in request_value.split(",")
    )


def _not_modified(request: Request, headers: dict[str, str]) -> bool:
    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None:
        if if_none_match.strip() == "*":
            return True
        return _etag_matches(if_none_match, headers.get("ETag"))
    if_modified_since = request.headers.get("if-modified-since")
    last_modified = headers.get("Last-Modified")
    if not if_modified_since or not last_modified:
        return False
    try:
        requested_date = parsedate_to_datetime(if_modified_since)
        modified_date = parsedate_to_datetime(last_modified)
    except (TypeError, ValueError, OverflowError):
        return False
    if requested_date.tzinfo is None:
        requested_date = requested_date.replace(tzinfo=UTC)
    return modified_date <= requested_date.astimezone(UTC)


def _r2_media_response(name: str, client: Any, bucket: str, request: Request) -> Response:
    if not _allowed_media_path(name):
        raise message_http_exception(
            status.HTTP_404_NOT_FOUND,
            "Media not found.",
            MessageMetadata("media.not_found.v1"),
        )
    # The cheap HEAD only answers a conditional request with 304. A full
    # response takes its length and validators from the GET that supplies the
    # body, so they cannot describe a different object version (#799).
    if _is_conditional(request):
        validators = _validator_headers(_head_r2_media(name, client, bucket))
        if _not_modified(request, validators):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=validators)
    remote_object = _get_r2_media(name, client, bucket)
    headers = _validator_headers(remote_object)
    content_type = MEDIA_CONTENT_TYPES[Path(name).suffix.lower()]
    expected_length = remote_object.get("ContentLength")
    return StreamingResponse(
        _stream_body(name, remote_object["Body"], int(expected_length) if expected_length is not None else None),
        media_type=content_type,
        headers=headers,
    )


def _is_conditional(request: Request) -> bool:
    return (
        request.headers.get("if-none-match") is not None
        or request.headers.get("if-modified-since") is not None
    )


def _local_media_response(name: str) -> FileResponse:
    for directory in SEARCH_DIRS:
        candidate = directory / name
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file() and directory in resolved.parents:
            return FileResponse(resolved, headers={"Cache-Control": MEDIA_CACHE_CONTROL})
    raise message_http_exception(
        status.HTTP_404_NOT_FOUND,
        "Media not found.",
        MessageMetadata("media.not_found.v1"),
    )


@router.get("/{name:path}")
def get_media(name: str, request: Request) -> Response:
    if not _allowed_media_path(name):
        raise message_http_exception(
            status.HTTP_404_NOT_FOUND,
            "Media not found.",
            MessageMetadata("media.not_found.v1"),
        )

    connection = _configured_r2_connection()
    if connection is not None:
        client, bucket = connection
        return _r2_media_response(name, client, bucket, request)
    return _local_media_response(name)
