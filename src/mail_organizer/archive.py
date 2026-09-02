"""Verified local and NAS archive transaction primitives."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ArchiveReceipt:
    path: Path
    size_bytes: int
    sha256: str


class VerifiedArchive:
    """Write bytes atomically and verify them before returning success."""

    def __init__(self, root: Path) -> None:
        self._root = root.expanduser().resolve()

    def store(self, relative_path: Path, content: bytes) -> ArchiveReceipt:
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("Archive path must be relative and traversal-free")
        destination = (self._root / relative_path).resolve()
        if not destination.is_relative_to(self._root):
            raise ValueError("Archive destination escapes the configured root")
        destination.parent.mkdir(parents=True, exist_ok=True)
        expected_hash = hashlib.sha256(content).hexdigest()
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
                temporary_path = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if hashlib.sha256(temporary_path.read_bytes()).hexdigest() != expected_hash:
                raise OSError("Archive verification failed")
            temporary_path.replace(destination)
            stored = destination.read_bytes()
            if len(stored) != len(content) or hashlib.sha256(stored).hexdigest() != expected_hash:
                raise OSError("Final archive verification failed")
            return ArchiveReceipt(destination, len(stored), expected_hash)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
