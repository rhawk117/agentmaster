# Release Workflow, Entry-Point Cleanup, Makefile, and Telemetry Pruning — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Work happens on the existing `worktree-agentmaster-consolidation` branch (tracking `origin/feat/agentmaster-consolidation`, PR #2).

**Goal:** Make agentmaster releasable and maintainable: a tag-gated GitHub release with an install bundle, `install.py`/`make` as the only entry points (shell wrappers deleted), a manual telemetry prune command, a consolidated pytest suite with shared fixtures and registered markers, and a README that explains all of it.

**Architecture:** The release is a quality-gated immutable tag: pushing `v*` re-runs the full gate, checks the tag against `pyproject.toml`, builds a runtime-only `git archive` bundle, and publishes a GitHub Release with auto-generated notes. Locally, a Makefile is a thin façade over `scripts/code-quality.sh` and `install.py` (CI keeps calling the script directly). Telemetry cleanup is a manual `--prune` mode on `scripts/telemetry_report.py` — hooks never delete data. Test consolidation moves the six duplicated helpers into `tests/conftest.py` fixtures and registers a `subprocess` marker with `--strict-markers`.

**Tech Stack:** Python 3.14 stdlib (runtime), `uv` + `pytest` + `ruff` + `ty` + `bashate` (dev), GNU make (optional convenience), GitHub Actions + `gh` CLI (release).

## Global Constraints

- Python `>=3.14`; `install.py`, `installer/`, `hooks/`, `scripts/*.py` stay **stdlib only**.
- Package manager is `uv`; run tools as `uv run <tool>`; tests with `uv run pytest`.
- Style: single quotes, line length 90, frozen dataclasses, DI via default args — ruff config is authoritative; every Python change must pass `uv run ruff format --check` and `uv run ruff check --no-fix`.
- Commit format: `<feat|chore|fix>(<scope>): short summary` (scopes here: `tests`, `scripts`, `make`, `ci`, `docs`), ending with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- The quality gate stays check-only; only `code-quality.sh format` mutates. CI (`quality.yml`) is untouched and keeps calling `bash scripts/code-quality.sh all`.
- `scripts/code-quality.sh` and `scripts/log.sh` are the only shell scripts that remain; bashate keeps ignoring `E003,E006`.
- Hooks never delete or rewrite telemetry artifacts; pruning is manual-command-only.
- Preserve behavior everywhere not named by a task: same installed destinations, telemetry line format `hook,<agent>,,<tokens>,<duration_ms>`, same env vars, same CLI flags on `install.py`.
- Dev-environment note: ruff/ty/bashate/pytest run via WSL Ubuntu on this machine (Windows ASR blocks the native executables); git runs from Windows Git Bash. `make` verification may also need WSL.

## Measured Outcomes

Complete only when every row passes from the branch head:

| # | Command | Expected |
|---|---------|----------|
| 1 | `bash scripts/code-quality.sh all` | exit 0 (ruff, bashate, ty, pytest, validate all green) |
| 2 | `uv run pytest tests/ -m "not subprocess" -q` then `-m subprocess -q` | both exit 0; the two subsets partition the suite; total count ≥ 90 |
| 3 | `uv run pytest --markers \| grep subprocess` | the registered `subprocess` marker is listed; `--strict-markers` is in effect (an unregistered marker fails collection) |
| 4 | `git ls-files '*.sh'` | exactly `scripts/code-quality.sh` and `scripts/log.sh` |
| 5 | `git grep -l "install-claude.sh\|install-copilot.sh\|sync-criteria.sh\|telemetry-report.sh"` | no matches anywhere in the tree |
| 6 | `make -n check` | prints `bash scripts/code-quality.sh all`, exit 0 (Makefile syntax valid) |
| 7 | Seed a fake `.agentmaster/` (600 telemetry lines, 7 snapshots, 1 stale + 1 fresh `.starts` entry), run `uv run python scripts/telemetry_report.py --prune` | telemetry.md has exactly 500 lines (the newest), 5 newest snapshots remain, stale start gone, fresh start kept; a prior `--dry-run` run printed the same actions but changed nothing |
| 8 | Local simulation of release steps: version-check snippet with matching and mismatching tags; `git archive` bundle command | mismatch exits 1; bundle zip contains `install.py` and `shared/`, contains no `tests/` or `.github/` |
| 9 | `python install.py validate --target all` | exit 0 (doc/skill edits did not disturb parity or criteria sync) |

## Execution Order

Sequential Tasks 1 → 7. (Task 1 and Task 2 both edit `tests/test_hooks.py`; Task 4 needs Task 2's `--prune` and Task 3's wrapper removal; Task 6 documents everything before it.) If dispatching subagents, one per task, reviewed between tasks.

## File Structure

```
Makefile                              # new — thin façade
.github/workflows/release.yml         # new — tag-gated release
scripts/telemetry_report.py           # gains prune() + argparse CLI
scripts/code-quality.sh               # SHELL_SCRIPTS shrinks
tests/conftest.py                     # new — shared fixtures
tests/test_telemetry_report.py        # new — report tests move here + prune tests
README.md                             # rewritten
Deleted: install-claude.sh, install-copilot.sh,
         scripts/sync-criteria.sh, scripts/telemetry-report.sh
```

---

### Task 1: Registered pytest markers + `tests/conftest.py` fixtures

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/conftest.py`
- Modify: `tests/test_actions.py`, `tests/test_claude_target.py`, `tests/test_copilot_target.py`, `tests/test_hooks.py`, `tests/test_parity.py`
- Untouched: `tests/test_hooklib.py` (no duplicated helpers, no subprocesses)

**Interfaces (produces — later tasks and all test files rely on these exact names):**
- Marker `subprocess` (registered, strict).
- Fixtures in `tests/conftest.py`: `repo_root: Path` (session-scoped), `repo_copy: Path` (function-scoped tmp copy of the repo), `statuses` (callable `entries -> list[str]`), `make_manifest` (callable `(**overrides) -> Manifest`), `run_cli` (callable `(args, cwd, env_extra=None) -> CompletedProcess`), `run_hook` (callable `(name, payload, env=None, raw=None) -> CompletedProcess`, cwd bound to `tmp_path`).

- [ ] **Step 1: Register the marker and strict mode** in `pyproject.toml` — replace the `[tool.pytest.ini_options]` table with:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
addopts = "--strict-markers"
markers = [
    "subprocess: test spawns Python subprocesses (slower; deselect with -m 'not subprocess')",
]
```

- [ ] **Step 2: Verify strict mode bites** — add `@pytest.mark.subprocess` to one test in `tests/test_hooks.py`, run `uv run pytest tests/test_hooks.py -q`: passes. Temporarily change it to `@pytest.mark.subproces` (typo) and rerun: collection error. Restore. This is the RED evidence that `--strict-markers` works.

- [ ] **Step 3: Write `tests/conftest.py`** — consolidates the helpers currently duplicated across five files (`_statuses` ×3, `_fake_manifest` ×3, `_copy_repo`, `_run_cli`, `_run`):

```python
"""Shared fixtures for the agentmaster test suite."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from installer.manifest import Manifest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope='session')
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    """A disposable copy of the repository tree, sans VCS and caches."""
    dest = tmp_path / 'repo'
    shutil.copytree(
        REPO_ROOT,
        dest,
        ignore=shutil.ignore_patterns(
            '.git', '.venv', '__pycache__', '.superpowers', '.agentmaster'
        ),
    )
    return dest


@pytest.fixture(scope='session')
def statuses():
    def _statuses(entries) -> list[str]:
        return [status for status, _ in entries]

    return _statuses


@pytest.fixture
def make_manifest():
    """Factory for fake Manifests; every field defaults to empty."""

    def _make(**overrides) -> Manifest:
        fields: dict = {
            'workers': (),
            'claude_skills': (),
            'copilot_coordinators': (),
            'claude_only_agents': (),
            'claude_hooks': (),
            'copilot_hooks': (),
            'claude_frontmatter': {},
            'copilot_frontmatter': {},
            'substitutions': {},
        }
        fields.update(overrides)
        return Manifest(**fields)

    return _make


@pytest.fixture
def run_cli():
    def _run(args, cwd, env_extra=None):
        env = dict(os.environ)
        env.update(env_extra or {})
        return subprocess.run(  # noqa: S603
            [sys.executable, 'install.py', *args],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    return _run


@pytest.fixture
def run_hook(tmp_path: Path):
    def _run(name, payload, env=None, raw=None):
        stdin = raw if raw is not None else json.dumps(payload)
        return subprocess.run(  # noqa: S603
            [sys.executable, str(REPO_ROOT / 'hooks' / f'{name}.py')],
            input=stdin,
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env=env,
            check=False,
        )

    return _run
```

- [ ] **Step 4: Refactor the five test files** — purely mechanical, no assertion changes:
  - `tests/test_hooks.py`: add `pytestmark = pytest.mark.subprocess` after imports (every test here shells out); delete `_HOOKS` and `_run`; every test gains a `run_hook` parameter and calls `run_hook(name, payload)` / `run_hook(name, payload, env=env)` / `run_hook(name, None, raw='not json')` — dropping the old explicit `tmp_path` argument (the fixture binds it; tests that seed files under `tmp_path` keep their `tmp_path` parameter). Leave `_run_report` and its two tests alone — Task 2 moves them.
  - `tests/test_parity.py`: delete `_copy_repo` and `_run_cli`; the five CLI tests get `@pytest.mark.subprocess` and a `run_cli` parameter; every `_copy_repo(tmp_path)` becomes the `repo_copy` fixture parameter; `REPO_ROOT` module constant is replaced by the conftest fixture where used inside tests, and `_seed_shared_bodies` becomes a local fixture:

```python
@pytest.fixture
def seed_shared_bodies(repo_root):
    def _seed(root, names):
        (root / 'shared' / 'agents').mkdir(parents=True, exist_ok=True)
        for name in names:
            source = repo_root / 'shared' / 'agents' / f'{name}.md'
            (root / 'shared' / 'agents' / f'{name}.md').write_text(
                source.read_text(encoding='utf-8'), encoding='utf-8'
            )

    return _seed
```

  (Module-level tests like `test_rendered_matches_committed_files` that used `REPO_ROOT` take the `repo_root` fixture instead. `PLATFORMS` stays.)
  - `tests/test_claude_target.py` and `tests/test_copilot_target.py`: delete `ROOT`, `_statuses`, `_fake_manifest`; tests take `repo_root` and `statuses` fixtures (`install(repo_root, home, ...)`, `statuses(report.entries)`); `_fake_manifest()` call sites become `make_manifest(...)` with the same field values the deleted helper had, e.g. in `test_claude_target.py`:

```python
manifest = make_manifest(
    workers=('scout',),
    claude_skills=('myskill',),
    claude_hooks=('myhook.py',),
    claude_frontmatter={'scout': 'name: scout\nmodel: haiku\n'},
)
```

  and in `test_copilot_target.py`:

```python
manifest = make_manifest(
    workers=('scout',),
    copilot_coordinators=('co',),
    copilot_hooks=('myhook.py',),
    copilot_frontmatter={'scout': 'name: scout\nmodel: claude-haiku-4.5\n'},
    substitutions={'%USES_RULE%': {'claude': 'x', 'copilot': 'y'}},
)
```

  `_build_fake_root` helpers stay (they differ per platform).
  - `tests/test_actions.py`: delete `_statuses`; tests take the `statuses` fixture. `_plan` stays (trivial, actions-specific).

- [ ] **Step 5: Full suite green, same behavior** — `uv run pytest tests/ -q`: all pass, count unchanged (84). Then `uv run pytest -m subprocess -q` and `-m "not subprocess" -q`: both nonzero counts, sum = total. `uv run ruff check tests/ --no-fix` and `uv run ruff format tests/ --check`: clean.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/
git commit -m "chore(tests): shared conftest fixtures and registered subprocess marker"
```

### Task 2: Telemetry pruning (`telemetry_report.py --prune`)

**Files:**
- Modify: `scripts/telemetry_report.py`
- Create: `tests/test_telemetry_report.py`
- Modify: `tests/test_hooks.py` (remove `_TELEMETRY_REPORT`, `_run_report`, and the two report tests — they move)

**Interfaces:**
- Consumes: fixtures from Task 1 (`repo_root`).
- Produces: `prune(am_dir: Path, *, keep_lines: int, keep_snapshots: int, dry_run: bool) -> list[str]` (human-readable action strings; empty = nothing to prune) and the CLI `telemetry_report.py [FILE] [--prune] [--keep-lines N] [--keep-snapshots N] [--dry-run]`. Task 4's `make clean-telemetry` calls `--prune`.

Prune policy (from the approved design): keep the newest `--keep-lines` (default 500) telemetry lines, rewritten atomically; keep the newest `--keep-snapshots` (default 5) `compaction-snapshots/` dirs ordered by directory name (they are `YYYYmmdd-HHMMSS` timestamps); delete `.starts/` files older than 24 h by mtime (orphans from crashed sessions — live entries are seconds old). Report mode is unchanged, including `no telemetry file … run agentmaster first` on stderr + exit 1.

- [ ] **Step 1: Write the failing tests** — `tests/test_telemetry_report.py`:

```python
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
    assert prune(tmp_path / 'absent', keep_lines=500, keep_snapshots=5, dry_run=False) == []


@pytest.mark.subprocess
def test_cli_prune_dry_run_prints_would(tmp_path):
    _seed(tmp_path)

    result = _run_report(tmp_path, '--prune', '--dry-run')

    assert result.returncode == 0, result.stderr
    assert 'would' in result.stdout
    assert len((tmp_path / '.agentmaster' / 'telemetry.md').read_text().splitlines()) == 600


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
def test_report_missing_file_exits_one(tmp_path):
    result = _run_report(tmp_path)

    assert result.returncode == 1
    assert 'telemetry' in result.stderr.lower()
```

(The last two tests are moved verbatim from `tests/test_hooks.py` — delete `_TELEMETRY_REPORT`, `_run_report`, `test_telemetry_report_summarizes_per_agent`, and `test_telemetry_report_missing_file_exits_one` there in the same change.)

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_telemetry_report.py -v`. Expected: ImportError (`cannot import name 'prune'`).

- [ ] **Step 3: Implement** — in `scripts/telemetry_report.py`, extend the module docstring with one prune sentence, add `import argparse`, `import shutil`, `import time`, keep `summarize` untouched, add:

```python
def _prune_telemetry(am_dir: Path, keep_lines: int, *, dry_run: bool) -> list[str]:
    telemetry = am_dir / 'telemetry.md'
    if not telemetry.is_file():
        return []
    lines = telemetry.read_text(encoding='utf-8').splitlines(keepends=True)
    excess = len(lines) - keep_lines
    if excess <= 0:
        return []
    if not dry_run:
        tmp = telemetry.with_name('telemetry.md.tmp')
        tmp.write_text(''.join(lines[-keep_lines:]), encoding='utf-8')
        tmp.replace(telemetry)
    return [f'telemetry.md: drop {excess} oldest of {len(lines)} lines']


def _prune_snapshots(am_dir: Path, keep_snapshots: int, *, dry_run: bool) -> list[str]:
    snapshots = am_dir / 'compaction-snapshots'
    if not snapshots.is_dir():
        return []
    dirs = sorted(p for p in snapshots.iterdir() if p.is_dir())
    stale = dirs[:-keep_snapshots] if keep_snapshots > 0 else dirs
    if not dry_run:
        for path in stale:
            shutil.rmtree(path)
    return [f'compaction-snapshots/{path.name}: remove' for path in stale]


def _prune_starts(am_dir: Path, *, dry_run: bool) -> list[str]:
    starts = am_dir / '.starts'
    if not starts.is_dir():
        return []
    cutoff = time.time() - 24 * 60 * 60
    stale = sorted(
        p for p in starts.iterdir() if p.is_file() and p.stat().st_mtime < cutoff
    )
    if not dry_run:
        for path in stale:
            path.unlink()
    return [f'.starts/{path.name}: remove stale entry' for path in stale]


def prune(
    am_dir: Path, *, keep_lines: int, keep_snapshots: int, dry_run: bool
) -> list[str]:
    """Prune telemetry artifacts under `am_dir`; return the actions taken."""
    return [
        *_prune_telemetry(am_dir, keep_lines, dry_run=dry_run),
        *_prune_snapshots(am_dir, keep_snapshots, dry_run=dry_run),
        *_prune_starts(am_dir, dry_run=dry_run),
    ]
```

and replace `main` with an argparse CLI (default path and report behavior unchanged):

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Report or prune agentmaster telemetry.')
    parser.add_argument(
        'path',
        nargs='?',
        type=Path,
        default=Path('.agentmaster') / 'telemetry.md',
        help='telemetry file (default: .agentmaster/telemetry.md)',
    )
    parser.add_argument(
        '--prune', action='store_true', help='prune old telemetry artifacts'
    )
    parser.add_argument('--keep-lines', type=int, default=500)
    parser.add_argument('--keep-snapshots', type=int, default=5)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if args.prune:
        actions = prune(
            args.path.parent,
            keep_lines=args.keep_lines,
            keep_snapshots=args.keep_snapshots,
            dry_run=args.dry_run,
        )
        if not actions:
            print('nothing to prune')
            return 0
        prefix = 'would ' if args.dry_run else ''
        for action in actions:
            print(prefix + action)
        return 0
    if not args.path.is_file():
        print(f'no telemetry file at {args.path} - run agentmaster first', file=sys.stderr)
        return 1
    print(summarize(args.path))
    return 0
```

- [ ] **Step 4: Run tests to verify pass** — `uv run pytest tests/test_telemetry_report.py tests/test_hooks.py -v`: all pass. Full suite: `uv run pytest tests/ -q` (count grows by the 5 new tests). Ruff clean on both changed files.

- [ ] **Step 5: Commit**

```bash
git add scripts/telemetry_report.py tests/test_telemetry_report.py tests/test_hooks.py
git commit -m "feat(scripts): telemetry prune mode with retention flags"
```

### Task 3: Remove the four shell wrappers and their references

**Files:**
- Delete: `install-claude.sh`, `install-copilot.sh`, `scripts/sync-criteria.sh`, `scripts/telemetry-report.sh`
- Modify: `scripts/code-quality.sh:13-15`, `copilot/README.md:27,60,84`, `copilot/skills/agentmaster-plan/SKILL.md:14`, `copilot/skills/agentmaster-execute/SKILL.md:13`, `copilot/skills/agentmaster-review/SKILL.md:12`, `installer/claude.py:3`, `installer/copilot.py:5`

- [ ] **Step 1: Delete the wrappers**

```bash
git rm install-claude.sh install-copilot.sh scripts/sync-criteria.sh scripts/telemetry-report.sh
```

- [ ] **Step 2: Shrink the bashate scope** — in `scripts/code-quality.sh` replace:

```bash
SHELL_SCRIPTS=(install-claude.sh install-copilot.sh scripts/*.sh)
```

with:

```bash
SHELL_SCRIPTS=(scripts/*.sh)
```

(the glob now matches only `code-quality.sh` and `log.sh`; the comment above it stays accurate).

- [ ] **Step 3: Update every remaining reference** (Measured Outcome 5 demands zero matches):
  - `copilot/README.md`: `./install-copilot.sh` → `python install.py install --target copilot`; `run \`./sync-criteria.sh\`` → `run \`python install.py sync\``; the line 84 sentence starting `` `install-copilot.sh` writes `` → `` `install.py` writes ``.
  - The three `copilot/skills/*/SKILL.md` files: `install-copilot.sh` → `python install.py install --target copilot` (same sentence shape: "tell the user to run … from the agentmaster bundle"). These files carry no criteria markers, so parity validation is unaffected — Step 4 proves it.
  - `installer/claude.py` docstring: `Ports the behaviour of \`install-claude.sh\` (lines 81-135):` → `Ports the behaviour of the retired shell installer (install-claude.sh):`; `installer/copilot.py` docstring: `Ported from \`install-copilot.sh\` (lines 124-177):` → `Ported from the retired shell installer (install-copilot.sh):`. (The names stay greppable as history, but see next line.) **Correction — Outcome 5 requires zero grep hits:** use `Ports the behaviour of the retired shell installer:` and `Ported from the retired shell installer:` with no filename.

- [ ] **Step 4: Verify**

```bash
git grep -l "install-claude.sh\|install-copilot.sh\|sync-criteria.sh\|telemetry-report.sh"   # no output
bash scripts/code-quality.sh all                                                             # exit 0
```

(The gate run covers bashate on the shrunk list, the full pytest suite — no test referenced the wrappers — and `install.py validate --target all` proving the SKILL.md edits broke nothing.)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(scripts): remove shell wrapper entry points"
```

### Task 4: Makefile façade

**Files:**
- Create: `Makefile`

**Interfaces:**
- Consumes: `scripts/code-quality.sh` commands (lint/shell/typecheck/test/validate/format/all), `install.py` subcommands, Task 2's `telemetry_report.py --prune`.
- Produces: the `make` targets the README (Task 6) documents.

- [ ] **Step 1: Write the Makefile** (recipes are TAB-indented — a Makefile with spaces fails immediately):

```make
# Thin façade over scripts/code-quality.sh and install.py.
# CI calls the script directly; these targets exist for humans.

.DEFAULT_GOAL := help

.PHONY: help check lint shell typecheck test format validate sync \
	install install-claude install-copilot uninstall telemetry clean-telemetry

help:  ## List available targets
	@grep -E '^[a-z][a-z-]*:.*##' $(MAKEFILE_LIST) | \
		awk -F':.*## ' '{printf "  %-18s %s\n", $$1, $$2}'

check:  ## Full quality gate (same command CI runs)
	bash scripts/code-quality.sh all

lint:  ## ruff format --check + ruff check
	bash scripts/code-quality.sh lint

shell:  ## bashate over the maintained shell scripts
	bash scripts/code-quality.sh shell

typecheck:  ## ty
	bash scripts/code-quality.sh typecheck

test:  ## compileall + pytest
	bash scripts/code-quality.sh test

format:  ## Mutating: ruff format + ruff check --fix (local only)
	bash scripts/code-quality.sh format

validate:  ## Installer parity + criteria drift validation
	bash scripts/code-quality.sh validate

sync:  ## Regenerate worker agents from shared/agents/
	uv run python install.py sync

install:  ## Install both targets (Claude Code + Copilot)
	uv run python install.py install --target all

install-claude:  ## Install the Claude Code target
	uv run python install.py install --target claude

install-copilot:  ## Install the GitHub Copilot target
	uv run python install.py install --target copilot

uninstall:  ## Uninstall both targets
	uv run python install.py uninstall --target all

telemetry:  ## Summarize .agentmaster/telemetry.md
	uv run python scripts/telemetry_report.py

clean-telemetry:  ## Prune telemetry, snapshots, and stale starts
	uv run python scripts/telemetry_report.py --prune
```

- [ ] **Step 2: Verify** — `make -n check` prints `bash scripts/code-quality.sh all`; `make help` lists every target with its description; `make check` runs the gate to completion (exit 0). If `make` is absent on the Windows side, run these in WSL.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat(make): thin makefile facade over the gate and installer"
```

### Task 5: Release workflow (`.github/workflows/release.yml`)

**Files:**
- Create: `.github/workflows/release.yml`

**What a release means (document this understanding in Task 6's README section):** pushing a `v*` tag is the release act. The workflow re-runs the full quality gate on the tagged commit, refuses tags that don't match `pyproject.toml`'s `version`, builds a runtime-only install bundle, and publishes a GitHub Release with auto-generated notes. A tag that fails the gate produces no release — delete the tag, fix, re-tag. The workflow never pushes commits.

- [ ] **Step 1: Write the workflow**

```yaml
name: release

on:
  push:
    tags: ['v*']

permissions:
  contents: write

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: '3.14'
      - name: Verify tag matches pyproject version
        run: |
          version=$(uv run python -c "import tomllib, pathlib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])")
          tag="${GITHUB_REF_NAME#v}"
          if [ "$tag" != "$version" ]; then
            echo "tag v$tag does not match pyproject version $version" >&2
            exit 1
          fi
      - run: uv sync
      - name: Quality gate
        run: bash scripts/code-quality.sh all
      - name: Build install bundle
        run: |
          git archive --format=zip -o "agentmaster-$GITHUB_REF_NAME.zip" HEAD \
            install.py installer shared agents copilot skills hooks criteria \
            scripts/telemetry_report.py README.md LICENSE pyproject.toml
      - name: Create GitHub release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release create "$GITHUB_REF_NAME" "agentmaster-$GITHUB_REF_NAME.zip" \
            --generate-notes --verify-tag
```

- [ ] **Step 2: Simulate the two release-only steps locally** (the gate itself is Measured Outcome 1):

```bash
# version check: current state must pass with tag v0.1.0 and fail with v9.9.9
version=$(uv run python -c "import tomllib, pathlib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['version'])")
for ref in v0.1.0 v9.9.9; do tag="${ref#v}"; [ "$tag" = "$version" ] && echo "$ref: match" || echo "$ref: MISMATCH (exit 1)"; done

# bundle: contains install.py + shared/, no tests/ or .github/
git archive --format=zip -o /tmp/agentmaster-test.zip HEAD \
  install.py installer shared agents copilot skills hooks criteria \
  scripts/telemetry_report.py README.md LICENSE pyproject.toml
uv run python -c "import zipfile; names = zipfile.ZipFile('/tmp/agentmaster-test.zip').namelist(); assert 'install.py' in names; assert any(n.startswith('shared/') for n in names); assert not any(n.startswith(('tests/', '.github/')) for n in names); print(f'{len(names)} entries, bundle OK')"
```

Expected: `v0.1.0: match`, `v9.9.9: MISMATCH (exit 1)`, `… entries, bundle OK`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "feat(ci): tag-gated release workflow with install bundle"
```

### Task 6: README rewrite

**Files:**
- Modify: `README.md` (restructure; the pipeline/hardening/research prose is kept but re-homed)

Target structure — sections in this order, with these mandatory contents (prose may be tightened, claims must stay accurate to the code):

1. **`# agentmaster`** — keep the current opening paragraph and platform line verbatim (it's good copy).
2. **`## Quick start`** — replaces both install sections. Canonical commands, no wrappers:

```bash
git clone https://github.com/rhawk117/agentmaster && cd agentmaster
python install.py install                  # both platforms; add --target claude|copilot
python install.py install --dry-run        # preview every file first
python install.py uninstall --target all   # clean removal, hook entries stripped
```

   State: Python 3.14+ required (stdlib only — no dependencies to install); flags win, a TTY prompts for model/git-guard choices, non-TTY uses defaults (`--model` overrides); every overwrite is backed up (`agentmaster-backup-<timestamp>/`); superpowers-plugin check prints the install commands when missing. Keep the "restart once / `CLAUDE_CODE_SUBAGENT_MODEL` unset / Explore stays haiku" caveats from the old Claude section and the pointer to `copilot/README.md`. Releases: each GitHub Release attaches `agentmaster-<tag>.zip` — unzip and run the same commands without cloning.
3. **`## Requirements`** — current section, trimmed to its first two sentences.
4. **`## The pipeline`**, **`## Language-agnostic by design`**, **`## Models and cost`** — keep as-is.
5. **`## Telemetry`** — new. The hook layer appends `hook,<agent>,,<tokens>,<duration_ms>` rows to `.agentmaster/telemetry.md`; read it with `make telemetry` (or `uv run python scripts/telemetry_report.py`); prune with `make clean-telemetry` — keeps the newest 500 lines and 5 compaction snapshots, drops `.starts` orphans older than a day (`--keep-lines/--keep-snapshots/--dry-run` to adjust). Nothing prunes automatically; hooks only ever append.
6. **`## Development`** — expand the current section: `make check` (or `bash scripts/code-quality.sh all` where make is absent — the exact command CI runs); the `make help` target list; generated worker files (`shared/agents/` + `make sync`) and drift-failing `validate`; requires `uv`.
7. **`## Releasing`** — new. Bump `version` in `pyproject.toml`, commit, `git tag v<version> && git push origin v<version>`; the release workflow re-runs the gate, rejects tag/version mismatches, attaches the runtime bundle, and auto-generates notes; a failed gate means no release — delete the tag, fix, re-tag.
8. **`## Hardening: …`** and **`## Research-driven revisions`** — keep, with one edit: item 7's "by `./sync-criteria.sh`" → "by `python install.py sync`" and the research section's "`scripts/telemetry-report.sh`" → "`scripts/telemetry_report.py`" (Outcome 5 covers these).

- [ ] **Step 1: Rewrite `README.md`** per the structure above.
- [ ] **Step 2: Verify** — `git grep -n "install-claude.sh\|install-copilot.sh\|sync-criteria.sh\|telemetry-report.sh" README.md`: no output. Every command named in the README exists: `make -n telemetry clean-telemetry check sync` exits 0; `python install.py install --dry-run --target all` exits 0 (with temp `CLAUDE_CONFIG_DIR`/`COPILOT_CONFIG_DIR` if run outside a sandbox).
- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "chore(docs): readme rewritten around install.py, make, and releases"
```

### Task 7: Final verification

- [ ] **Step 1: Run every Measured Outcomes row** (table above) from the branch head; capture actual output before claiming success (superpowers:verification-before-completion).
- [ ] **Step 2: Push and update PR #2** — `git push`, then update the PR body's test plan with the new outcomes (release workflow, wrapper removal, Makefile, prune, markers/fixtures).
- [ ] **Step 3:** Any review fixes commit as `fix(<scope>): …`.

## Self-Review (performed)

- **Spec coverage:** release workflow incl. "what it means" (T5 + README §7), wrapper removal (T3), Makefile façade (T4), telemetry pruning (T2), README (T6), pytest markers + fixtures (T1). All five user asks plus the test-consolidation addition have tasks.
- **Placeholder scan:** all code steps carry complete code; README task specifies exact commands and mandatory statements rather than full prose (prose is the deliverable of that task, constrained by Outcome 5 and the listed claims).
- **Type consistency:** `prune()` signature identical in T2 tests, implementation, and T4's `clean-telemetry`; fixture names in T1 match their uses in T2's moved tests; `SHELL_SCRIPTS` glob in T3 matches what T4's `shell` target lints; bundle path list identical in T5 workflow and T5 simulation.
- **Ordering hazards checked:** T1 and T2 both edit `tests/test_hooks.py` (sequential); T3 must precede T4/T6 (they reference the post-wrapper world); Outcome 5's zero-grep forced the docstring wording in T3 Step 3.
