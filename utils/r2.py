"""Shared Cloudflare R2 client configuration and catalog media settings."""

import os
from typing import Any

R2_ENDPOINT_ENV = "R2_ENDPOINT"
R2_BUCKET_ENV = "R2_BUCKET"
R2_ACCESS_KEY_ENV = "R2_ACCESS_KEY_ID"
R2_SECRET_KEY_ENV = "R2_SECRET_ACCESS_KEY"
R2_ENV_NAMES = (R2_ENDPOINT_ENV, R2_BUCKET_ENV, R2_ACCESS_KEY_ENV, R2_SECRET_KEY_ENV)

MEDIA_PREFIX = "media/"
MEDIA_CACHE_CONTROL = "public, max-age=86400, stale-while-revalidate=604800"
MEDIA_DIRECTORIES = {"images": {".jpg", ".jpeg"}, "videos": {".gif"}}
MEDIA_CONTENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif"}
MISSING_R2_OBJECT_CODES = {"404", "NoSuchKey", "NotFound"}


def create_r2_client_from_environment(
    *, connect_timeout: int = 5, read_timeout: int = 30, max_attempts: int = 3
) -> tuple[Any, str] | None:
    """Create an S3 client from named R2 settings without exposing credentials."""
    environment_values = {name: os.getenv(name, "").strip() for name in R2_ENV_NAMES}
    if not all(environment_values.values()):
        return None

    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        region_name="auto",
        endpoint_url=environment_values[R2_ENDPOINT_ENV],
        aws_access_key_id=environment_values[R2_ACCESS_KEY_ENV],
        aws_secret_access_key=environment_values[R2_SECRET_KEY_ENV],
        config=Config(
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            retries={"mode": "standard", "max_attempts": max_attempts},
            signature_version="s3v4",
        ),
    )
    return client, environment_values[R2_BUCKET_ENV]
