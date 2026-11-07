import re
import os
import subprocess
from pathlib import Path


# Built from pieces so this file does not match its own pattern.
LEGACY_PROVIDER_REFERENCE = re.compile(r"\b" + "o" + "v" + "h", re.IGNORECASE)
# Ignore encoded image bytes inside text files; they can contain accidental matches.
IMAGE_DATA_URI = re.compile(r"data:image/[^;]+;base64,[A-Za-z0-9+/=]+")


def _tracked_text_files(repo_root):
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    for relative_path in result.stdout.splitlines():
        path = Path(relative_path)
        if path.as_posix().startswith("docs/design-review/") and path.suffix == ".patch":
            continue
        try:
            full_path = repo_root / path
            # Git tracks a symlink's target text, not the target's contents.
            # Owner-local tool links can legitimately dangle on a CI runner.
            content = os.readlink(full_path) if full_path.is_symlink() else full_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        yield relative_path, content


def test_tracked_text_has_no_legacy_provider_reference(git_checkout):
    repo_root = git_checkout
    matches = []
    for relative_path, content in _tracked_text_files(repo_root):
        for line_number, line in enumerate(content.splitlines(), start=1):
            searchable_line = IMAGE_DATA_URI.sub("", line)
            if LEGACY_PROVIDER_REFERENCE.search(searchable_line):
                matches.append(f"{relative_path}:{line_number}")

    assert not matches, "Legacy provider references found:\n" + "\n".join(matches)
