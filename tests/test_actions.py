"""Tests for the transactional installer actions core."""

from typing import TYPE_CHECKING

import pytest

import installer.actions as actions_module
from installer.actions import BatchRollbackError, FilePlan, apply_plans, remove_paths

if TYPE_CHECKING:
    from pathlib import Path


def _plan(tmp_path: Path, name: str, content: str) -> FilePlan:
    return FilePlan(content=content, destination=tmp_path / 'home' / name)


def test_fresh_install_creates_all(tmp_path: Path, statuses) -> None:
    plans = [_plan(tmp_path, 'a.md', 'alpha\n'), _plan(tmp_path, 'sub/b.md', 'beta\n')]

    report = apply_plans(plans, backup_root=tmp_path / 'home', dry_run=False)

    assert statuses(report.entries) == ['create', 'create']
    assert (tmp_path / 'home' / 'a.md').read_text() == 'alpha\n'
    assert (tmp_path / 'home' / 'sub' / 'b.md').read_text() == 'beta\n'
    assert report.backup_dir is None


def test_rerun_identical_skips_all(tmp_path: Path, statuses) -> None:
    plans = [_plan(tmp_path, 'a.md', 'alpha\n')]
    apply_plans(plans, backup_root=tmp_path / 'home', dry_run=False)

    report = apply_plans(plans, backup_root=tmp_path / 'home', dry_run=False)

    assert statuses(report.entries) == ['skip']
    assert report.backup_dir is None


def test_update_backs_up_original(tmp_path: Path, statuses) -> None:
    home = tmp_path / 'home'
    apply_plans([_plan(tmp_path, 'a.md', 'original\n')], backup_root=home, dry_run=False)

    report = apply_plans(
        [_plan(tmp_path, 'a.md', 'changed\n')], backup_root=home, dry_run=False
    )

    assert statuses(report.entries) == ['update']
    assert (home / 'a.md').read_text() == 'changed\n'
    assert report.backup_dir is not None
    assert report.backup_dir.name.startswith('agentmaster-backup-')
    assert (report.backup_dir / 'a.md').read_text() == 'original\n'


def test_dry_run_reports_without_writing(tmp_path: Path, statuses) -> None:
    home = tmp_path / 'home'
    plans = [_plan(tmp_path, 'a.md', 'alpha\n')]

    report = apply_plans(plans, backup_root=home, dry_run=True)

    assert statuses(report.entries) == ['create']
    assert not home.exists()


def test_dry_run_update_leaves_file_and_makes_no_backup(tmp_path: Path, statuses) -> None:
    home = tmp_path / 'home'
    apply_plans([_plan(tmp_path, 'a.md', 'original\n')], backup_root=home, dry_run=False)

    report = apply_plans(
        [_plan(tmp_path, 'a.md', 'changed\n')], backup_root=home, dry_run=True
    )

    assert statuses(report.entries) == ['update']
    assert (home / 'a.md').read_text() == 'original\n'
    assert report.backup_dir is None


def test_uncreatable_parent_raises_before_any_write(tmp_path: Path) -> None:
    home = tmp_path / 'home'
    home.mkdir()
    (home / 'blocker').write_text('a file where a directory is needed\n')
    plans = [
        _plan(tmp_path, 'ok.md', 'fine\n'),
        FilePlan(content='nope\n', destination=home / 'blocker' / 'c.md'),
    ]

    with pytest.raises((NotADirectoryError, FileExistsError)):
        apply_plans(plans, backup_root=home, dry_run=False)

    assert not (home / 'ok.md').exists()


def test_executable_plans_get_execute_bit(tmp_path: Path) -> None:
    plan = FilePlan(
        content='print("hi")\n',
        destination=tmp_path / 'home' / 'hook.py',
        executable=True,
    )

    apply_plans([plan], backup_root=tmp_path / 'home', dry_run=False)

    mode = (tmp_path / 'home' / 'hook.py').stat().st_mode
    assert mode & 0o111


def test_remove_paths_removes_files_dirs_and_skips_missing(
    tmp_path: Path, statuses
) -> None:
    target_file = tmp_path / 'a.md'
    target_file.write_text('x\n')
    target_dir = tmp_path / 'skill'
    (target_dir / 'nested').mkdir(parents=True)
    (target_dir / 'nested' / 'f.md').write_text('y\n')
    missing = tmp_path / 'not-there.md'

    report = remove_paths([target_file, target_dir, missing], dry_run=False)

    assert statuses(report.entries) == ['remove', 'remove', 'skip']
    assert not target_file.exists()
    assert not target_dir.exists()


def test_remove_paths_dry_run_removes_nothing(tmp_path: Path, statuses) -> None:
    target = tmp_path / 'a.md'
    target.write_text('x\n')

    report = remove_paths([target], dry_run=True)

    assert statuses(report.entries) == ['remove']
    assert target.exists()


def test_summary_counts_by_status(tmp_path: Path) -> None:
    home = tmp_path / 'home'
    apply_plans([_plan(tmp_path, 'a.md', 'one\n')], backup_root=home, dry_run=False)

    report = apply_plans(
        [_plan(tmp_path, 'a.md', 'two\n'), _plan(tmp_path, 'b.md', 'new\n')],
        backup_root=home,
        dry_run=False,
    )

    assert (
        report.summary() == 'created 1, updated 1, mode-changed 0, skipped 0, removed 0'
    )


def test_backup_dir_collides_retries_with_next_suffix(tmp_path: Path) -> None:
    home = tmp_path / 'home'
    apply_plans([_plan(tmp_path, 'a.md', 'v1\n')], backup_root=home, dry_run=False)
    # Simulate a pre-existing backup dir from a concurrent/prior run that
    # happens to pick the same first candidate name.
    (home / 'agentmaster-backup-collides').mkdir(parents=True)
    suffixes = iter(['collides', 'unique'])

    report = apply_plans(
        [_plan(tmp_path, 'a.md', 'v2\n')],
        backup_root=home,
        dry_run=False,
        suffix_provider=lambda: next(suffixes),
    )

    assert report.backup_dir == home / 'agentmaster-backup-unique'
    assert report.backup_dir is not None
    assert (report.backup_dir / 'a.md').read_text() == 'v1\n'


def test_update_preserves_destination_permissions(tmp_path: Path) -> None:
    home = tmp_path / 'home'
    apply_plans([_plan(tmp_path, 'a.md', 'v1\n')], backup_root=home, dry_run=False)
    (home / 'a.md').chmod(0o640)

    apply_plans([_plan(tmp_path, 'a.md', 'v2\n')], backup_root=home, dry_run=False)

    assert (home / 'a.md').stat().st_mode & 0o777 == 0o640


def test_mode_only_change_adds_execute_bit_without_backup(
    tmp_path: Path, statuses
) -> None:
    home = tmp_path / 'home'
    apply_plans([_plan(tmp_path, 'a.md', 'same\n')], backup_root=home, dry_run=False)

    plan = FilePlan(content='same\n', destination=home / 'a.md', executable=True)
    report = apply_plans([plan], backup_root=home, dry_run=False)

    assert statuses(report.entries) == ['mode']
    assert report.backup_dir is None
    assert (home / 'a.md').read_text() == 'same\n'
    assert (home / 'a.md').stat().st_mode & 0o111


def test_mode_only_change_removes_execute_bit(tmp_path: Path, statuses) -> None:
    home = tmp_path / 'home'
    exec_plan = FilePlan(content='same\n', destination=home / 'a.md', executable=True)
    apply_plans([exec_plan], backup_root=home, dry_run=False)

    non_exec_plan = FilePlan(
        content='same\n', destination=home / 'a.md', executable=False
    )
    report = apply_plans([non_exec_plan], backup_root=home, dry_run=False)

    assert statuses(report.entries) == ['mode']
    assert not (home / 'a.md').stat().st_mode & 0o111


def test_mid_batch_failure_rolls_back_prior_writes(tmp_path: Path) -> None:
    home = tmp_path / 'home'
    apply_plans([_plan(tmp_path, 'a.md', 'original\n')], backup_root=home, dry_run=False)

    def flaky_write(plan: FilePlan, prior_mode: int | None) -> None:
        if plan.destination.name == 'c.md':
            raise OSError('disk full (simulated)')
        actions_module._write_atomic(plan, prior_mode)

    plans = [
        _plan(tmp_path, 'a.md', 'changed\n'),  # update — must be restored
        _plan(tmp_path, 'b.md', 'new\n'),  # create — must be deleted
        _plan(tmp_path, 'c.md', 'fails\n'),  # fails before ever being written
    ]

    with pytest.raises(OSError, match='disk full'):
        apply_plans(plans, backup_root=home, dry_run=False, write=flaky_write)

    assert (home / 'a.md').read_text() == 'original\n'
    assert not (home / 'b.md').exists()
    assert not (home / 'c.md').exists()


def test_rollback_reports_unrestored_paths_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / 'home'
    apply_plans([_plan(tmp_path, 'a.md', 'original\n')], backup_root=home, dry_run=False)

    original_backup = actions_module._backup

    def backup_then_lose_it(destination, backup_dir, backup_root):
        target = original_backup(destination, backup_dir, backup_root)
        target.unlink()  # simulate the backup becoming unavailable before rollback
        return target

    monkeypatch.setattr(actions_module, '_backup', backup_then_lose_it)

    def flaky_write(plan: FilePlan, prior_mode: int | None) -> None:
        if plan.destination.name == 'b.md':
            raise OSError('simulated failure')
        actions_module._write_atomic(plan, prior_mode)

    plans = [_plan(tmp_path, 'a.md', 'changed\n'), _plan(tmp_path, 'b.md', 'fails\n')]

    with pytest.raises(BatchRollbackError) as exc_info:
        apply_plans(plans, backup_root=home, dry_run=False, write=flaky_write)

    error = exc_info.value
    assert home / 'a.md' in error.unrestored
    assert isinstance(error.original, OSError)
