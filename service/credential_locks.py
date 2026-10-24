"""Cross-process per-account locks for credential changes and checks."""

from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
from typing import Iterator


def _ensure_no_symlink_ancestors(directory: Path) -> None:
    if any(parent.is_symlink() for parent in (directory, *directory.parents)):
        raise PermissionError(f"Credential lock path must not contain symlinked parents: {directory}")


def _lock_file(account_id: str, catalog_path: str | os.PathLike[str] | None = None) -> int:
    override = os.getenv("MYOS_CREDENTIAL_LOCK_DIR")
    if override:
        lock_directory = Path(override).absolute()
        _ensure_no_symlink_ancestors(lock_directory)
    else:
        if catalog_path is None:
            raise ValueError("catalog_path is required for credential locks")
        catalog_parent = Path(catalog_path).absolute().parent
        _ensure_no_symlink_ancestors(catalog_parent)
        lock_directory = catalog_parent / ".myos-credential-locks"
    lock_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory_stat = lock_directory.lstat()
    if not lock_directory.is_dir() or lock_directory.is_symlink():
        raise PermissionError(f"Credential lock path must be a directory: {lock_directory}")
    if directory_stat.st_uid != os.getuid() or directory_stat.st_mode & 0o077:
        raise PermissionError(f"Credential lock directory must be private: {lock_directory}")
    lock_name = hashlib.sha256(account_id.encode("utf-8")).hexdigest() + ".lock"
    lock_path = lock_directory / lock_name
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.open(lock_path, flags, 0o600)


@contextmanager
def account_credential_lock(account_id: str, catalog_path: str | os.PathLike[str] | None = None) -> Iterator[None]:
    """Serializes credential work for one account across threads and processes."""
    descriptor = _lock_file(account_id, catalog_path)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)
