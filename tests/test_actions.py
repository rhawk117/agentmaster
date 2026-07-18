"""Tests for the transactional installer actions core."""

from typing import TYPE_CHECKING

import pytest

from installer.actions import FilePlan, apply_plans, remove_paths

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

    assert report.summary() == 'created 1, updated 1, skipped 0, removed 0'
