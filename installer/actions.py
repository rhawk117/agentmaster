"""Transactional file actions for the agentmaster installer.

`apply_plans` classifies every planned file before touching the filesystem
(create / update / mode / skip), backs up files it is about to update into a
collision-safe backup directory, writes each file atomically (temp file +
`os.replace`) preserving the destination's existing permissions unless the
plan requests executable, and rolls the entire batch back to its exact prior
state if any write fails partway through. `dry_run` performs the
classification and reporting only.
"""

import os
import secrets
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

type Status = Literal['create', 'update', 'mode', 'skip', 'remove']


@dataclass(frozen=True, slots=True)
class FilePlan:
    """One file the installer intends to place, with its exact content."""

    content: str
    destination: Path
    executable: bool = False


@dataclass(slots=True)
class InstallReport:
    """Outcome of an install or uninstall run."""

    entries: list[tuple[Status, Path]] = field(default_factory=list)
    backup_dir: Path | None = None

    def summary(self) -> str:
        counts = dict.fromkeys(('create', 'update', 'mode', 'skip', 'remove'), 0)
        for status, _ in self.entries:
            counts[status] += 1
        return (
            f'created {counts["create"]}, updated {counts["update"]}, '
            f'mode-changed {counts["mode"]}, skipped {counts["skip"]}, '
            f'removed {counts["remove"]}'
        )


class BatchRollbackError(OSError):
    """A batch write failed and rollback could not fully restore prior state.

    Raised only when rollback itself leaves some destinations unrestored;
    a clean rollback re-raises the original error instead, so callers only
    ever see this type when there is genuinely extra diagnostic content —
    both the triggering failure and the paths rollback could not fix.

    Parameters
    ----------
    original
        The exception that triggered rollback.
    unrestored
        Destinations rollback could not restore to their prior state.
    """

    def __init__(self, original: Exception, unrestored: list[Path]) -> None:
        self.original = original
        self.unrestored = unrestored
        paths = ', '.join(str(path) for path in unrestored)
        message = f'install failed ({original}); rollback could not restore: {paths}'
        super().__init__(message)


def _default_suffix() -> str:
    return f'{time.strftime("%Y%m%d-%H%M%S")}-{secrets.token_hex(4)}'


def _unique_dir(root: Path, prefix: str, *, suffix_provider: Callable[[], str]) -> Path:
    """Create and return a directory under `root` that did not previously exist.

    Never `mkdir(exist_ok=True)`: a backup directory is exclusively owned by
    one batch, so reusing an existing one would let two runs' backups mix.
    """
    root.mkdir(parents=True, exist_ok=True)
    while True:
        candidate = root / f'{prefix}-{suffix_provider()}'
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate


def _classify(plan: FilePlan) -> Status:
    if not plan.destination.exists():
        return 'create'
    if plan.destination.read_text(encoding='utf-8') != plan.content:
        return 'update'
    if _is_executable(plan.destination) != plan.executable:
        return 'mode'
    return 'skip'


def _is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & 0o111)


def _backup(destination: Path, backup_dir: Path, backup_root: Path) -> Path:
    try:
        relative = destination.relative_to(backup_root)
    except ValueError:
        relative = Path(destination.name)
    target = backup_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(destination, target)
    return target


def _write_atomic(plan: FilePlan, prior_mode: int | None) -> None:
    """Write `plan.content` atomically, preserving `prior_mode` when given.

    `prior_mode` is the destination's existing permission bits on an update;
    `None` on a fresh create, where the temp file's own default mode applies
    unless `plan.executable` requests the execute bits.
    """
    fd, tmp_name = tempfile.mkstemp(dir=plan.destination.parent, suffix='.tmp')
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(plan.content)
        if prior_mode is not None:
            tmp.chmod(prior_mode | 0o111 if plan.executable else prior_mode)
        elif plan.executable:
            tmp.chmod(0o755)
        tmp.replace(plan.destination)
    finally:
        tmp.unlink(missing_ok=True)


def _apply_mode_only(plan: FilePlan, *, prior_mode: int) -> None:
    """Flip only the execute bits; content is already identical."""
    new_mode = prior_mode | 0o111 if plan.executable else prior_mode & ~0o111
    plan.destination.chmod(new_mode)


@dataclass(slots=True)
class _Applied:
    """One completed write in a batch, with enough state to invert it."""

    status: Status
    destination: Path
    backup: Path | None = None
    prior_mode: int | None = None


def _rollback(applied: list[_Applied]) -> list[Path]:
    """Best-effort restore of every applied write, most recent first.

    Returns the destinations that could not be restored; an empty list
    means the batch's prior state was fully recovered.
    """
    unrestored: list[Path] = []
    for entry in reversed(applied):
        try:
            if entry.status == 'create':
                entry.destination.unlink(missing_ok=True)
            elif entry.status == 'update' and entry.backup is not None:
                shutil.copy2(entry.backup, entry.destination)
            elif entry.status == 'mode' and entry.prior_mode is not None:
                entry.destination.chmod(entry.prior_mode)
        except OSError:
            unrestored.append(entry.destination)
    return unrestored


def apply_plans(
    plans: Sequence[FilePlan],
    *,
    backup_root: Path,
    dry_run: bool,
    suffix_provider: Callable[[], str] = _default_suffix,
    write: Callable[[FilePlan, int | None], None] = _write_atomic,
) -> InstallReport:
    """Install every plan, or report what would happen when `dry_run`.

    Classification happens for all plans before any write; parent
    directories are created for all plans before the first file is
    written, so an uncreatable parent aborts with nothing installed. If a
    write fails partway through the batch, every prior write from this call
    is rolled back to its exact starting state before the exception
    propagates; if rollback itself cannot restore everything, the original
    failure and the unrestored paths are reported together via
    `BatchRollbackError`.

    `suffix_provider` and `write` are injectable so tests can force a
    collision or a mid-batch failure deterministically, without permission
    or timing tricks against the real filesystem.
    """
    classified = [(plan, _classify(plan)) for plan in plans]
    report = InstallReport(
        entries=[(status, plan.destination) for plan, status in classified]
    )
    if dry_run:
        return report

    pending = [(plan, status) for plan, status in classified if status != 'skip']
    for plan, _ in pending:
        plan.destination.parent.mkdir(parents=True, exist_ok=True)

    backup_dir = None
    if any(status == 'update' for _, status in pending):
        backup_dir = _unique_dir(
            backup_root, 'agentmaster-backup', suffix_provider=suffix_provider
        )
        report.backup_dir = backup_dir

    applied: list[_Applied] = []
    try:
        for plan, status in pending:
            applied.append(_apply_one(plan, status, backup_dir, backup_root, write))
    except Exception as error:
        unrestored = _rollback(applied)
        if unrestored:
            raise BatchRollbackError(error, unrestored) from error
        raise
    return report


def _apply_one(
    plan: FilePlan,
    status: Status,
    backup_dir: Path | None,
    backup_root: Path,
    write: Callable[[FilePlan, int | None], None],
) -> _Applied:
    if status == 'create':
        write(plan, None)
        return _Applied(status=status, destination=plan.destination)

    prior_mode = plan.destination.stat().st_mode & 0o777
    if status == 'mode':
        _apply_mode_only(plan, prior_mode=prior_mode)
        return _Applied(
            status=status, destination=plan.destination, prior_mode=prior_mode
        )

    assert backup_dir is not None
    backup = _backup(plan.destination, backup_dir, backup_root)
    write(plan, prior_mode)
    return _Applied(
        status=status, destination=plan.destination, backup=backup, prior_mode=prior_mode
    )


def remove_paths(paths: Sequence[Path], *, dry_run: bool) -> InstallReport:
    """Remove files and directory trees; missing paths are reported as skips."""
    report = InstallReport()
    for path in paths:
        if not path.exists():
            report.entries.append(('skip', path))
            continue
        report.entries.append(('remove', path))
        if dry_run:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    return report
