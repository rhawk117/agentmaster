"""Transactional file actions for the agentmaster installer.

`apply_plans` classifies every planned file before touching the filesystem
(create / update / skip), backs up files it is about to change, and writes
each file atomically (temp file + `os.replace`). `dry_run` performs the
classification and reporting only.
"""

import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

type Status = Literal['create', 'update', 'skip', 'remove']


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
        counts = dict.fromkeys(('create', 'update', 'skip', 'remove'), 0)
        for status, _ in self.entries:
            counts[status] += 1
        return (
            f'created {counts["create"]}, updated {counts["update"]}, '
            f'skipped {counts["skip"]}, removed {counts["remove"]}'
        )


def _classify(plan: FilePlan) -> Status:
    if not plan.destination.exists():
        return 'create'
    if plan.destination.read_text(encoding='utf-8') != plan.content:
        return 'update'
    return 'skip'


def _backup(destination: Path, backup_dir: Path, backup_root: Path) -> None:
    try:
        relative = destination.relative_to(backup_root)
    except ValueError:
        relative = Path(destination.name)
    target = backup_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(destination, target)


def _write_atomic(plan: FilePlan) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=plan.destination.parent, suffix='.tmp')
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(plan.content)
        if plan.executable:
            tmp.chmod(0o755)
        tmp.replace(plan.destination)
    finally:
        tmp.unlink(missing_ok=True)


def apply_plans(
    plans: Sequence[FilePlan], *, backup_root: Path, dry_run: bool
) -> InstallReport:
    """Install every plan, or report what would happen when `dry_run`.

    Classification happens for all plans before any write; parent
    directories are created for all plans before the first file is
    written, so an uncreatable parent aborts with nothing installed.
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

    updates = [plan for plan, status in pending if status == 'update']
    if updates:
        backup_dir = backup_root / time.strftime('agentmaster-backup-%Y%m%d-%H%M%S')
        backup_dir.mkdir(parents=True, exist_ok=True)
        for plan in updates:
            _backup(plan.destination, backup_dir, backup_root)
        report.backup_dir = backup_dir

    for plan, _ in pending:
        _write_atomic(plan)
    return report


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
