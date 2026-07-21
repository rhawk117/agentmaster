"""Content-addressed SHA-256 artifact storage (SPEC.md §16.1, §23 Microtask 13).

Writes are atomic and deduplicated: a blob is hashed first, and if a file
already exists at that digest's path the write is skipped entirely. A new
blob is written to a temporary file in the same directory and renamed into
place, so a crash mid-write never leaves a partial file at the final path.
"""

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

_SHA256_HEX = re.compile(r'^[0-9a-f]{64}$')


@dataclass(frozen=True, slots=True)
class ArtifactWrite:
    """The result of storing one blob of content-addressed bytes."""

    sha256: str
    relative_path: str
    byte_size: int
    deduplicated: bool


def content_address(data: bytes) -> str:
    """Return the SHA-256 hex digest identifying `data`."""
    return hashlib.sha256(data).hexdigest()


class ArtifactStore:
    """Atomic, deduplicated, content-addressed storage under `root/sha256/`."""

    def __init__(self, root: Path) -> None:
        self._sha256_root = root / 'sha256'
        self._sha256_root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def path_for(self, sha256: str) -> Path:
        """Return the on-disk path for the artifact identified by `sha256`.

        Raises
        ------
        ValueError
            If `sha256` is not a 64-character lowercase hex digest, so a
            malformed or traversal-crafted digest can never be used to
            build a path outside the artifact root.
        """
        if not _SHA256_HEX.fullmatch(sha256):
            raise ValueError(f'not a valid sha256 hex digest: {sha256!r}')
        return self._sha256_root / sha256

    def put(self, data: bytes) -> ArtifactWrite:
        """Store `data` at its content-addressed path, deduplicating identical content."""
        digest = content_address(data)
        final_path = self.path_for(digest)
        relative_path = f'sha256/{digest}'
        if final_path.exists():
            return ArtifactWrite(digest, relative_path, len(data), deduplicated=True)

        descriptor, tmp_name = tempfile.mkstemp(dir=self._sha256_root)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(descriptor, 'wb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            tmp_path.chmod(0o600)
            tmp_path.replace(final_path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
        return ArtifactWrite(digest, relative_path, len(data), deduplicated=False)

    def read(self, sha256: str) -> bytes:
        """Return the stored bytes for `sha256`."""
        return self.path_for(sha256).read_bytes()
