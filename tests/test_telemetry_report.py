"""Tests for the telemetry report and prune tool."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts.telemetry_report import prune

SCRIPT = Path(__file__).resolve().parent.parent / 'scripts' / 'telemetry_report.py'


def _run_report(cwd, *args):
    return subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _seed(tmp_path: Path) -> Path:
    am = tmp_path / '.agentmaster'
    (am / 'compaction-snapshots').mkdir(parents=True)
    (am / '.starts').mkdir()
    lines = [f'hook,scout,,{n},{n}\n' for n in range(600)]
    (am / 'telemetry.md').write_text(''.join(lines), encoding='utf-8')
    for n in range(7):
        snap = am / 'compaction-snapshots' / f'20260101-00000{n}'
        snap.mkdir()
        (snap / 'ledger.md').write_text('x', encoding='utf-8')
    stale = am / '.starts' / 'old-agent'
    stale.write_text('1.0', encoding='utf-8')
    os.utime(stale, (time.time() - 90000, time.time() - 90000))
    (am / '.starts' / 'fresh-agent').write_text(str(time.time()), encoding='utf-8')
    return am


def test_prune_trims_lines_snapshots_and_stale_starts(tmp_path):
    am = _seed(tmp_path)

    actions = prune(am, keep_lines=500, keep_snapshots=5, dry_run=False)

    kept = (am / 'telemetry.md').read_text(encoding='utf-8').splitlines()
    assert len(kept) == 500
    assert kept[-1] == 'hook,scout,,599,599'  # newest lines survive
    snaps = sorted(p.name for p in (am / 'compaction-snapshots').iterdir())
    assert snaps == [f'20260101-00000{n}' for n in range(2, 7)]
    assert not (am / '.starts' / 'old-agent').exists()
    assert (am / '.starts' / 'fresh-agent').exists()
    assert len(actions) == 4  # 1 telemetry + 2 snapshots + 1 stale start


def test_prune_dry_run_changes_nothing(tmp_path):
    am = _seed(tmp_path)

    actions = prune(am, keep_lines=500, keep_snapshots=5, dry_run=True)

    assert actions  # same actions reported...
    assert len((am / 'telemetry.md').read_text().splitlines()) == 600
    assert len(list((am / 'compaction-snapshots').iterdir())) == 7
    assert (am / '.starts' / 'old-agent').exists()


def test_prune_nothing_to_do(tmp_path):
    am = tmp_path / '.agentmaster'
    am.mkdir()
    (am / 'telemetry.md').write_text('hook,scout,,1,1\n', encoding='utf-8')

    assert prune(am, keep_lines=500, keep_snapshots=5, dry_run=False) == []


def test_prune_missing_dir_is_noop(tmp_path):
    assert (
        prune(tmp_path / 'absent', keep_lines=500, keep_snapshots=5, dry_run=False) == []
    )


@pytest.mark.subprocess
def test_cli_prune_dry_run_prints_would(tmp_path):
    _seed(tmp_path)

    result = _run_report(tmp_path, '--prune', '--dry-run')

    assert result.returncode == 0, result.stderr
    assert 'would' in result.stdout
    assert (
        len((tmp_path / '.agentmaster' / 'telemetry.md').read_text().splitlines()) == 600
    )


@pytest.mark.subprocess
def test_report_summarizes_per_agent(tmp_path):
    am = tmp_path / '.agentmaster'
    am.mkdir()
    (am / 'telemetry.md').write_text(
        'hook,scout,,120,3000\n'
        'hook,scout,,80,1000\n'
        'hook,implementer,,,\n'
        'not a telemetry line\n'
    )

    result = _run_report(tmp_path)

    assert result.returncode == 0, result.stderr
    assert 'scout' in result.stdout
    assert '200' in result.stdout
    assert 'implementer' in result.stdout


@pytest.mark.subprocess
def test_report_summarizes_phases_and_models(tmp_path):
    am = tmp_path / '.agentmaster'
    am.mkdir()
    (am / 'telemetry.md').write_text(
        'hook,scout,,120,3000\n'
        'plan,scout,claude-haiku-4-5,100,2000\n'
        'plan,code-analyst,claude-sonnet-4-6,50,1000\n'
        'review,implementer,claude-sonnet-4-6,25,500\n'
    )

    result = _run_report(tmp_path)

    assert result.returncode == 0, result.stderr
    assert 'phase' in result.stdout
    assert 'plan' in result.stdout
    assert 'review' in result.stdout
    assert 'model' in result.stdout
    assert 'claude-haiku-4-5' in result.stdout
    assert '150' in result.stdout  # plan-phase token subtotal


def test_prune_removes_stale_phase_marker(tmp_path):
    am = tmp_path / '.agentmaster'
    am.mkdir()
    (am / 'telemetry.md').write_text('hook,scout,,1,1\n', encoding='utf-8')
    marker = am / '.phase'
    marker.write_text('plan\n', encoding='utf-8')
    os.utime(marker, (time.time() - 90000, time.time() - 90000))

    actions = prune(am, keep_lines=500, keep_snapshots=5, dry_run=False)

    assert actions == ['.phase: remove stale phase marker']
    assert not marker.exists()


@pytest.mark.subprocess
def test_report_missing_file_exits_one(tmp_path):
    result = _run_report(tmp_path)

    assert result.returncode == 1
    assert 'telemetry' in result.stderr.lower()
