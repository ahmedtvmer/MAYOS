"""Per-account synchronization for password and recovery credential changes."""

from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Iterator


def _lock_file(account_id: str) -> int:
    lock_directory = Path(tempfile.gettempdir()) / f"myos-credential-locks-{os.getuid()}"
    lock_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory_stat = lock_directory.stat()
    if directory_stat.st_uid != os.getuid() or directory_stat.st_mode & 0o077:
        raise PermissionError(f"Credential lock directory must be private: {lock_directory}")
    lock_name = hashlib.sha256(account_id.encode("utf-8")).hexdigest() + ".lock"
    lock_path = lock_directory / lock_name
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    return os.open(lock_path, flags, 0o600)


@contextmanager
def account_credential_lock(account_id: str) -> Iterator[None]:
    """Serializes credential work for one account across threads and processes."""
    descriptor = _lock_file(account_id)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)
