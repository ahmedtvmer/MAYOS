"""Catalog demo media. Public: assets are generic, not per-trainee data."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

router = APIRouter(prefix="/media", tags=["media"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SEARCH_DIRS = (BASE_DIR / "data", BASE_DIR / "dataset")


@router.get("/{name:path}")
async def get_media(name: str):
    if not name or name.startswith(("http://", "https://", "/")) or ".." in Path(name).parts:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found.")
    for directory in SEARCH_DIRS:
        candidate = directory / name
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file() and directory in resolved.parents:
            return FileResponse(resolved)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found.")
