"""Presentation helpers: API namespaces and media resolution."""

from pathlib import Path
from types import SimpleNamespace

from ui.api_client import API_BASE_URL


def ns(value):
    """Converts API dicts/lists to attribute-style namespaces for render code."""
    if isinstance(value, dict):
        return SimpleNamespace(**{key: ns(item) for key, item in value.items()})
    if isinstance(value, list):
        return [ns(item) for item in value]
    return value


def resolve_media_path(path: str | None, base_dir: Path) -> str | None:
    """Local file when present, otherwise the service media URL (public catalog assets)."""
    if not path or not isinstance(path, str):
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    for candidate in [Path(path), base_dir / path, base_dir / "data" / path, base_dir / "dataset" / path]:
        if candidate.is_file():
            return str(candidate.resolve())
    name = Path(path).name
    if name and ".." not in Path(name).parts:
        return f"{API_BASE_URL}/media/{name}"
    return None
