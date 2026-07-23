import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

_SHA256_HEX = re.compile(r'^[0-9a-f]{64}$')


@dataclass(frozen=True, slots=True)
class ArtifactWrite:
    sha256: str
    relative_path: str
    byte_size: int
    deduplicated: bool


def content_address(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self._sha256_root = root / 'sha256'
        self._sha256_root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def path_for(self, sha256: str) -> Path:
        if not _SHA256_HEX.fullmatch(sha256):
            raise ValueError(f'not a valid sha256 hex digest: {sha256!r}')
        return self._sha256_root / sha256

    def put(self, data: bytes) -> ArtifactWrite:
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
        return self.path_for(sha256).read_bytes()
