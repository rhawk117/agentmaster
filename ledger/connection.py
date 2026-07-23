import sqlite3
from dataclasses import dataclass
from pathlib import Path

BUSY_TIMEOUT_MS = 5_000
MIN_WAL_SAFE_VERSION = (3, 51, 3)
_NETWORK_FILESYSTEM_TYPES = frozenset({
    'nfs',
    'nfs4',
    'cifs',
    'smb3',
    'smbfs',
    '9p',
    'afs',
    'fuse.sshfs',
})


@dataclass(frozen=True, slots=True)
class JournalDecision:
    mode: str
    reason: str


def _runtime_sqlite_version() -> tuple[int, int, int]:
    parts = [int(part) for part in sqlite3.sqlite_version.split('.')]
    major, minor, patch, *_rest = (*parts, 0, 0)
    return major, minor, patch


def _mount_filesystem_type(path: Path) -> str | None:
    mounts_file = Path('/proc/mounts')
    if not mounts_file.is_file():
        return None
    resolved = str(path.resolve())
    best_match: tuple[int, str] | None = None
    for line in mounts_file.read_text(encoding='utf-8').splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        mount_point, fs_type = fields[1], fields[2]
        if resolved.startswith(mount_point) and (
            best_match is None or len(mount_point) > best_match[0]
        ):
            best_match = (len(mount_point), fs_type)
    return best_match[1] if best_match else None


def _is_network_filesystem(path: Path) -> bool:
    fs_type = _mount_filesystem_type(path)
    return fs_type in _NETWORK_FILESYSTEM_TYPES if fs_type else False


def select_journal_mode(ledger_path: Path) -> JournalDecision:
    version = _runtime_sqlite_version()
    if version < MIN_WAL_SAFE_VERSION:
        required = '.'.join(str(part) for part in MIN_WAL_SAFE_VERSION)
        return JournalDecision(
            mode='DELETE',
            reason=(
                f'sqlite3 runtime {sqlite3.sqlite_version} lacks the WAL-reset fix '
                f'(requires >= {required})'
            ),
        )
    if _is_network_filesystem(ledger_path):
        return JournalDecision(
            mode='DELETE', reason=f'{ledger_path} is on a network filesystem'
        )
    return JournalDecision(mode='WAL', reason='local filesystem and sqlite >= 3.51.3')


def connect_read_only(ledger_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f'file:{ledger_path}?mode=ro', uri=True)
    connection.execute('PRAGMA query_only = ON')
    return connection


def connect(ledger_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(ledger_path, timeout=BUSY_TIMEOUT_MS / 1000)
    try:
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute(f'PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}')
        decision = select_journal_mode(ledger_path)
        connection.execute(f'PRAGMA journal_mode = {decision.mode}')
    except sqlite3.Error:
        connection.close()
        raise
    return connection
